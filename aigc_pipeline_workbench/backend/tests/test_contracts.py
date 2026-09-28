from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    ArtifactType,
    ErrorCode,
    JobStatus,
    LogLevel,
    ParameterValueType,
    ServiceStatus,
)
from app.domain.models import JobError, JobProgress, ParameterDefinition
from app.schemas.common import (
    CONTRACT_VERSION,
    ApiErrorEnvelope,
    ArtifactInput,
    ErrorResponse,
    error_detail,
)
from app.schemas.job import (
    JobCancelResponse,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from app.schemas.service import ServiceHealthResponse, ServiceMetadataResponse


def test_contract_version_is_v1():
    assert CONTRACT_VERSION == "v1"


def test_health_response_supports_minimal_fields():
    response = ServiceHealthResponse(
        contract_version=CONTRACT_VERSION,
        status=ServiceStatus.ONLINE,
        service="mock_fast",
        version="0.1.0",
    )

    assert response.gpu is None
    assert response.load is None


def test_metadata_can_describe_segmentation_service():
    metadata = ServiceMetadataResponse(
        contract_version=CONTRACT_VERSION,
        module_key="image_segmentation",
        name="Image Segmentation",
        version="0.3.0",
        input_artifact_types=["image"],
        output_artifact_types=["mask", "report"],
        parameter_schema=[
            ParameterDefinition(
                key="threshold",
                label="Confidence Threshold",
                value_type=ParameterValueType.NUMBER,
                default=0.5,
                minimum=0,
                maximum=1,
            )
        ],
        supports_cancel=True,
        supports_progress=True,
        max_concurrent_jobs=1,
    )

    assert metadata.input_artifact_types == ["image"]
    assert metadata.parameter_schema[0].key == "threshold"


def test_job_submit_request_requires_url_input_without_storage_path():
    request = JobSubmitRequest(
        contract_version=CONTRACT_VERSION,
        job_id="job_001",
        module_key="image_segmentation",
        inputs=[
            ArtifactInput(
                artifact_id="artifact_001",
                type=ArtifactType.IMAGE,
                name="input.png",
                url="https://storage.example.com/artifact_001",
            )
        ],
        parameters={"threshold": 0.62},
    )

    assert str(request.inputs[0].url).startswith("https://")


def test_job_submit_request_rejects_plain_file_path():
    with pytest.raises(ValidationError):
        JobSubmitRequest(
            contract_version=CONTRACT_VERSION,
            job_id="job_001",
            module_key="image_segmentation",
            inputs=[
                ArtifactInput(
                    artifact_id="artifact_001",
                    type=ArtifactType.IMAGE,
                    url="/data/input.png",
                )
            ],
        )


def test_job_status_response_can_represent_running():
    response = JobStatusResponse(
        job_id="job_001",
        status=JobStatus.RUNNING,
        progress=JobProgress(percent=45, phase="inference"),
        logs=[
            {
                "seq": 1,
                "level": LogLevel.INFO,
                "message": "loading model",
                "created_at": datetime.now(timezone.utc),
            }
        ],
        updated_at=datetime.now(timezone.utc),
    )

    assert response.progress.percent == 45


def test_job_status_response_can_represent_succeeded_with_outputs():
    response = JobStatusResponse(
        job_id="job_001",
        status=JobStatus.SUCCEEDED,
        progress=JobProgress(percent=100),
        output_artifacts=[
            {
                "artifact_id": "artifact_mask_001",
                "type": ArtifactType.MASK,
                "name": "object_001_mask.png",
                "uri": "https://storage.example.com/object_001_mask.png",
                "mime_type": "image/png",
                "size_bytes": 128443,
                "metadata": {"class": "bottle", "confidence": 0.91},
            }
        ],
        finished_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    assert response.output_artifacts[0].metadata["class"] == "bottle"


def test_cancel_response_uses_best_effort_states():
    cancelling = JobCancelResponse(job_id="job_001", status=JobStatus.CANCELLING)
    cancelled = JobCancelResponse(job_id="job_001", status=JobStatus.CANCELLED)

    assert cancelling.status is JobStatus.CANCELLING
    assert cancelled.status is JobStatus.CANCELLED


def test_error_response_serializes_stable_structure():
    error = JobError(
        code=ErrorCode.INVALID_PARAMETER,
        message="threshold must be between 0 and 1",
        details={"parameter": "threshold"},
    )
    detail = error_detail(error)
    response = ErrorResponse(error=detail)
    envelope = ApiErrorEnvelope(error=detail)

    assert response.error.code is ErrorCode.INVALID_PARAMETER
    assert envelope.model_dump()["success"] is False
