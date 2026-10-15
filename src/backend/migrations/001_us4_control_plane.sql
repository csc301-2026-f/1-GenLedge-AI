-- Metadata and redacted evidence only; no connector credentials or raw source rows.
CREATE TABLE sources (
    id text PRIMARY KEY,
    organization_id text NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE source_snapshots (
    id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(id),
    fingerprint text NOT NULL,
    contract_version text NOT NULL,
    sealed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, fingerprint)
);
CREATE TABLE source_resources (
    snapshot_id text NOT NULL REFERENCES source_snapshots(id),
    resource_id text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('collection', 'table', 'sheet', 'file')),
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (snapshot_id, resource_id),
    UNIQUE (snapshot_id, position)
);
CREATE TABLE source_fields (
    snapshot_id text NOT NULL,
    resource_id text NOT NULL,
    field_path text NOT NULL,
    type text NOT NULL CHECK (type IN ('text', 'number', 'boolean', 'date', 'timestamp', 'json')),
    nullable boolean NOT NULL,
    repeating boolean NOT NULL,
    samples text[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(samples) <= 3 AND array_position(samples, NULL) IS NULL),
    description text,
    native_type text,
    ambiguity text,
    status text NOT NULL CHECK (status IN ('stable', 'new', 'unknown')),
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (snapshot_id, resource_id, field_path),
    UNIQUE (snapshot_id, position),
    FOREIGN KEY (snapshot_id, resource_id) REFERENCES source_resources(snapshot_id, resource_id)
);

CREATE FUNCTION guard_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.sealed THEN
        RAISE EXCEPTION 'source snapshot is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON source_snapshots
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot();
CREATE FUNCTION guard_snapshot_child() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM 1 FROM source_snapshots WHERE id = OLD.snapshot_id AND NOT sealed FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'source snapshot is immutable' USING ERRCODE = '23514'; END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM 1 FROM source_snapshots WHERE id = NEW.snapshot_id AND NOT sealed FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'source snapshot is sealed or missing' USING ERRCODE = '23514'; END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER immutable_resource BEFORE INSERT OR UPDATE OR DELETE ON source_resources
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot_child();
CREATE TRIGGER immutable_field BEFORE INSERT OR UPDATE OR DELETE ON source_fields
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot_child();

CREATE TABLE target_catalogues (
    id text PRIMARY KEY,
    organization_id text NOT NULL,
    payload_json jsonb NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
    contract_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, organization_id)
);
CREATE TABLE proposal_jobs (
    id text PRIMARY KEY,
    organization_id text NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) > 0),
    request_hash text NOT NULL,
    catalog_ref text,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'revising', 'awaiting_review', 'edit_requested',
        'approval_requested', 'cancelling', 'blocked', 'approved', 'failed', 'cancelled')),
    created_by text NOT NULL,
    active_thread_id text NOT NULL,
    model_mode text NOT NULL CHECK (model_mode IN ('auto', 'fake', 'live')),
    budgets_json jsonb NOT NULL,
    failure_json jsonb,
    contract_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, idempotency_key),
    FOREIGN KEY (catalog_ref, organization_id) REFERENCES target_catalogues(id, organization_id)
);
CREATE TABLE proposal_job_snapshots (
    job_id text NOT NULL REFERENCES proposal_jobs(id),
    snapshot_id text NOT NULL REFERENCES source_snapshots(id),
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (job_id, snapshot_id),
    UNIQUE (job_id, position)
);
CREATE TABLE proposal_revisions (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES proposal_jobs(id),
    revision integer NOT NULL CHECK (revision >= 0),
    model_draft_json jsonb NOT NULL,
    mapping_draft_json jsonb,
    table_is_new_json jsonb NOT NULL DEFAULT '{}',
    contract_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, revision),
    UNIQUE (id, job_id)
);
CREATE TABLE proposal_findings (
    revision_id text NOT NULL REFERENCES proposal_revisions(id),
    position integer NOT NULL CHECK (position >= 0),
    payload_json jsonb NOT NULL,
    PRIMARY KEY (revision_id, position)
);
CREATE TABLE source_coverage_records (
    revision_id text NOT NULL REFERENCES proposal_revisions(id),
    resource_id text NOT NULL,
    field_path text NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    payload_json jsonb NOT NULL,
    PRIMARY KEY (revision_id, resource_id, field_path),
    UNIQUE (revision_id, position)
);
CREATE TABLE tool_results (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES proposal_jobs(id),
    tool_call_id text NOT NULL,
    tool text NOT NULL,
    arguments_json jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('ok', 'error')),
    payload_json jsonb NOT NULL,
    redacted boolean NOT NULL CHECK (redacted),
    bytes_estimate integer NOT NULL CHECK (bytes_estimate >= 0),
    contract_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, tool_call_id)
);
CREATE TABLE proposal_edits (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES proposal_jobs(id),
    revision_id text NOT NULL,
    reviewer text NOT NULL,
    reviewer_role text NOT NULL,
    target text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('accept', 'reject')),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) > 0),
    contract_version text NOT NULL,
    applied_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, idempotency_key),
    FOREIGN KEY (revision_id, job_id) REFERENCES proposal_revisions(id, job_id)
);

CREATE FUNCTION guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'persisted artifact is immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER immutable_revision BEFORE UPDATE OR DELETE ON proposal_revisions
    FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER immutable_finding BEFORE UPDATE OR DELETE ON proposal_findings
    FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER immutable_coverage BEFORE UPDATE OR DELETE ON source_coverage_records
    FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER immutable_tool_result BEFORE UPDATE OR DELETE ON tool_results
    FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER immutable_catalogue BEFORE UPDATE OR DELETE ON target_catalogues
    FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER no_truncate_snapshot BEFORE TRUNCATE ON source_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER no_truncate_resource BEFORE TRUNCATE ON source_resources
    FOR EACH STATEMENT EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER no_truncate_field BEFORE TRUNCATE ON source_fields
    FOR EACH STATEMENT EXECUTE FUNCTION guard_artifact();

CREATE FUNCTION guard_job_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['status', 'failure_json', 'updated_at', 'active_thread_id'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'failure_json', 'updated_at', 'active_thread_id']) THEN
        RAISE EXCEPTION 'job inputs are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_job_inputs BEFORE UPDATE ON proposal_jobs
    FOR EACH ROW EXECUTE FUNCTION guard_job_inputs();
CREATE FUNCTION guard_edit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'edit audit is immutable' USING ERRCODE = '23514'; END IF;
    IF (to_jsonb(NEW) - 'applied_at') IS DISTINCT FROM (to_jsonb(OLD) - 'applied_at')
       OR (OLD.applied_at IS NOT NULL AND OLD.applied_at IS DISTINCT FROM NEW.applied_at) THEN
        RAISE EXCEPTION 'edit audit is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_edit BEFORE UPDATE OR DELETE ON proposal_edits
    FOR EACH ROW EXECUTE FUNCTION guard_edit();

CREATE INDEX proposal_jobs_status_idx ON proposal_jobs(status, created_at);
CREATE INDEX pending_edits_idx ON proposal_edits(job_id) WHERE applied_at IS NULL;
