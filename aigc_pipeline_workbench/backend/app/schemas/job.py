from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobStatus
from app.domain.models import JobError, JobProgress
from app.schemas.common import (
    ArtifactDescriptor,
    ArtifactInput,
    ArtifactStoreInfo,
    ContractVersion,
)


class JobSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: ContractVersion
    job_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    inputs: list[ArtifactInput] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    artifact_store: Optional[ArtifactStoreInfo] = None


class JobSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: JobStatus


class JobLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    level: str = Field(min_length=1)
    message: str
    created_at: datetime


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: JobStatus
    progress: Optional[JobProgress] = None
    logs: list[JobLogEntry] = Field(default_factory=list)
    output_artifacts: list[ArtifactDescriptor] = Field(default_factory=list)
    error: Optional[JobError] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime


class JobCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: JobStatus
