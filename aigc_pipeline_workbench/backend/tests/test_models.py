from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    ArtifactRetention,
    ArtifactType,
    ArtifactVisibility,
    ErrorCode,
    JobStatus,
    LogLevel,
    LogSource,
    ParameterValueType,
    ServiceStatus,
)
from app.domain.models import (
    Artifact,
    ArtifactRef,
    Job,
    JobLog,
    ParameterDefinition,
    ServiceCapabilities,
)


def test_valid_job_can_be_created():
    now = datetime.now(timezone.utc)
    job = Job(
        job_id="job_001",
        service_id="service_001",
        module_key="image_segmentation",
        status=JobStatus.CREATED,
        parameters={"threshold": 0.5},
        input_artifacts=[
            ArtifactRef(
                artifact_id="artifact_001",
                type=ArtifactType.IMAGE,
                uri="/api/v1/artifacts/artifact_001/file",
            )
        ],
        created_at=now,
        updated_at=now,
    )

    assert job.status is JobStatus.CREATED
    assert job.input_artifacts[0].artifact_id == "artifact_001"


def test_invalid_job_status_is_rejected():
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError):
        Job(
            job_id="job_001",
            service_id="service_001",
            module_key="image_segmentation",
            status="running_forever",
            created_at=now,
            updated_at=now,
        )


def test_number_parameter_definition_supports_min_and_max():
    parameter = ParameterDefinition(
        key="threshold",
        label="Confidence Threshold",
        value_type=ParameterValueType.NUMBER,
        required=False,
        default=0.5,
        minimum=0,
        maximum=1,
    )

    assert parameter.minimum == 0
    assert parameter.maximum == 1


def test_artifact_ref_does_not_require_storage_path():
    ref = ArtifactRef(
        artifact_id="artifact_001",
        type=ArtifactType.IMAGE,
        uri="/api/v1/artifacts/artifact_001/file",
    )

    assert ref.uri == "/api/v1/artifacts/artifact_001/file"
    assert not hasattr(ref, "storage_key")


def test_artifact_model_can_keep_storage_key_private_to_backend():
    now = datetime.now(timezone.utc)
    artifact = Artifact(
        artifact_id="artifact_001",
        type=ArtifactType.IMAGE,
        name="input.png",
        uri="/api/v1/artifacts/artifact_001/file",
        storage_key="runs/job_001/inputs/artifact_001.png",
        visibility=ArtifactVisibility.INTERNAL,
        retention=ArtifactRetention.TEMPORARY,
        created_at=now,
    )

    assert artifact.storage_key.startswith("runs/")
