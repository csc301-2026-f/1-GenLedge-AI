import pytest
from pydantic import ValidationError

from app.agent.contracts import JobStatus
from app.common.api_schemas import CreateMappingJobRequest, CreateMappingJobResponse, EditMappingRequest, MappingJobResponse
from app.common.errors import make_error


def test_api_request_and_response_contracts():
    request = CreateMappingJobRequest.model_validate({"source_snapshot_id": "snapshot-1", "catalog_ref": None})
    response = CreateMappingJobResponse(job_id="job-1", status=JobStatus.QUEUED)
    edit = EditMappingRequest(edit_id="edit-1", target="fact_orders.order_id", decision="reject")
    assert request.source_snapshot_id == "snapshot-1"
    assert response.status == JobStatus.QUEUED
    assert edit.decision == "reject"


def test_job_status_and_error_envelopes_reject_invalid_values():
    with pytest.raises(ValidationError):
        MappingJobResponse(job_id="job-1", status="unknown", source_snapshot_id="snapshot-1")
    error = make_error("invalid_model_output", "The proposal is invalid.")
    assert error.error.details == {}
