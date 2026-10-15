"""Person D boundary tests. Fake A/B/C; these do not certify PostgreSQL or LangGraph."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, RLock, get_ident

import pytest
from app import create_app
from app.agent.contracts import (
    CoverageRecord, FailureInfo, InventoryField, InventoryView, JobStatus,
    Mapping, MappingDraft, ModelDraft, ResourceSummary, Table, ValidationFinding,
)
from app.common.api_schemas import EditMappingResponse, RoutingReviewPackage
from app.mappings.service import MappingError, MappingService


class FakeRepository:
    """Only a test double for the atomic repository contract; never wired at startup."""
    def __init__(self):
        self.jobs, self.keys, self.packages, self.drafts, self.edits = {}, {}, {}, {}, {}
        self.edit_keys, self.pending, self.consumed = {}, {}, set()
        self.lock = RLock()

    def find_job(self, owner, key):
        with self.lock:
            return self.jobs.get(self.keys.get((owner, key)))

    def create_job(self, job):
        with self.lock:
            prior = self.find_job(job.owner, job.idempotency_key)
            if prior:
                if prior.request != job.request:
                    raise MappingError('idempotency_conflict', 'Key reused with another request.')
                return prior, False
            self.jobs[job.view.job_id] = job
            self.keys[job.owner, job.idempotency_key] = job.view.job_id
            return job, True

    def get_job(self, owner, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return job if job and job.owner == owner else None

    def update(self, job_id, **updates):
        job = self.jobs[job_id]
        self.jobs[job_id] = replace(job, view=job.view.model_copy(update=updates))

    def claim_job(self, owner, job_id):
        with self.lock:
            job = self.get_job(owner, job_id)
            if not job or job.view.status != JobStatus.QUEUED:
                return False
            self.update(job_id, status=JobStatus.RUNNING)
            return True

    def save_model_draft(self, owner, job_id, draft):
        self.drafts[job_id] = draft.model_dump_json()

    def publish(self, owner, job_id, package, status):
        with self.lock:
            self.packages[job_id] = package.model_dump_json()
            self.update(job_id, status=status)

    def fail(self, owner, job_id, failure):
        with self.lock:
            self.update(job_id, status=JobStatus.FAILED, failure=failure)

    def get_package(self, owner, job_id):
        with self.lock:
            value = self.packages.get(job_id) if self.get_job(owner, job_id) else None
            return RoutingReviewPackage.model_validate_json(value) if value else None

    def request_edit(self, owner, job_id, key, edit):
        with self.lock:
            job = self.get_job(owner, job_id)
            if not job:
                raise MappingError('job_not_found', 'Routing job not found.', 404)
            prior_id = self.edit_keys.get((job_id, key))
            receipt = self.edits.get((job_id, prior_id or edit.edit_id))
            if receipt:
                original, response = receipt
                if original != edit:
                    raise MappingError('edit_conflict', 'Idempotency key or edit ID already used.')
                self.edit_keys[job_id, key] = edit.edit_id
                return response, False
            if job.view.status not in (JobStatus.BLOCKED, JobStatus.AWAITING_REVIEW):
                raise MappingError('job_not_reviewable', 'Job is not ready for review.')
            package = self.get_package(owner, job_id)
            if edit.target not in {t.id for t in package.model_draft.tables}:
                raise MappingError('invalid_target_reference', 'Unknown target table.', 422)
            response = EditMappingResponse(job_id=job_id, edit_id=edit.edit_id, status=JobStatus.EDIT_REQUESTED)
            self.edits[job_id, edit.edit_id] = (edit, response)
            self.edit_keys[job_id, key] = edit.edit_id
            self.pending[job_id] = edit
            self.update(job_id, status=JobStatus.EDIT_REQUESTED)
            return response, True

    def claim_edit(self, owner, job_id):
        with self.lock:
            job = self.get_job(owner, job_id)
            if not job or job.view.status != JobStatus.EDIT_REQUESTED:
                return None
            self.update(job_id, status=JobStatus.REVISING)
            return self.pending[job_id]

    def publish_edit(self, owner, job_id, edit_id, package, status):
        with self.lock:
            assert self.pending[job_id].edit_id == edit_id
            self.publish(owner, job_id, package, status)
            self.consumed.add((job_id, edit_id))
            del self.pending[job_id]


def inventory(owner, snapshot):
    if snapshot != 'snapshot-1' or owner != 'demo':
        return None
    return InventoryView(snapshot_id=snapshot,
        resources=[ResourceSummary(resource_id='orders', name='orders', kind='collection', field_count=1)],
        fields=[InventoryField(ref={'source_id': 'source-1', 'resource_id': 'orders', 'field_path': 'id'}, type='text', nullable=False, repeating=False, status='stable')])


def draft():
    return ModelDraft(revision=1, tables=[Table(id=name, name=name, kind='event', grain='One row per order',
        key=['id'], attributes=[dict(id='id', type='text', nullable=False, confidence=0.9,
        evidence=[dict(resource_id='orders', field_path='id')])], relationships=[], rationale='Order grain preserved.')
        for name in ('fact_orders', 'fact_lines')], source_coverage=[])


def project(model, inv, catalog):
    return RoutingReviewPackage(model_draft=model,
        mapping_draft=MappingDraft(revision=model.revision, based_on_model_revision=model.revision, mappings=[
            Mapping(target=f'{t.id}.id', sources=['orders.id'], confidence=0.9) for t in model.tables]),
        is_new={t.id: True for t in model.tables},
        findings=[ValidationFinding(code='ambiguous_date', severity='blocker', target='fact_orders', message='Confirm the date format.')],
        coverage=[CoverageRecord(resource_id='orders', field_path='id', disposition='represented', reason='Mapped to key.')])


def resume_edit(job_id, package, edit):
    return package.model_draft.model_copy(update={'revision': package.model_draft.revision + 1})


def make_app(repo, graph=None, projection=project, dispatch=None):
    service = MappingService(repo, inventory, graph or (lambda *args: draft()), projection, 'fake', 'snapshot-1', resume_edit=resume_edit)
    queue = []
    class Config:
        TESTING = True
        SECRET_KEY = 'test'
        MAPPING_SERVICE_FACTORY = staticmethod(lambda app: service)
        MAPPING_DISPATCH = staticmethod(dispatch or (lambda owner, job_id: queue.append((owner, job_id))))
    return create_app(Config), service, queue


def client_for(app, username='demo'):
    client = app.test_client()
    client.post('/api/auth/login', json={'username': username, 'password': 'test'})
    return client


def start(client, key='key-1', **body):
    return client.post('/api/mappings/jobs', headers={'Idempotency-Key': key}, json=body)


@pytest.fixture
def setup():
    repo = FakeRepository()
    app, service, queue = make_app(repo)
    return repo, app, service, queue, client_for(app)


def test_create_replay_conflict_and_no_inline_execution(setup):
    repo, app, service, queue, client = setup
    first = start(client)
    assert first.status_code == 202 and first.json['status'] == 'queued'
    assert start(client).json == first.json
    assert len(queue) == 1 and repo.drafts == {}
    assert start(client, source_snapshot_id='other').status_code == 409
    assert first.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('body,status', [({'source_snapshot_id': 'missing'}, 404), ({'extra': True}, 400), ({'source_snapshot_id': 123}, 400)])
def test_invalid_creation(setup, body, status):
    *_, client = setup
    assert start(client, **body).status_code == status
    assert client.post('/api/mappings/jobs', json={}).status_code == 400
    assert client.post('/api/mappings/jobs', headers={'Idempotency-Key': 'k'}, data='{', content_type='application/json').status_code == 400


def test_saved_package_decisions_refresh_and_replay(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']
    path = f'/api/mappings/jobs/{job_id}'
    assert client.get(path + '/package').json['payload'] is None
    assert client.put(path + '/edits', headers={'Idempotency-Key': 'edit-key'}, json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'}).status_code == 409
    service.execute(*queue.pop())
    assert job_id in repo.drafts
    package = client.get(path + '/package').json
    assert package['status'] == 'blocked'
    assert package['payload']['findings'][0]['code'] == 'ambiguous_date'
    assert package['payload']['coverage'][0]['disposition'] == 'represented'
    edit = {'edit_id': 'edit-1', 'target': 'fact_orders', 'decision': 'reject'}
    first = client.put(path + '/edits', headers={'Idempotency-Key': 'edit-key'}, json=edit)
    assert first.status_code == 202 and not first.json['replayed']
    assert first.json['status'] == 'edit_requested' and first.json['payload'] is None
    assert client.get(path).json['status'] == 'edit_requested'
    assert client.get(path + '/package').json['payload']['decisions'] == {}
    service.execute(*queue.pop())
    assert (job_id, 'edit-1') in repo.consumed
    # Recreate application/service and use a fresh browser session against the same store.
    new_app, _, _ = make_app(repo)
    fresh = client_for(new_app)
    saved = fresh.get(path + '/package').json['payload']
    assert saved['decisions'] == {'fact_orders': 'reject'}
    assert len(saved['model_draft']['tables']) == 2
    assert fresh.get(path).json['model_mode'] == 'fake'
    replay = fresh.put(path + '/edits', headers={'Idempotency-Key': 'edit-key'}, json=edit)
    assert replay.status_code == 202 and replay.json == {**first.json, 'replayed': True}
    assert fresh.get(path).json['status'] == 'blocked'
    assert fresh.put(path + '/edits', headers={'Idempotency-Key': 'edit-key'}, json={**edit, 'decision': 'accept'}).status_code == 409
    assert fresh.put(path + '/edits', headers={'Idempotency-Key': 'new-key'}, json={**edit, 'edit_id': 'other', 'target': 'invented'}).status_code == 422


def test_auth_and_ownership(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']
    path = f'/api/mappings/jobs/{job_id}'
    assert app.test_client().get(path).status_code == 401
    other = client_for(app, 'other')
    for suffix in ('', '/package'):
        assert other.get(path + suffix).status_code == 404
    assert other.put(path + '/edits', headers={'Idempotency-Key': 'edit-key'}, json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'}).status_code == 404
    assert start(other).status_code == 404


def test_worker_claim_and_concurrent_creation(setup):
    repo, app, service, queue, client = setup
    from app.common.api_schemas import CreateMappingJobRequest
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.create('demo', 'same', CreateMappingJobRequest(), lambda *args: queue.append(args)), range(12)))
    assert len({r.job_id for r in results}) == 1 and len(queue) == 1
    count = []
    service.run_graph = lambda *args: (count.append(1), draft())[1]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: service.execute(*queue[0]), range(6)))
    assert len(count) == 1


def test_background_runtime_returns_while_graph_runs(monkeypatch):
    entered, release = Event(), Event()
    threads = []
    def graph(*args):
        threads.append(get_ident()); entered.set()
        assert release.wait(5)
        return draft()
    repo = FakeRepository()
    service = MappingService(repo, inventory, graph, project, 'fake', 'snapshot-1')
    class Config:
        TESTING = True
        SECRET_KEY = 'test'
        MAPPING_SERVICE_FACTORY = staticmethod(lambda app: service)
    monkeypatch.setenv('GENLEDGE_AGENT_INLINE_RUN', '1')
    app = create_app(Config)
    try:
        client = client_for(app)
        result = start(client)
        assert result.status_code == 202 and entered.wait(2)
        assert threads == [threads[0]] and threads[0] != get_ident()
        assert client.get(f"/api/mappings/jobs/{result.json['job_id']}").json['status'] == 'running'
    finally:
        release.set()
        app.extensions['mapping_executor'].shutdown(wait=True)


def test_failures_are_persisted_without_exception_details(setup):
    repo, app, service, queue, client = setup
    def broken(*args):
        raise RuntimeError('secret credential sentinel')
    service.run_graph = broken
    job_id = start(client).json['job_id']
    service.execute(*queue.pop())
    result = client.get(f'/api/mappings/jobs/{job_id}')
    assert result.json['status'] == 'failed'
    assert 'sentinel' not in result.text
    assert result.json['failure']['retryable']


def test_awaiting_review_and_typed_graph_failure(setup):
    repo, app, service, queue, client = setup
    service.project = lambda *args: project(*args).model_copy(update={'findings': []})
    first = start(client).json['job_id']; service.execute(*queue.pop())
    assert client.get(f'/api/mappings/jobs/{first}').json['status'] == 'awaiting_review'
    service.run_graph = lambda *args: FailureInfo(code='budget_exhausted', message='Budget exhausted.', retryable=False)
    second = start(client, key='second').json['job_id']; service.execute(*queue.pop())
    assert client.get(f'/api/mappings/jobs/{second}').json['failure']['code'] == 'budget_exhausted'


def test_missing_dependencies_are_explicit(monkeypatch):
    monkeypatch.delenv('GENLEDGE_MAPPING_RUNTIME_FACTORY', raising=False)
    app = create_app()
    response = start(client_for(app))
    assert response.status_code == 503
    assert response.json['error']['code'] == 'routing_not_configured'


def test_dispatch_and_projection_failures(setup):
    repo, app, service, queue, client = setup
    def broken(*args):
        raise RuntimeError('sensitive sentinel')
    app.extensions['mapping_dispatch'] = broken
    job_id = start(client).json['job_id']
    assert client.get(f'/api/mappings/jobs/{job_id}').json['failure']['code'] == 'dispatch_failed'
    app.extensions['mapping_dispatch'] = lambda *args: queue.append(args)
    service.project = broken
    job_id = start(client, key='next').json['job_id']
    service.execute(*queue.pop())
    assert job_id in repo.drafts  # Model revision survives projection failure.
    assert client.get(f'/api/mappings/jobs/{job_id}').json['status'] == 'failed'
    assert 'sentinel' not in client.get(f'/api/mappings/jobs/{job_id}/package').text


def test_snapshot_requirements(setup):
    repo, app, service, queue, client = setup
    service.default_snapshot_id = None
    assert start(client).status_code == 400
    assert start(client, source_snapshot_id=' ').status_code == 400
    service.inventory = lambda owner, snapshot: InventoryView(snapshot_id=snapshot, resources=[], fields=[])
    assert start(client, source_snapshot_id='empty').status_code == 422
    assert not queue


@pytest.mark.parametrize('key', [None, '', '   ', 'x' * 201])
def test_edit_header_required(setup, key):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']; service.execute(*queue.pop())
    result = client.put(f'/api/mappings/jobs/{job_id}/edits',
        headers={} if key is None else {'Idempotency-Key': key},
        json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'})
    assert result.status_code == 400
    assert result.json['error']['code'] == 'invalid_idempotency_key'
    assert not repo.edits and not queue


def test_pending_edit_replay_conflicts_and_single_worker_consumption(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']; service.execute(*queue.pop())
    path = f'/api/mappings/jobs/{job_id}'
    edit = {'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'}
    submit = lambda key, body: client.put(path + '/edits', headers={'Idempotency-Key': key}, json=body)
    assert submit('header', edit).status_code == 202
    assert submit('header', edit).json['replayed']
    assert submit('other-header', edit).json['replayed']
    assert submit('header', {**edit, 'edit_id': 'different'}).status_code == 409
    assert submit('third-header', {**edit, 'decision': 'accept'}).status_code == 409
    assert len(repo.edits) == 1
    calls = []
    def resume(*args):
        calls.append(args[2].edit_id)
        return resume_edit(*args)
    service.resume_edit = resume
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda _: service.execute('demo', job_id), range(6)))
    queue.clear()
    assert calls == ['e']
    assert client.get(path).json['status'] == 'blocked'
    assert submit('header', edit).json['replayed'] and not queue
    # A later edit preserves the earlier decision and all unrelated tables.
    assert submit('next', {'edit_id': 'next', 'target': 'fact_lines', 'decision': 'accept'}).status_code == 202
    service.execute(*queue.pop())
    package = client.get(path + '/package').json['payload']
    assert package['decisions'] == {'fact_orders': 'reject', 'fact_lines': 'accept'}
    assert len(package['model_draft']['tables']) == 2
    assert package['model_draft']['revision'] == 3
    assert package['mapping_draft']['based_on_model_revision'] == 3


def test_pending_edit_survives_dispatch_failure_and_app_restart(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']; service.execute(*queue.pop())
    path = f'/api/mappings/jobs/{job_id}'
    def broken(*args):
        raise RuntimeError('private failure details')
    app.extensions['mapping_dispatch'] = broken
    edit = {'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'}
    response = client.put(path + '/edits', headers={'Idempotency-Key': 'key'}, json=edit)
    assert response.status_code == 503 and 'private' not in response.text
    assert client.get(path).json['status'] == 'edit_requested'
    new_app, worker, new_queue = make_app(repo)
    fresh = client_for(new_app)
    replay = fresh.put(path + '/edits', headers={'Idempotency-Key': 'key'}, json=edit)
    assert replay.status_code == 202 and replay.json['replayed']
    worker.execute(*new_queue.pop())
    assert fresh.get(path + '/package').json['payload']['decisions'] == {'fact_orders': 'reject'}


def test_edit_resume_failure_does_not_publish_or_consume_edit(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']; service.execute(*queue.pop())
    path = f'/api/mappings/jobs/{job_id}'
    before = client.get(path + '/package').json['payload']
    service.resume_edit = lambda *args: FailureInfo(code='resume_failed', message='Unable to revise.', retryable=True)
    client.put(path + '/edits', headers={'Idempotency-Key': 'key'}, json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'})
    service.execute(*queue.pop())
    assert client.get(path).json['status'] == 'failed'
    assert client.get(path + '/package').json['payload'] == before
    assert (job_id, 'e') not in repo.consumed


def test_edit_runs_off_request_thread(monkeypatch):
    repo = FakeRepository()
    entered, release = Event(), Event()
    thread_ids = []
    def resume(*args):
        thread_ids.append(get_ident()); entered.set()
        assert release.wait(5)
        return resume_edit(*args)
    service = MappingService(repo, inventory, lambda *args: draft(), project, 'fake', 'snapshot-1', resume_edit=resume)
    # Seed the published job before starting the background executor.
    from app.common.api_schemas import CreateMappingJobRequest
    job = service.create('demo', 'create', CreateMappingJobRequest(), lambda *args: None)
    service.execute('demo', job.job_id)
    class Config:
        TESTING = True
        SECRET_KEY = 'test'
        MAPPING_SERVICE_FACTORY = staticmethod(lambda app: service)
    monkeypatch.setenv('GENLEDGE_AGENT_INLINE_RUN', '1')
    app = create_app(Config)
    try:
        client = client_for(app)
        response = client.put(f'/api/mappings/jobs/{job.job_id}/edits', headers={'Idempotency-Key': 'key'}, json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'})
        assert response.status_code == 202 and entered.wait(2)
        assert thread_ids[0] != get_ident()
        assert client.get(f'/api/mappings/jobs/{job.job_id}').json['status'] == 'revising'
    finally:
        release.set()
        app.extensions['mapping_executor'].shutdown(wait=True)


def test_edit_cannot_be_marked_applied_with_old_revision(setup):
    repo, app, service, queue, client = setup
    job_id = start(client).json['job_id']; service.execute(*queue.pop())
    path = f'/api/mappings/jobs/{job_id}'
    service.resume_edit = lambda job_id, package, edit: package.model_draft
    client.put(path + '/edits', headers={'Idempotency-Key': 'key'}, json={'edit_id': 'e', 'target': 'fact_orders', 'decision': 'reject'})
    service.execute(*queue.pop())
    assert client.get(path).json['status'] == 'failed'
    assert client.get(path + '/package').json['payload']['decisions'] == {}
    assert (job_id, 'e') not in repo.consumed
