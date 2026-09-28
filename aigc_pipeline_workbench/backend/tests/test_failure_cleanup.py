from io import BytesIO

import pytest

from app.domain.enums import ArtifactType
from app.services.artifact_service import ArtifactService
from tests.test_artifacts import upload_png


def test_database_failure_cleans_saved_file(test_app, monkeypatch):
    service: ArtifactService = test_app.state.artifact_service
    store = test_app.state.artifact_store

    def fail_create(_artifact):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(service.repository, "create", fail_create)
    with pytest.raises(RuntimeError):
        service.upload(
            BytesIO(b"cleanup-bytes"),
            ArtifactType.IMAGE,
            "input.png",
            "image/png",
        )

    assert not any((store.root).glob("**/*.*"))
