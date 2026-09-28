from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ArtifactType


class ArtifactUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    type: ArtifactType
    name: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    uri: str


class ArtifactMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    type: ArtifactType
    name: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
