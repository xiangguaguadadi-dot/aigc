import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.public_api import job_manager_from_request, service_registry_from_request
from app.db import Database
from app.domain.enums import ArtifactType, JobStatus, ServiceStatus
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.service_repository import ServiceRepository
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.schemas.service import ServiceHealthResponse, ServiceMetadataResponse
from app.services.service_registry import ServiceRegistry
from app.settings import Settings


@pytest.fixture
def phase4_app(test_app, monkeypatch):
    settings = Settings(start_background_polling=False)
    database = test_app.state.database
    service_repository = ServiceRepository(database)
    job_repository = JobRepository(database)
    job_log_repository = JobLogRepository(database)
    client = GpuServiceClient(settings)
    registry = ServiceRegistry(service_repository, client, settings)
    manager = JobManager(job_repository, job_log_repository, service_repository, client, settings)
    test_app.state.settings = settings
    test_app.state.service_registry = registry
    test_app.state.job_manager = manager
    test_app.dependency_overrides[service_registry_from_request] = lambda: registry
    test_app.dependency_overrides[job_manager_from_request] = lambda: manager
    yield test_app


def test_backend_health(phase4_app):
    client = TestClient(phase4_app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "v1"


def test_service_registration_and_check(phase4_app):
    registry: ServiceRegistry = phase4_app.state.service_registry
    health = AsyncMock(return_value={"contract_version": "v1", "status": "online", "service": "mock_fast", "version": "0.1.0"})
    metadata = AsyncMock(return_value={
        "contract_version": "v1",
        "module_key": "mock_fast",
        "name": "Mock Fast GPU Service",
        "version": "0.1.0",
        "input_artifact_types": ["image", "mask"],
        "output_artifact_types": ["report"],
        "parameter_schema": [],
        "supports_cancel": True,
        "supports_progress": True,
        "max_concurrent_jobs": 1,
    })
    registry.client.health = health
    registry.client.metadata = metadata
    client = TestClient(phase4_app)
    response = client.post(
        "/api/v1/services",
        data={"name": "Mock Fast", "base_url": "http://127.0.0.1:8101", "instance_label": "local"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "online"
    assert body["module_key"] == "mock_fast"
    assert body["instance_label"] == "local"


def test_service_registration_allows_offline_service(phase4_app):
    registry: ServiceRegistry = phase4_app.state.service_registry
    registry.client.health = AsyncMock(side_effect=RuntimeError("connection refused"))
    registry.client.metadata = AsyncMock(side_effect=RuntimeError("connection refused"))
    client = TestClient(phase4_app)
    response = client.post(
        "/api/v1/services",
        data={"name": "Cloud GPU", "base_url": "https://gpu.example.com"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "offline"


def test_service_registration_rejects_invalid_scheme(phase4_app):
    client = TestClient(phase4_app)
    response = client.post(
        "/api/v1/services",
        data={"name": "Bad", "base_url": "file:///tmp"},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_job_lifecycle_with_mock_gpu(phase4_app, monkeypatch):
    registry: ServiceRegistry = phase4_app.state.service_registry
    manager: JobManager = phase4_app.state.job_manager
    health = AsyncMock(return_value={"contract_version": "v1", "status": "online", "service": "mock_fast", "version": "0.1.0"})
    metadata = AsyncMock(return_value={
        "contract_version": "v1",
        "module_key": "mock_fast",
        "name": "Mock Fast GPU Service",
        "version": "0.1.0",
        "input_artifact_types": ["image", "mask"],
        "output_artifact_types": ["report"],
        "parameter_schema": [],
        "supports_cancel": True,
        "supports_progress": True,
        "max_concurrent_jobs": 1,
    })
    registry.client.health = health
    registry.client.metadata = metadata
    service = registry.register("Mock Fast", "http://127.0.0.1:8101", "local")
    checked = registry.repository.update(registry._sync_metadata(service, ServiceHealthResponse.model_validate(health.return_value), ServiceMetadataResponse.model_validate(metadata.return_value)))
    assert checked.status == ServiceStatus.ONLINE

    manager.client.submit_job = AsyncMock(return_value={"job_id": "job_001", "status": "queued"})
    manager.client.job_status = AsyncMock(side_effect=[
        {
            "job_id": "job_001",
            "status": "running",
            "progress": {"percent": 50, "phase": "inference"},
            "logs": [
                {"seq": 0, "level": "info", "message": "started", "created_at": "2026-09-11T00:00:00Z"},
                {"seq": 1, "level": "info", "message": "running", "created_at": "2026-09-11T00:00:01Z"},
            ],
            "output_artifacts": [],
            "error": None,
            "started_at": "2026-09-11T00:00:01Z",
            "finished_at": None,
            "updated_at": "2026-09-11T00:00:01Z",
        },
        {
            "job_id": "job_001",
            "status": "succeeded",
            "progress": {"percent": 100, "phase": "done"},
            "logs": [{"seq": 2, "level": "info", "message": "done", "created_at": "2026-09-11T00:00:02Z"}],
            "output_artifacts": [
                {
                    "artifact_id": "artifact_report",
                    "type": "report",
                    "name": "report.json",
                    "uri": "/api/v1/artifacts/artifact_report/file",
                    "mime_type": "application/json",
                    "size_bytes": 10,
                    "metadata": {},
                }
            ],
            "error": None,
            "started_at": "2026-09-11T00:00:01Z",
            "finished_at": "2026-09-11T00:00:02Z",
            "updated_at": "2026-09-11T00:00:02Z",
        },
    ])
    job = asyncio.run(manager.create_job(service.service_id, {"message": "hello"}))
    submitted = asyncio.run(manager.submit(job.job_id))
    assert submitted.status == JobStatus.QUEUED
    running = asyncio.run(manager.sync(job.job_id))
    assert running.status == JobStatus.RUNNING
    assert running.progress.percent == 50
    succeeded = asyncio.run(manager.sync(job.job_id))
    assert succeeded.status == JobStatus.SUCCEEDED
    assert succeeded.output_artifacts[0].artifact_id == "artifact_report"
    client = TestClient(phase4_app)
    logs = client.get(f"/api/v1/jobs/{job.job_id}/logs").json()
    assert [entry["seq"] for entry in logs] == [0, 1, 2]
    assert logs[0]["source"] == "service"


def test_job_polling_failure_is_not_terminal(phase4_app):
    registry: ServiceRegistry = phase4_app.state.service_registry
    manager: JobManager = phase4_app.state.job_manager
    service = registry.register("Mock", "http://127.0.0.1:8101")
    service.status = ServiceStatus.ONLINE
    registry.repository.update(service)
    job = asyncio.run(manager.create_job(service.service_id, {}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": job.job_id, "status": "queued"})
    submitted = asyncio.run(manager.submit(job.job_id))
    assert submitted.status == JobStatus.QUEUED
    manager.client.job_status = AsyncMock(side_effect=RuntimeError("network failed"))
    synced = asyncio.run(manager.sync(job.job_id))
    assert synced.status == JobStatus.QUEUED
    assert synced.consecutive_poll_failures == 1
    assert synced.last_sync_error == "network failed"


def test_cancel_and_rerun(phase4_app):
    registry: ServiceRegistry = phase4_app.state.service_registry
    manager: JobManager = phase4_app.state.job_manager
    service = registry.register("Mock", "http://127.0.0.1:8101")
    service.status = ServiceStatus.ONLINE
    registry.repository.update(service)
    job = asyncio.run(manager.create_job(service.service_id, {"message": "rerun"}))
    manager.client.submit_job = AsyncMock(side_effect=[
        {"job_id": job.job_id, "status": "queued"},
        {"job_id": "job_rerun", "status": "queued"},
    ])
    asyncio.run(manager.submit(job.job_id))
    manager.client.cancel_job = AsyncMock(return_value={"job_id": job.job_id, "status": "cancelling"})
    cancelled = asyncio.run(manager.cancel(job.job_id))
    assert cancelled.status == JobStatus.CANCELLING
    rerun = asyncio.run(manager.rerun(job.job_id))
    assert rerun.job_id != job.job_id
    assert rerun.rerun_of_job_id == job.job_id
    assert rerun.parameters == job.parameters
    submitted = asyncio.run(manager.submit(rerun.job_id))
    assert submitted.status == JobStatus.QUEUED


def test_restart_recovers_active_jobs(phase4_app):
    registry: ServiceRegistry = phase4_app.state.service_registry
    manager: JobManager = phase4_app.state.job_manager
    service = registry.register("Mock", "http://127.0.0.1:8101")
    service.status = ServiceStatus.ONLINE
    registry.repository.update(service)
    job = asyncio.run(manager.create_job(service.service_id, {}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": job.job_id, "status": "queued"})
    asyncio.run(manager.submit(job.job_id))
    manager.client.job_status = AsyncMock(return_value={
        "job_id": job.job_id,
        "status": "succeeded",
        "progress": {"percent": 100},
        "logs": [],
        "output_artifacts": [],
        "error": None,
        "started_at": None,
        "finished_at": "2026-09-11T00:00:02Z",
        "updated_at": "2026-09-11T00:00:02Z",
    })
    asyncio.run(manager.recover())
    assert manager.job_repository.get(job.job_id).status == JobStatus.SUCCEEDED
