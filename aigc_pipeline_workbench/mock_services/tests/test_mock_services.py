from fastapi.testclient import TestClient
import time

import pytest

from mock_services.base import MockGPUService
from mock_services.fast_service import app as fast_app
from mock_services.job_store import StoredJob, utcnow
from mock_services.slow_service import app as slow_app


def test_fast_health_and_metadata():
    client = TestClient(fast_app)
    assert client.get("/v1/health").json()["status"] == "online"
    metadata = client.get("/v1/metadata").json()
    assert metadata["module_key"] == "mock_fast"
    assert metadata["parameter_schema"][0]["key"] == "message"


def test_slow_health_and_metadata():
    client = TestClient(slow_app)
    assert client.get("/v1/health").json()["status"] == "online"
    metadata = client.get("/v1/metadata").json()
    assert metadata["module_key"] == "mock_slow"
    assert metadata["supports_cancel"] is True


def test_fast_job_reaches_failed_without_backend_upload(monkeypatch):
    monkeypatch.setattr(
        fast_app.settings,
        'control_plane_base_url',
        'http://127.0.0.1:1',
    )
    with TestClient(fast_app) as client:
        response = client.post(
            "/v1/jobs",
            json={"contract_version": "v1", "job_id": "job_fast_001", "module_key": "mock_fast", "parameters": {}},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        time.sleep(1)
        status = client.get("/v1/jobs/job_fast_001").json()
        assert status["status"] in {"running", "succeeded"}
        time.sleep(2.5)
        final = client.get("/v1/jobs/job_fast_001").json()
        assert final["status"] == "failed"
        assert final["error"]["code"] == "INTERNAL_ERROR"


def test_slow_cancel_reaches_cancelled():
    with TestClient(slow_app) as client:
        response = client.post(
            "/v1/jobs",
            json={"contract_version": "v1", "job_id": "job_slow_001", "module_key": "mock_slow", "parameters": {"duration_seconds": 2}},
        )
        assert response.status_code == 200
        time.sleep(0.1)
        cancel = client.post("/v1/jobs/job_slow_001/cancel")
        assert cancel.json()["status"] in {"cancelling", "cancelled"}
        time.sleep(0.3)
        assert client.get("/v1/jobs/job_slow_001").json()["status"] == "cancelled"


def test_job_not_found_returns_unified_error():
    client = TestClient(slow_app)
    response = client.get("/v1/jobs/job_missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_successful_job_artifacts_carry_output_slots(monkeypatch):
    app = MockGPUService(
        module_key="mock_fast",
        service_name="test",
        version="0.1.0",
        parameter_schema=[],
        default_duration=0,
    )

    async def fake_upload_artifact(settings, job_id, content, filename, artifact_type):
        return {
            "artifact_id": f"artifact_{artifact_type}",
            "type": artifact_type,
            "name": filename,
            "uri": "https://example.test/artifact",
            "mime_type": "application/octet-stream",
            "size_bytes": len(content),
        }

    monkeypatch.setattr("mock_services.base.upload_artifact", fake_upload_artifact)
    job = StoredJob(
        job_id="job_slots",
        module_key="mock_fast",
        status="running",
        created_at=utcnow(),
        updated_at=utcnow(),
        parameters={},
    )
    app.store.create(job)
    await app.finish_successfully("job_slots")
    final = app.store.get("job_slots")
    assert final is not None and final.status == "succeeded"
    slots = {
        artifact.type: artifact.metadata.get("output_slot")
        for artifact in final.output_artifacts
    }
    assert slots == {"report": "report", "glb": "mesh"}
