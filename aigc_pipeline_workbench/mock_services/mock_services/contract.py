"""Small reusable subset of GPU Service Contract v1."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ArtifactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    type: str
    name: Optional[str] = None
    url: HttpUrl


class ArtifactStoreInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    create_artifact_url: Optional[HttpUrl] = None


class JobSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    job_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    inputs: list[ArtifactInput] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    artifact_store: Optional[ArtifactStoreInfo] = None


class JobLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    level: str
    message: str
    created_at: datetime


class OutputArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    type: str
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
