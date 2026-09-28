from fastapi.testclient import TestClient

from app.domain.enums import ArtifactType


def test_artifact_survives_repository_restart(test_app, tmp_path):
    client = TestClient(test_app)
    response = client.post(
        "/api/v1/artifacts",
        files={"file": ("input.png", b"restart-bytes", "image/png")},
        data={"artifact_type": ArtifactType.IMAGE.value},
    )
    uploaded = response.json()

    from app.db import Database
    from app.repositories.artifact_repository import ArtifactRepository
    from app.storage.local_artifact_store import LocalArtifactStore

    database = Database(tmp_path / "workbench.sqlite3")
    repository = ArtifactRepository(database)
    restarted_artifact = repository.get(uploaded["artifact_id"])
    store = LocalArtifactStore(tmp_path / "artifacts")

    assert restarted_artifact.name == "input.png"
    assert store.exists(restarted_artifact.storage_key)
