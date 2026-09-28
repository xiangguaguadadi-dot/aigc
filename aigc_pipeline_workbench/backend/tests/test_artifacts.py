import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.enums import ArtifactType, ErrorCode
from app.errors import ArtifactNotFoundError
from app.storage.local_artifact_store import LocalArtifactStore


def upload_png(client: TestClient, name: str = "test image.png"):
    response = client.post(
        "/api/v1/artifacts",
        files={"file": (name, b"fake-png-bytes", "image/png")},
        data={"artifact_type": ArtifactType.IMAGE.value, "metadata": json.dumps({"source": "test"})},
    )
    assert response.status_code == 200
    return response.json()


def test_upload_artifact_success(test_app):
    client = TestClient(test_app)
    response = client.post(
        "/api/v1/artifacts",
        files={"file": ("input.png", b"image-bytes", "image/png")},
        data={"artifact_type": ArtifactType.IMAGE.value},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"].startswith("artifact_")
    assert body["name"] == "input.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(b"image-bytes")
    assert body["uri"] == f"/api/v1/artifacts/{body['artifact_id']}/file"


def test_metadata_is_written_to_sqlite(test_app):
    client = TestClient(test_app)
    uploaded = upload_png(client)
    artifact = test_app.state.artifact_repository.get(uploaded["artifact_id"])

    assert artifact.type == ArtifactType.IMAGE
    assert artifact.storage_key is not None
    assert artifact.metadata == {"source": "test"}


def test_file_is_saved_in_local_store(test_app, tmp_path: Path):
    client = TestClient(test_app)
    uploaded = upload_png(client)
    artifact = test_app.state.artifact_repository.get(uploaded["artifact_id"])
    path = test_app.state.artifact_store.root / artifact.storage_key

    assert path.is_file()
    assert path.read_bytes() == b"fake-png-bytes"


def test_get_metadata(test_app):
    client = TestClient(test_app)
    uploaded = upload_png(client)
    response = client.get(f"/api/v1/artifacts/{uploaded['artifact_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == uploaded["artifact_id"]
    assert body["metadata"] == {"source": "test"}


def test_get_file_returns_original_bytes(test_app):
    client = TestClient(test_app)
    uploaded = upload_png(client)
    response = client.get(f"/api/v1/artifacts/{uploaded['artifact_id']}/file")

    assert response.status_code == 200
    assert response.content == b"fake-png-bytes"


def test_missing_artifact_returns_unified_error(test_app):
    client = TestClient(test_app)
    response = client.get("/api/v1/artifacts/artifact_missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == ErrorCode.JOB_NOT_FOUND
    assert body["error"]["details"] == {"artifact_id": "artifact_missing"}


def test_public_metadata_does_not_expose_storage_key_or_real_path(test_app):
    client = TestClient(test_app)
    uploaded = upload_png(client)
    response = client.get(f"/api/v1/artifacts/{uploaded['artifact_id']}")

    assert "storage_key" not in response.json()
    assert str(test_app.state.artifact_store.root) not in response.text


def test_local_store_rejects_path_traversal(tmp_path: Path):
    store = LocalArtifactStore(tmp_path / "artifacts")

    assert store.exists("../outside.png") is False
    try:
        store.save("../outside.png", BytesIO(b"bad"))
    except Exception as exc:
        assert "invalid storage key" in str(exc)
    else:
        raise AssertionError("path traversal was allowed")
