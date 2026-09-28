import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.public_api import job_manager_from_request, service_registry_from_request
from app.domain.enums import ArtifactType, JobStatus, ServiceStatus
from app.services.job_manager import can_transition
from app.services.service_registry import ServiceRegistry
from app.services.job_manager import JobManager


@pytest.fixture
def phase5_app(test_app):
    from app.services.gpu_service_client import GpuServiceClient
    from app.repositories.job_log_repository import JobLogRepository
    from app.repositories.job_repository import JobRepository
    from app.repositories.service_repository import ServiceRepository
    from app.services.job_manager import JobManager
    from app.services.service_registry import ServiceRegistry

    database = test_app.state.database
    service_repository = ServiceRepository(database)
    client = GpuServiceClient()
    registry = ServiceRegistry(service_repository, client)
    manager = JobManager(
        JobRepository(database),
        JobLogRepository(database),
        service_repository,
        client,
    )
    test_app.state.service_registry = registry
    test_app.state.job_manager = manager
    test_app.dependency_overrides[service_registry_from_request] = lambda: registry
    test_app.dependency_overrides[job_manager_from_request] = lambda: manager
    yield test_app
    test_app.dependency_overrides = {}


def online_service(phase5_app, base_url="http://gpu.test"):
    registry: ServiceRegistry = phase5_app.state.service_registry
    service = registry.register("Mock", base_url)
    service.status = ServiceStatus.ONLINE
    return registry.repository.update(service)


def test_terminal_states_are_protected():
    assert can_transition(JobStatus.RUNNING, JobStatus.SUCCEEDED)
    assert not can_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.FAILED, JobStatus.SUCCEEDED)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.SUCCEEDED)


def test_disabled_service_rejects_new_jobs(phase5_app):
    registry: ServiceRegistry = phase5_app.state.service_registry
    manager: JobManager = phase5_app.state.job_manager
    service = online_service(phase5_app)
    service.enabled = False
    registry.repository.update(service)
    with pytest.raises(Exception, match="service is disabled"):
        asyncio.run(manager.create_job(service.service_id, {}))


def test_cancel_race_with_remote_success(phase5_app):
    manager: JobManager = phase5_app.state.job_manager
    service = online_service(phase5_app)
    job = asyncio.run(manager.create_job(service.service_id, {}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": job.job_id, "status": "running"})
    asyncio.run(manager.submit(job.job_id))
    manager.client.cancel_job = AsyncMock(side_effect=RuntimeError("remote already finished"))
    cancelling = asyncio.run(manager.cancel(job.job_id))
    assert cancelling.status == JobStatus.CANCELLING
    manager.client.job_status = AsyncMock(return_value={
        "job_id": job.job_id,
        "status": "succeeded",
        "progress": {"percent": 100},
        "logs": [],
        "output_artifacts": [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": "2026-09-11T00:00:00Z",
    })
    final = asyncio.run(manager.sync(job.job_id))
    assert final.status == JobStatus.SUCCEEDED


def test_repeated_polling_does_not_duplicate_logs(phase5_app):
    manager: JobManager = phase5_app.state.job_manager
    service = online_service(phase5_app)
    job = asyncio.run(manager.create_job(service.service_id, {}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": job.job_id, "status": "queued"})
    asyncio.run(manager.submit(job.job_id))
    remote = {
        "job_id": job.job_id,
        "status": "running",
        "progress": {"percent": 50},
        "logs": [{"seq": 0, "level": "info", "message": "running", "created_at": "2026-09-11T00:00:00Z"}],
        "output_artifacts": [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": "2026-09-11T00:00:00Z",
    }
    manager.client.job_status = AsyncMock(return_value=remote)
    first = asyncio.run(manager.sync(job.job_id))
    second = asyncio.run(manager.sync(job.job_id))
    assert first.status == JobStatus.RUNNING
    assert second.status == JobStatus.RUNNING
    logs = manager.job_log_repository.list(job.job_id)
    assert len(logs) == 1


def test_remote_failure_is_recorded(phase5_app):
    manager: JobManager = phase5_app.state.job_manager
    service = online_service(phase5_app)
    job = asyncio.run(manager.create_job(service.service_id, {}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": job.job_id, "status": "queued"})
    asyncio.run(manager.submit(job.job_id))
    manager.client.job_status = AsyncMock(return_value={
        "job_id": job.job_id,
        "status": "failed",
        "progress": {"percent": 40},
        "logs": [{"seq": 0, "level": "error", "message": "GPU OOM", "created_at": "2026-09-11T00:00:00Z"}],
        "output_artifacts": [],
        "error": {"code": "INTERNAL_ERROR", "message": "GPU OOM", "details": {}},
        "started_at": None,
        "finished_at": None,
        "updated_at": "2026-09-11T00:00:00Z",
    })
    failed = asyncio.run(manager.sync(job.job_id))
    assert failed.status == JobStatus.FAILED
    assert failed.error.message == "GPU OOM"


def test_public_artifact_metadata_has_no_internal_paths(test_app):
    client = TestClient(test_app)
    upload = client.post(
        "/api/v1/artifacts",
        files={"file": ("input.png", b"boundary-bytes", "image/png")},
        data={"artifact_type": ArtifactType.IMAGE.value},
    )
    body = upload.json()
    artifact_id = body["artifact_id"]
    metadata = client.get(f"/api/v1/artifacts/{artifact_id}")
    file_response = client.get(f"/api/v1/artifacts/{artifact_id}/file")
    text = metadata.text + file_response.text
    assert body["uri"] == f"/api/v1/artifacts/{artifact_id}/file"
    assert "storage_key" not in metadata.text
    assert str(test_app.state.artifact_store.root) not in text
    assert file_response.content == b"boundary-bytes"


def test_restart_recovery_preserves_job_and_logs(phase5_app):
    manager: JobManager = phase5_app.state.job_manager
    service = online_service(phase5_app)
    original = asyncio.run(manager.create_job(service.service_id, {"message": "recover"}))
    manager.client.submit_job = AsyncMock(return_value={"job_id": original.job_id, "status": "queued"})
    asyncio.run(manager.submit(original.job_id))
    manager.client.job_status = AsyncMock(return_value={
        "job_id": original.job_id,
        "status": "running",
        "progress": {"percent": 25},
        "logs": [{"seq": 0, "level": "info", "message": "before restart", "created_at": "2026-09-11T00:00:00Z"}],
        "output_artifacts": [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": "2026-09-11T00:00:00Z",
    })
    asyncio.run(manager.recover())
    manager.client.job_status = AsyncMock(return_value={
        "job_id": original.job_id,
        "status": "succeeded",
        "progress": {"percent": 100},
        "logs": [{"seq": 1, "level": "info", "message": "after restart", "created_at": "2026-09-11T00:00:01Z"}],
        "output_artifacts": [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": "2026-09-11T00:00:00Z",
    })
    asyncio.run(manager.recover())
    recovered = manager.job_repository.get(original.job_id)
    logs = manager.job_log_repository.list(original.job_id)
    assert recovered.status == JobStatus.SUCCEEDED
    assert [entry.seq for entry in logs] == [0, 1]
    assert logs[0].message == "before restart"
