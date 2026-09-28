from pathlib import Path

import pytest

from app.db import Database
from app.main import app
from app.repositories.artifact_repository import ArtifactRepository
from app.services.artifact_service import ArtifactService
from app.api.public_api import artifact_repository_from_request, artifact_service_from_request
from app.storage.local_artifact_store import LocalArtifactStore


@pytest.fixture
def test_app(tmp_path: Path):
    database = Database(tmp_path / "workbench.sqlite3")
    database.initialize()
    store = LocalArtifactStore(tmp_path / "artifacts")
    repository = ArtifactRepository(database)
    service = ArtifactService(repository, store)

    app.dependency_overrides = {}
    app.state.database = database
    app.state.artifact_store = store
    app.state.artifact_repository = repository
    app.state.artifact_service = service
    app.dependency_overrides[artifact_repository_from_request] = lambda: repository
    app.dependency_overrides[artifact_service_from_request] = lambda: service
    yield app
    app.dependency_overrides = {}
