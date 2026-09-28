from datetime import datetime
from typing import Any, Any, Optional

from pydantic import BaseModel, Field, HttpUrl

from app.domain.enums import (
    ArtifactRetention,
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


class ParameterOption(BaseModel):
    value: str
    label: str


class RuntimeSpec(BaseModel):
    """Describes runtime requirements for a module."""
    runtime_type: str = "cpu"
    gpu_mode: str | None = None
    min_vram_gb: float | None = None
    model_residency: str = "on_demand"
    max_concurrency: int = 1
    description: str | None = None


class ParameterDefinition(BaseModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_type: ParameterValueType
    required: bool = False
    default: Optional[Any] = None
    minimum: Optional[float] = Field(default=None, gt=None)
    maximum: Optional[float] = Field(default=None, gt=None)
    options: list[ParameterOption] = Field(default_factory=list)
    description: Optional[str] = None


class InputSlot(BaseModel):
    name: str = Field(min_length=1)
    artifact_type: ArtifactType
    required: bool = True
    accepted_mime_types: list[str] = Field(default_factory=list)
    accepted_extensions: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class OutputSlot(BaseModel):
    name: str = Field(min_length=1)
    artifact_type: ArtifactType
    required: bool = True
    expected_mime_types: list[str] = Field(default_factory=list)
    expected_extensions: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class ModuleDefinition(BaseModel):
    module_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    version: str = Field(default="1.0")
    status: str
    input_slots: list[InputSlot] = Field(default_factory=list)
    output_slots: list[OutputSlot] = Field(default_factory=list)
    parameter_schema: list[ParameterDefinition] = Field(default_factory=list)
    runtime_spec: Optional[RuntimeSpec] = None
    created_at: datetime
    updated_at: datetime


class ServiceCapabilities(BaseModel):
    input_artifact_types: list[ArtifactType]
    output_artifact_types: list[ArtifactType]
    parameter_schema: list[ParameterDefinition] = Field(default_factory=list)
    supports_cancel: bool = False
    supports_progress: bool = False
    supports_streaming_logs: bool = False
    estimated_duration_seconds: Optional[int] = Field(default=None, gt=0)
    max_concurrent_jobs: Optional[int] = Field(default=None, gt=0)


class GpuInfo(BaseModel):
    name: Optional[str] = None
    vram_bytes: Optional[int] = Field(default=None, gt=0)
    cuda_version: Optional[str] = None
    driver_version: Optional[str] = None


class AlgorithmService(BaseModel):
    service_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    base_url: HttpUrl
    instance_label: Optional[str] = None
    enabled: bool = True
    status: ServiceStatus
    version: str = Field(min_length=1)
    gpu: Optional[GpuInfo] = None
    capabilities: ServiceCapabilities
    registered_at: datetime
    updated_at: datetime
    last_checked_at: Optional[datetime] = None
    last_online_at: Optional[datetime] = None
    last_error: Optional[str] = None


class ArtifactRef(BaseModel):
    artifact_id: str = Field(min_length=1)
    type: ArtifactType
    name: Optional[str] = None
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Artifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    type: ArtifactType
    name: str = Field(min_length=1)
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    uri: str
    storage_key: Optional[str] = None
    visibility: ArtifactVisibility
    retention: ArtifactRetention
    created_at: datetime
    expires_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobError(BaseModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class JobProgress(BaseModel):
    percent: Optional[int] = Field(default=None, ge=0, le=100)
    phase: Optional[str] = None
    message: Optional[str] = None


class Job(BaseModel):
    job_id: str = Field(min_length=1)
    run_id: Optional[str] = None
    service_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    module_id: Optional[str] = None
    status: JobStatus
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    output_artifacts: list[ArtifactRef] = Field(default_factory=list)
    progress: Optional[JobProgress] = None
    error: Optional[JobError] = None
    created_at: datetime
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime
    rerun_of_job_id: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_sync_error: Optional[str] = None
    consecutive_poll_failures: int = Field(default=0, ge=0)


class JobLog(BaseModel):
    log_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    service_id: Optional[str] = None
    seq: int = Field(ge=0)
    source: LogSource
    level: LogLevel
    message: str
    created_at: datetime
