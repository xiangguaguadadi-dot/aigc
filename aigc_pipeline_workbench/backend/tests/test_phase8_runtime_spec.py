"""Phase 8 tests: RuntimeSpec seeding, persistence, and TRELLIS service registration."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.public_api import (
    job_manager_from_request,
    module_repository_from_request,
    service_registry_from_request,
)
from app.db import Database
from app.domain.models import (
    AlgorithmService,
    InputSlot,
    ModuleDefinition,
    OutputSlot,
    ParameterDefinition,
    RuntimeSpec,
    ServiceCapabilities,
)
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.module_repository import ModuleRepository
from app.repositories.service_repository import ServiceRepository
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.services.service_registry import ServiceRegistry
from app.settings import Settings
from app.domain.enums import ArtifactType, ParameterValueType, ServiceStatus
from pydantic import HttpUrl


@pytest.fixture
def phase8_app(test_app):
    settings = Settings(start_background_polling=False)
    database = test_app.state.database
    repository = ModuleRepository(database)
    service_repository = ServiceRepository(database)
    client = GpuServiceClient(settings)
    registry = ServiceRegistry(service_repository, client, settings)
    manager = JobManager(
        JobRepository(database),
        JobLogRepository(database),
        service_repository,
        client,
        settings,
    )
    test_app.state.settings = settings
    test_app.state.module_repository = repository
    test_app.state.service_registry = registry
    test_app.state.job_manager = manager
    test_app.dependency_overrides[module_repository_from_request] = lambda: repository
    test_app.dependency_overrides[service_registry_from_request] = lambda: registry
    test_app.dependency_overrides[job_manager_from_request] = lambda: manager
    return test_app


class TestRuntimeSpec:
    def test_runtime_spec_model_defaults(self):
        """Default RuntimeSpec should be CPU on-demand."""
        spec = RuntimeSpec()
        assert spec.runtime_type == "cpu"
        assert spec.gpu_mode is None
        assert spec.min_vram_gb is None
        assert spec.model_residency == "on_demand"
        assert spec.max_concurrency == 1

    def test_trellis_runtime_spec(self):
        """TRELLIS should have a dedicated GPU persistent spec."""
        spec = RuntimeSpec(
            runtime_type="gpu",
            gpu_mode="dedicated",
            min_vram_gb=40.0,
            model_residency="persistent",
            max_concurrency=1,
        )
        assert spec.runtime_type == "gpu"
        assert spec.gpu_mode == "dedicated"
        assert spec.min_vram_gb == 40.0
        assert spec.model_residency == "persistent"

    def test_runtime_spec_serialization_roundtrip(self):
        """RuntimeSpec should survive JSON serialization."""
        spec = RuntimeSpec(
            runtime_type="gpu",
            gpu_mode="dedicated",
            min_vram_gb=40.0,
            model_residency="persistent",
            max_concurrency=1,
        )
        data = json.loads(spec.model_dump_json())
        restored = RuntimeSpec.model_validate(data)
        assert restored.runtime_type == spec.runtime_type
        assert restored.gpu_mode == spec.gpu_mode
        assert restored.min_vram_gb == spec.min_vram_gb

    def test_module_definition_with_runtime_spec(self, test_app):
        """ModuleDefinition should persist and load RuntimeSpec correctly."""
        now = datetime.now(timezone.utc)
        repository = ModuleRepository(test_app.state.database)

        module = ModuleDefinition(
            module_id="test_module_with_spec",
            module_key="test_module_with_spec",
            name="Test Module",
            version="1.0",
            status="ready",
            input_slots=[InputSlot(name="image", artifact_type=ArtifactType.IMAGE, required=True)],
            output_slots=[OutputSlot(name="mesh", artifact_type=ArtifactType.GLB, required=True)],
            parameter_schema=[],
            runtime_spec=RuntimeSpec(
                runtime_type="gpu",
                gpu_mode="dedicated",
                min_vram_gb=40.0,
                model_residency="persistent",
                max_concurrency=1,
            ),
            created_at=now,
            updated_at=now,
        )
        repository.create(module)

        # Read back
        fetched = repository.get("test_module_with_spec")
        assert fetched is not None
        assert fetched.runtime_spec is not None
        assert fetched.runtime_spec.runtime_type == "gpu"
        assert fetched.runtime_spec.gpu_mode == "dedicated"
        assert fetched.runtime_spec.min_vram_gb == 40.0
        assert fetched.runtime_spec.model_residency == "persistent"
        assert fetched.runtime_spec.max_concurrency == 1

    def test_module_without_runtime_spec(self, test_app):
        """Legacy modules without RuntimeSpec should load without error."""
        now = datetime.now(timezone.utc)
        repository = ModuleRepository(test_app.state.database)

        module = ModuleDefinition(
            module_id="legacy_module_no_spec",
            module_key="legacy_no_spec",
            name="Legacy Module",
            version="1.0",
            status="ready",
            input_slots=[],
            output_slots=[],
            parameter_schema=[],
            runtime_spec=None,
            created_at=now,
            updated_at=now,
        )
        repository.create(module)

        fetched = repository.get("legacy_module_no_spec")
        assert fetched is not None
        assert fetched.runtime_spec is None

    def test_runtime_spec_in_api_response(self, test_app):
        """ModuleResponse schema should include runtime_spec."""
        from app.schemas.module import ModuleResponse
        from app.repositories.module_repository import ModuleRepository
        now = datetime.now(timezone.utc)
        repository = ModuleRepository(test_app.state.database)

        module = ModuleDefinition(
            module_id="api_spec_test",
            module_key="api_spec_test",
            name="API Spec Test",
            version="1.0",
            status="ready",
            input_slots=[],
            output_slots=[],
            parameter_schema=[],
            runtime_spec=RuntimeSpec(
                runtime_type="gpu", gpu_mode="dedicated",
                min_vram_gb=40.0, model_residency="persistent",
                max_concurrency=1,
            ),
            created_at=now,
            updated_at=now,
        )
        repository.create(module)

        fetched = repository.get("api_spec_test")
        assert fetched is not None
        response = ModuleResponse.model_validate(fetched.model_dump(mode="json"))
        body = response.model_dump(mode="json")
        assert "runtime_spec" in body
        assert body["runtime_spec"]["runtime_type"] == "gpu"
        assert body["runtime_spec"]["gpu_mode"] == "dedicated"
        assert body["runtime_spec"]["min_vram_gb"] == 40.0
        assert body["runtime_spec"]["model_residency"] == "persistent"
        assert body["runtime_spec"]["max_concurrency"] == 1

