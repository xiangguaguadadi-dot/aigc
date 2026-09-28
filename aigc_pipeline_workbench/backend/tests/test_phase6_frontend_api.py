from fastapi.testclient import TestClient

from app.domain.enums import JobStatus, ServiceStatus

from app.api.public_api import job_manager_from_request, service_registry_from_request
from app.repositories.job_repository import JobRepository
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.services.service_registry import ServiceRegistry


def phase6_app(test_app):
    from app.repositories.job_log_repository import JobLogRepository
    from app.repositories.service_repository import ServiceRepository

    database = test_app.state.database
    registry = ServiceRegistry(ServiceRepository(database), GpuServiceClient())
    manager = JobManager(
        JobRepository(database),
        JobLogRepository(database),
        registry.repository,
        GpuServiceClient(),
    )
    test_app.state.service_registry = registry
    test_app.state.job_manager = manager
    test_app.dependency_overrides[service_registry_from_request] = lambda: registry
    test_app.dependency_overrides[job_manager_from_request] = lambda: manager
    return test_app


def test_job_list_returns_recent_jobs_desc(test_app):
    app = phase6_app(test_app)
    registry = app.state.service_registry
    manager = app.state.job_manager
    service = registry.register("Mock", "http://gpu.test")
    service.status = ServiceStatus.ONLINE
    registry.repository.update(service)
    import asyncio
    jobs = []
    for index in range(3):
        jobs.append(asyncio.run(manager.create_job(service.service_id, {"index": index})))
    client = TestClient(app)
    response = client.get("/api/v1/jobs?limit=2")
    assert response.status_code == 200
    body = response.json()
    assert [item["job_id"] for item in body] == [jobs[2].job_id, jobs[1].job_id]


def test_job_list_filters_by_service_and_status(test_app):
    app = phase6_app(test_app)
    registry = app.state.service_registry
    manager = app.state.job_manager
    service = registry.register("Mock", "http://gpu.test")
    service.status = ServiceStatus.ONLINE
    registry.repository.update(service)
    other = registry.register("Other", "http://other.test", instance_label="other")
    other.status = ServiceStatus.ONLINE
    registry.repository.update(other)
    import asyncio
    selected = asyncio.run(manager.create_job(service.service_id, {}))
    asyncio.run(manager.create_job(other.service_id, {}))
    submitted = manager.job_repository.update(selected.job_id, status=JobStatus.QUEUED)
    client = TestClient(app)
    response = client.get(f"/api/v1/jobs?service_id={service.service_id}&status=queued")
    assert response.status_code == 200
    body = response.json()
    assert [item["job_id"] for item in body] == [submitted.job_id]


def test_job_list_rejects_invalid_status(test_app):
    app = phase6_app(test_app)
    client = TestClient(app)
    response = client.get("/api/v1/jobs?status=not_a_status")
    assert response.status_code == 422
