from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.domain.enums import ArtifactType, ErrorCode
from app.domain.models import JobError

CONTRACT_VERSION = "v1"
ContractVersion = Literal["v1"]


class ErrorDetail(JobError):
    pass


def error_detail(value: JobError) -> ErrorDetail:
    return ErrorDetail.model_validate(value.model_dump())


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApiSuccessEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = True
    data: dict[str, Any] = Field(default_factory=dict)


class ApiErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[False] = False
    error: ErrorDetail


class ArtifactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    type: ArtifactType
    name: Optional[str] = None
    url: HttpUrl


class ArtifactDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    type: ArtifactType
    name: str = Field(min_length=1)
    uri: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactStoreInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    create_artifact_url: HttpUrl
