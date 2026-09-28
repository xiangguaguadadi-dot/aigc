from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.domain.enums import ServiceStatus
from app.domain.models import GpuInfo, ParameterDefinition
from app.schemas.common import CONTRACT_VERSION, ContractVersion


class ServiceLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    running_jobs: int = Field(ge=0)
    max_concurrent_jobs: Optional[int] = Field(default=None, gt=0)


class ServiceHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: ContractVersion = "v1"
    status: ServiceStatus
    service: str = Field(min_length=1)
    version: str = Field(min_length=1)
    gpu: Optional[GpuInfo] = None
    load: Optional[ServiceLoad] = None


class ServiceMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: ContractVersion = "v1"
    module_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    input_artifact_types: list[str] = Field(min_length=1)
    output_artifact_types: list[str] = Field(min_length=1)
    parameter_schema: list[ParameterDefinition] = Field(default_factory=list)
    supports_cancel: bool = False
    supports_progress: bool = False
    max_concurrent_jobs: Optional[int] = Field(default=None, gt=0)
    estimated_duration_seconds: Optional[int] = Field(default=None, gt=0)
    extension: dict[str, Any] = Field(default_factory=dict)
