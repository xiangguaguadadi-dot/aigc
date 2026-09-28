import json
import sqlite3
from datetime import datetime
from typing import Optional

from app.db import get_connection
from app.domain.enums import ArtifactRetention, ArtifactType, ArtifactVisibility
from app.domain.models import Artifact
from app.errors import ArtifactNotFoundError


class ArtifactRepository:
    def __init__(self, database):
        self.database = database

    def create(self, artifact: Artifact) -> Artifact:
        with get_connection(self.database) as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, run_id, job_id, type, name, mime_type,
                    size_bytes, uri, storage_key, visibility, retention,
                    created_at, expires_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.run_id,
                    artifact.job_id,
                    artifact.type.value,
                    artifact.name,
                    artifact.mime_type,
                    artifact.size_bytes,
                    artifact.uri,
                    artifact.storage_key,
                    artifact.visibility.value,
                    artifact.retention.value,
                    artifact.created_at.isoformat(),
                    artifact.expires_at.isoformat() if artifact.expires_at else None,
                    json.dumps(artifact.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        return artifact

    def get(self, artifact_id: str) -> Artifact:
        artifact = self.get_optional(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(artifact_id)
        return artifact

    def get_optional(self, artifact_id: str) -> Optional[Artifact]:
        with get_connection(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def delete(self, artifact_id: str) -> bool:
        with get_connection(self.database) as connection:
            cursor = connection.execute(
                "DELETE FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Artifact:
        expires_at = row["expires_at"]
        return Artifact(
            artifact_id=row["artifact_id"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            type=ArtifactType(row["type"]),
            name=row["name"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            uri=row["uri"],
            storage_key=row["storage_key"],
            visibility=ArtifactVisibility(row["visibility"]),
            retention=ArtifactRetention(row["retention"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            metadata=json.loads(row["metadata_json"]),
        )
