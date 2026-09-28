from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from .contract import JobLogEntry, OutputArtifact


class StoredJob(BaseModel):
    job_id: str
    module_key: str
    status: str
    progress_percent: int = 0
    progress_phase: str = "queued"
    logs: list[JobLogEntry] = Field(default_factory=list)
    output_artifacts: list[OutputArtifact] = Field(default_factory=list)
    error: Optional[dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime
    cancel_requested: bool = False
    failure_rate: float = 0.0
    parameters: dict[str, Any] = Field(default_factory=dict)
    control_plane_job_id: Optional[str] = None


class JobStore:
    def __init__(self):
        self.jobs: dict[str, StoredJob] = {}

    def create(self, job: StoredJob) -> StoredJob:
        self.jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[StoredJob]:
        return self.jobs.get(job_id)

    def add_log(self, job_id: str, level: str, message: str) -> None:
        job = self.jobs[job_id]
        job.logs.append(
            JobLogEntry(
                seq=len(job.logs),
                level=level,
                message=message,
                created_at=utcnow(),
            )
        )

    def update(self, job_id: str, **changes: Any) -> StoredJob:
        job = self.jobs[job_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = utcnow()
        return job


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
