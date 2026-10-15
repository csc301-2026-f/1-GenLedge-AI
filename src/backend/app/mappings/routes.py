"""Authenticated HTTP boundary; graph execution is dispatched outside the request."""
from flask import Blueprint, current_app, jsonify, request, session
from pydantic import ValidationError

from app.common.api_schemas import (
    CreateMappingJobRequest, CreateMappingJobResponse, EditMappingRequest,
    MappingPackageResponse,
)
from app.common.errors import make_error
from .service import MappingError

bp = Blueprint('mappings', __name__, url_prefix='/api/mappings')


def response(model, status=200):
    return jsonify(model.model_dump(mode='json')), status


@bp.before_request
def authenticate():
    if not session.get('user'):
        raise MappingError('unauthorized', 'Authentication required.', 401)


@bp.after_request
def no_cache(result):
    result.headers['Cache-Control'] = 'no-store'
    return result


@bp.errorhandler(MappingError)
def mapping_error(error):
    return response(make_error(error.code, error.message), error.status)


@bp.errorhandler(Exception)
def unexpected_error(error):
    # Do not include arbitrary database/provider exception text in HTTP responses.
    return response(make_error('routing_unavailable', 'Routing is temporarily unavailable. Please retry.'), 503)


def context():
    service = current_app.extensions.get('mapping_service')
    if service is None:
        raise MappingError('routing_not_configured', 'Routing dependencies are not configured.', 503)
    # US1 currently has one demo ID for every login. Use its username to avoid
    # sharing routing jobs between distinct demo sessions. Replace with org scope
    # when the production identity provider lands.
    return service, session['user']['username']


def parse(schema):
    try:
        return schema.model_validate(request.get_json(silent=True))
    except ValidationError:
        raise MappingError('invalid_request', 'Expected a valid JSON request with no unknown fields.', 400)


def idempotency_key():
    key = request.headers.get('Idempotency-Key', '')
    if not key.strip() or len(key) > 200:
        raise MappingError('invalid_idempotency_key', 'Idempotency-Key must contain 1–200 characters.', 400)
    return key


@bp.post('/jobs')
def create_job():
    service, owner = context()
    key = idempotency_key()
    payload = parse(CreateMappingJobRequest)
    job = service.create(owner, key, payload, current_app.extensions['mapping_dispatch'])
    return response(CreateMappingJobResponse(job_id=job.job_id, status=job.status), 202)


@bp.get('/jobs/<job_id>')
def get_job(job_id):
    service, owner = context()
    return response(service.get(owner, job_id).view)


@bp.get('/jobs/<job_id>/package')
def get_package(job_id):
    service, owner = context()
    job, package = service.package(owner, job_id)
    return response(MappingPackageResponse(
        payload=package.model_dump(mode='json') if package else None,
        status=job.status, failure=job.failure))


@bp.put('/jobs/<job_id>/edits')
def edit_job(job_id):
    service, owner = context()
    result = service.decide(owner, job_id, idempotency_key(), parse(EditMappingRequest),
                            current_app.extensions['mapping_dispatch'])
    return response(result, 202)
