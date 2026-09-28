from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import InputSlot, OutputSlot, ParameterDefinition, RuntimeSpec


class ModuleCreateRequest(BaseModel):
    module_key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    description: Optional[str] = None
    version: str = Field(default="1.0", min_length=1)
    input_slots: list[InputSlot] = Field(default_factory=list)
    output_slots: list[OutputSlot] = Field(default_factory=list)
    parameter_schema: list[ParameterDefinition] = Field(default_factory=list)
    runtime_spec: Optional[RuntimeSpec] = None
    status: str = Field(default="draft")


class ModuleUpdateRequest(BaseModel):
    module_key: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    version: Optional[str] = Field(default=None, min_length=1)
    status: Optional[str] = None
    input_slots: Optional[list[InputSlot]] = None
    output_slots: Optional[list[OutputSlot]] = None
    parameter_schema: Optional[list[ParameterDefinition]] = None
    runtime_spec: Optional[RuntimeSpec] = None


class ModuleResponse(BaseModel):
    module_id: str
    module_key: str
    name: str
    description: Optional[str]
    version: str
    status: str
    input_slots: list[InputSlot]
    output_slots: list[OutputSlot]
    parameter_schema: list[ParameterDefinition]
    runtime_spec: Optional[RuntimeSpec] = None
    created_at: datetime
    updated_at: datetime


class ModuleCompatibilityResponse(BaseModel):
    service_id: str
    compatible: bool
    reasons: list[str]
