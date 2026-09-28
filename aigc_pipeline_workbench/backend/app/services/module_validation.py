from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from app.domain.enums import ArtifactType
from app.domain.models import Job, ModuleDefinition, ParameterDefinition, RuntimeSpec
from app.repositories.module_repository import ModuleRepository
from app.schemas.module import ModuleCompatibilityResponse, ModuleCreateRequest, ModuleUpdateRequest
from app.services.service_registry import ServiceRegistry


class ModuleValidation:
    @staticmethod
    def validate_and_build(payload, *, module_id, created_at, updated_at, existing=None):
        if existing is not None:
            raise HTTPException(status_code=409, detail="module_key already exists")
        ModuleValidation._validate_names(
            [slot.name for slot in payload.input_slots],
            [slot.name for slot in payload.output_slots],
            [item.key for item in payload.parameter_schema],
        )
        ModuleValidation._validate_mime_and_extensions(payload.input_slots, payload.output_slots)
        ModuleValidation._validate_parameters(payload.parameter_schema)
        status = payload.status if payload.status is not None else "draft"
        if status == "ready":
            ModuleValidation._validate_ready(payload.input_slots, payload.output_slots, payload.parameter_schema)
        return ModuleDefinition(
            module_id=module_id,
            module_key=payload.module_key,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            status=status,
            input_slots=payload.input_slots,
            output_slots=payload.output_slots,
            parameter_schema=payload.parameter_schema,
            runtime_spec=payload.runtime_spec,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def validate_and_update(existing, payload, now, repository: ModuleRepository):
        module_key = payload.module_key if payload.module_key is not None else existing.module_key
        if module_key != existing.module_key:
            conflict = repository.get_by_key(module_key)
            if conflict is not None:
                raise HTTPException(status_code=409, detail="module_key already exists")
        input_slots = payload.input_slots if payload.input_slots is not None else existing.input_slots
        output_slots = payload.output_slots if payload.output_slots is not None else existing.output_slots
        parameter_schema = payload.parameter_schema if payload.parameter_schema is not None else existing.parameter_schema
        status = payload.status if payload.status is not None else existing.status
        ModuleValidation._validate_names(
            [slot.name for slot in input_slots],
            [slot.name for slot in output_slots],
            [item.key for item in parameter_schema],
        )
        ModuleValidation._validate_mime_and_extensions(input_slots, output_slots)
        ModuleValidation._validate_parameters(parameter_schema)
        if status == "ready":
            ModuleValidation._validate_ready(input_slots, output_slots, parameter_schema)
        ModuleValidation._validate_status(status)
        return existing.model_copy(update={
            "module_key": module_key,
            "name": payload.name if payload.name is not None else existing.name,
            "description": payload.description,
            "version": payload.version if payload.version is not None else existing.version,
            "status": status,
            "input_slots": input_slots,
            "output_slots": output_slots,
            "parameter_schema": parameter_schema,
            "runtime_spec": payload.runtime_spec if payload.runtime_spec is not None else existing.runtime_spec,
            "updated_at": now,
        })

    @staticmethod
    def compatibility_list(module: ModuleDefinition, services):
        return [
            ModuleCompatibilityResponse(
                service_id=service.service_id,
                compatible=ModuleValidation.is_service_compatible(module, service)[0],
                reasons=ModuleValidation.is_service_compatible(module, service)[1],
            )
            for service in services
        ]

    @staticmethod
    def is_service_compatible(module: ModuleDefinition, service) -> tuple[bool, list[str]]:
        reasons = []
        if module.module_key != service.module_key:
            reasons.append("module_key mismatch")
        input_types = {slot.artifact_type for slot in module.input_slots}
        service_inputs = set(service.capabilities.input_artifact_types)
        if not input_types.issubset(service_inputs):
            reasons.append("input artifact types are not compatible")
        output_types = {slot.artifact_type for slot in module.output_slots if slot.required}
        service_outputs = set(service.capabilities.output_artifact_types)
        if not output_types.issubset(service_outputs):
            reasons.append("required output artifact types are not compatible")
        return not reasons, reasons

    @staticmethod
    def validate_job_inputs(module: ModuleDefinition, inputs, parameters):
        supplied = {input.type for input in inputs}
        for slot in module.input_slots:
            if slot.required and slot.artifact_type not in supplied:
                raise HTTPException(status_code=422, detail=f"missing required input slot: {slot.name}")

    @staticmethod
    def _validate_names(input_names, output_names, parameter_names):
        if len(input_names) != len(set(input_names)):
            raise HTTPException(status_code=422, detail="input slot names must be unique")
        if len(output_names) != len(set(output_names)):
            raise HTTPException(status_code=422, detail="output slot names must be unique")
        if len(parameter_names) != len(set(parameter_names)):
            raise HTTPException(status_code=422, detail="parameter names must be unique")

    @staticmethod
    def _validate_mime_and_extensions(input_slots, output_slots):
        for slot in list(input_slots) + list(output_slots):
            for mime in (getattr(slot, "accepted_mime_types", []) or getattr(slot, "expected_mime_types", [])):
                if "/" not in mime:
                    raise HTTPException(status_code=422, detail=f"invalid MIME type: {mime}")
            extensions = getattr(slot, "accepted_extensions", []) or getattr(slot, "expected_extensions", [])
            for extension in extensions:
                if not extension.startswith("."):
                    raise HTTPException(status_code=422, detail=f"invalid extension: {extension}")

    @staticmethod
    def _validate_parameters(parameters):
        for parameter in parameters:
            if parameter.value_type == "enum" and parameter.options:
                choices = {option.value for option in parameter.options}
                if parameter.default is not None and parameter.default not in choices:
                    raise HTTPException(status_code=422, detail=f"enum default is invalid: {parameter.key}")

    @staticmethod
    def _validate_ready(input_slots, output_slots, parameter_schema):
        if not input_slots or not output_slots:
            raise HTTPException(status_code=422, detail="ready module requires at least one input and output slot")

    @staticmethod
    def _validate_status(status):
        if status not in {"draft", "ready"}:
            raise HTTPException(status_code=422, detail="module status must be draft or ready")
