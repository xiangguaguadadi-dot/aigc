import json
import sqlite3
from datetime import datetime
from typing import List, Optional, Set

from app.db import get_connection
from app.domain.enums import JobStatus
from app.domain.models import ArtifactRef, Job, JobError, JobProgress


class JobRepository:
    def __init__(self, database):
        self.database = database

    def create(self, job: Job) -> Job:
        with get_connection(self.database) as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, run_id, service_id, module_key, module_id, status,
                    parameters_json, input_artifacts_json, output_artifacts_json,
                    progress_json, error_json, rerun_of_job_id, created_at,
                    submitted_at, started_at, finished_at, updated_at,
                    last_synced_at, last_sync_error, consecutive_poll_failures
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._params(job),
            )
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with get_connection(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        service_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None,
        module_id: Optional[str] = None,
    ) -> List[Job]:
        query = "SELECT * FROM jobs"
        conditions: list[str] = []
        params: list[object] = []
        if service_id is not None:
            conditions.append("service_id = ?")
            params.append(service_id)
        if module_id is not None:
            conditions.append("module_id = ?")
            params.append(module_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with get_connection(self.database) as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._from_row(row) for row in rows]

    def list_by_statuses(self, statuses: Set[JobStatus]) -> List[Job]:
        placeholders = ",".join("?" for _ in statuses)
        with get_connection(self.database) as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at",
                tuple(status.value for status in statuses),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update(self, job_id: str, **changes) -> Job:
        allowed = {
            "status", "parameters_json", "input_artifacts_json",
            "output_artifacts_json", "progress_json", "error_json", "module_id",
            "submitted_at", "started_at", "finished_at", "updated_at",
            "last_synced_at", "last_sync_error", "consecutive_poll_failures",
        }
        updates = {key: value for key, value in changes.items() if key in allowed}
        if "status" in updates:
            updates["status"] = updates["status"].value
        updates["updated_at"] = datetime.now().astimezone().isoformat()
        fields = ", ".join(f"{key} = ?" for key in updates)
        with get_connection(self.database) as connection:
            connection.execute(
                f"UPDATE jobs SET {fields} WHERE job_id = ?",
                tuple(updates.values()) + (job_id,),
            )
        job = self.get(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        return job

    @staticmethod
    def _params(job: Job):
        return (
            job.job_id,
            job.run_id,
            job.service_id,
            job.module_key,
            job.module_id,
            job.status.value,
            json.dumps(job.parameters, ensure_ascii=False, sort_keys=True),
            json.dumps([item.model_dump(mode="json") for item in job.input_artifacts], ensure_ascii=False),
            json.dumps([item.model_dump(mode="json") for item in job.output_artifacts], ensure_ascii=False),
            job.progress.model_dump_json() if job.progress else None,
            job.error.model_dump_json() if job.error else None,
            job.rerun_of_job_id,
            job.created_at.isoformat(),
            job.submitted_at.isoformat() if job.submitted_at else None,
            job.started_at.isoformat() if job.started_at else None,
            job.finished_at.isoformat() if job.finished_at else None,
            job.updated_at.isoformat(),
            job.last_synced_at.isoformat() if job.last_synced_at else None,
            job.last_sync_error,
            job.consecutive_poll_failures,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        progress = json.loads(row["progress_json"]) if row["progress_json"] else None
        error = json.loads(row["error_json"]) if row["error_json"] else None
        return Job(
            job_id=row["job_id"],
            run_id=row["run_id"],
            service_id=row["service_id"],
            module_key=row["module_key"],
            module_id=row["module_id"],
            status=JobStatus(row["status"]),
            parameters=json.loads(row["parameters_json"]),
            input_artifacts=[ArtifactRef.model_validate(value) for value in json.loads(row["input_artifacts_json"])],
            output_artifacts=[ArtifactRef.model_validate(value) for value in json.loads(row["output_artifacts_json"])],
            progress=JobProgress.model_validate(progress) if progress else None,
            error=JobError.model_validate(error) if error else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            submitted_at=datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]),
            rerun_of_job_id=row["rerun_of_job_id"],
            last_synced_at=datetime.fromisoformat(row["last_synced_at"]) if row["last_synced_at"] else None,
            last_sync_error=row["last_sync_error"],
            consecutive_poll_failures=row["consecutive_poll_failures"],
        )
