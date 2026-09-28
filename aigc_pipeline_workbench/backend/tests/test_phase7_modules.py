import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.public_api import (
    job_manager_from_request,
    module_repository_from_request,
    service_registry_from_request,
)
from app.domain.enums import ArtifactType, ServiceStatus
from app.domain.models import InputSlot, ModuleDefinition, OutputSlot, ParameterDefinition
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.module_repository import ModuleRepository
from app.repositories.service_repository import ServiceRepository
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.services.service_registry import ServiceRegistry
from app.settings import Settings


def phase7_app(test_app):
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


def test_module_crud_and_persistence(test_app):
    app = phase7_app(test_app)
    client = TestClient(app)
    payload = {
        "module_key": "physics_asset_generator",
        "name": "Physics Asset Generator",
        "description": "Generates physics assets",
        "version": "1.2",
        "input_slots": [{"name": "mesh", "artifact_type": "glb", "required": True}],
        "output_slots": [{"name": "physics", "artifact_type": "physics_asset", "required": True}],
        "parameter_schema": [{
            "key": "mass",
            "label": "Mass",
            "value_type": "number",
            "required": True,
            "default": 1.0,
            "description": "Object mass",
        }],
    }

    created = client.post("/api/v1/modules", json=payload)
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "draft"
    module_id = body["module_id"]

    listed = client.get("/api/v1/modules", params={"module_key": "physics_asset_generator"})
    assert [item["module_id"] for item in listed.json()] == [module_id]
    fetched = client.get(f"/api/v1/modules/{module_id}")
    assert fetched.status_code == 200
    assert fetched.json()["parameter_schema"][0]["default"] == 1.0

    updated = client.patch(f"/api/v1/modules/{module_id}", json={"status": "ready"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "ready"

    persisted = app.state.module_repository.get(module_id)
    assert persisted is not None
    assert persisted.status == "ready"
    assert persisted.input_slots[0].artifact_type == ArtifactType.GLB


def test_module_validation_rejects_invalid_definitions(test_app):
    app = phase7_app(test_app)
    client = TestClient(app)
    app.state.module_repository.create(ModuleDefinition(
        module_id="module_existing",
        module_key="image_to_3d",
        name="Existing Module",
        version="1.0",
        status="ready",
        input_slots=[InputSlot(name="image", artifact_type=ArtifactType.IMAGE, required=True)],
        output_slots=[OutputSlot(name="mesh", artifact_type=ArtifactType.GLB, required=True)],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    duplicate_input = {
        "module_key": "duplicate_inputs",
        "name": "Duplicate Inputs",
        "input_slots": [
            {"name": "image", "artifact_type": "image", "required": True},
            {"name": "image", "artifact_type": "image", "required": False},
        ],
    }
    assert client.post("/api/v1/modules", json=duplicate_input).status_code == 422

    duplicate_key = {
        "module_key": "image_to_3d",
        "name": "Duplicate Module",
        "input_slots": [{"name": "image", "artifact_type": "image", "required": True}],
    }
    assert client.post("/api/v1/modules", json=duplicate_key).status_code == 409

    invalid_ready = {
        "module_key": "invalid_ready",
        "name": "Invalid Ready",
        "input_slots": [{"name": "image", "artifact_type": "image", "required": True}],
        "output_slots": [],
        "status": "ready",
    }
    assert client.post("/api/v1/modules", json=invalid_ready).status_code == 422


def test_module_service_compatibility_and_mismatch(test_app):
    app = phase7_app(test_app)
    client = TestClient(app)
    created = client.post("/api/v1/modules", json={
        "module_key": "image_to_3d",
        "name": "Compatible Image Module",
        "input_slots": [{"name": "image", "artifact_type": "image", "required": True}],
        "output_slots": [{"name": "mesh", "artifact_type": "glb", "required": True}],
    })
    module_id = created.json()["module_id"]
    repository = app.state.module_repository
    module = repository.get(module_id)

    from app.domain.models import AlgorithmService, ServiceCapabilities
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    matching = AlgorithmService(
        service_id="service_match", module_key="image_to_3d", name="Match",
        base_url="http://gpu-a.test", status=ServiceStatus.ONLINE, version="1.0",
        capabilities=ServiceCapabilities(input_artifact_types=[ArtifactType.IMAGE], output_artifact_types=[ArtifactType.GLB]),
        registered_at=now, updated_at=now,
    )
    mismatched = AlgorithmService(
        service_id="service_mismatch", module_key="image_to_3d", name="Mismatch",
        base_url="http://gpu-b.test", status=ServiceStatus.ONLINE, version="1.0",
        capabilities=ServiceCapabilities(input_artifact_types=[ArtifactType.IMAGE], output_artifact_types=[ArtifactType.IMAGE]),
        registered_at=now, updated_at=now,
    )
    app.state.service_registry.repository.create(matching)
    app.state.service_registry.repository.create(mismatched)

    response = client.get(f"/api/v1/modules/{module_id}/services")
    assert response.status_code == 200
    services = {item["service_id"]: item for item in response.json()}
    assert services["service_match"]["compatible"] is True
    assert services["service_mismatch"]["compatible"] is False
    assert "required output artifact types are not compatible" in services["service_mismatch"]["reasons"]

    mismatch_module = client.post("/api/v1/modules", json={
        "module_key": "mesh_to_mesh",
        "name": "Mesh To Mesh",
        "input_slots": [{"name": "mesh", "artifact_type": "glb", "required": True}],
        "output_slots": [{"name": "mesh", "artifact_type": "glb", "required": True}],
    }).json()
    mismatch_response = client.get(f"/api/v1/modules/{mismatch_module['module_id']}/services")
    assert all(not item["compatible"] for item in mismatch_response.json())


def test_module_job_creation_and_filters(test_app):
    app = phase7_app(test_app)
    client = TestClient(app)
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc)
    definition = app.state.module_repository.create(
        ModuleDefinition(
            module_id="module_job_test",
            module_key="multi_input_test",
            name="Multi Input Job Test",
            version="1.0",
            status="ready",
            input_slots=[
                InputSlot(name="image", artifact_type=ArtifactType.IMAGE, required=True),
                InputSlot(name="reference", artifact_type=ArtifactType.IMAGE, required=False),
            ],
            output_slots=[OutputSlot(name="report", artifact_type=ArtifactType.REPORT, required=True)],
            parameter_schema=[ParameterDefinition(key="strength", label="Strength", value_type="number", default=1.0)],
            created_at=timestamp,
            updated_at=timestamp,
        )
    )

    uploaded = client.post(
        "/api/v1/artifacts",
        files={"file": ("image.png", b"png", "image/png")},
        data={"artifact_type": "image"},
    ).json()

    service = app.state.service_registry.register("Offline Service", "http://offline.test")
    offline_response = client.post(
        "/api/v1/jobs",
        data={
            "service_id": service.service_id,
            "module_id": definition.module_id,
            "input_artifacts": f'[{{"artifact_id":"{uploaded["artifact_id"]}","type":"image","uri":"{uploaded["uri"]}"}}]',
            "parameters": "{}",
        },
    )
    assert offline_response.status_code == 409

    missing_required = client.post(
        "/api/v1/jobs",
        data={"service_id": service.service_id, "module_id": definition.module_id},
    )
    assert missing_required.status_code == 422
    assert "missing required input slot: image" in missing_required.json()["detail"]

    service.status = ServiceStatus.ONLINE
    app.state.service_registry.repository.update(service)
    legacy_job = asyncio.run(app.state.job_manager.create_job(service.service_id, {}, module_id=None))
    assert legacy_job.module_id is None
    listed = app.state.job_manager.job_repository.list(module_id=definition.module_id)
    assert listed == []
