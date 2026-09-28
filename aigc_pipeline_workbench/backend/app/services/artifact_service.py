import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Optional

from app.domain.enums import ArtifactRetention, ArtifactType, ArtifactVisibility
from app.domain.models import Artifact
from app.repositories.artifact_repository import ArtifactRepository
from app.storage.artifact_store import ArtifactStore


class ArtifactService:
    def __init__(self, repository: ArtifactRepository, store: ArtifactStore):
        self.repository = repository
        self.store = store

    def upload(
        self,
        content: IO[bytes],
        artifact_type: ArtifactType,
        filename: str,
        mime_type: Optional[str],
        metadata: Optional[dict] = None,
        run_id: Optional[str] = None,
        job_id: Optional[str] = None,
        retention: ArtifactRetention = ArtifactRetention.TEMPORARY,
    ) -> Artifact:
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            safe_name = "upload.bin"
        artifact_id = f"artifact_{uuid.uuid4().hex}"
        storage_key = f"artifacts/{artifact_id}/{safe_name}"
        size = self.store.save(storage_key, content, mime_type)
        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            job_id=job_id,
            type=artifact_type,
            name=safe_name,
            mime_type=mime_type,
            size_bytes=size,
            uri=f"/api/v1/artifacts/{artifact_id}/file",
            storage_key=storage_key,
            visibility=ArtifactVisibility.INTERNAL,
            retention=retention,
            created_at=now,
            metadata=metadata or {},
        )
        try:
            return self.repository.create(artifact)
        except Exception:
            self.store.delete(storage_key)
            raise
