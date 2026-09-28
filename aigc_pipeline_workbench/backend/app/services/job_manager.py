import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.domain.enums import ArtifactType, ErrorCode, JobStatus, LogLevel, LogSource, ServiceStatus
from app.domain.models import ArtifactRef, Job, JobError, JobLog, JobProgress
from app.errors import AppError, JobAlreadyFinishedError, JobNotFoundError
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.service_repository import ServiceRepository
from app.schemas.common import ArtifactDescriptor
from app.schemas.job import JobStatusResponse
from app.services.gpu_service_client import GpuServiceClient
from app.settings import Settings

logger = logging.getLogger("workbench.jobs")

TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.TIMEOUT,
}

ALLOWED_TRANSITIONS = {
    JobStatus.CREATED: {JobStatus.SUBMITTING, JobStatus.SUBMIT_FAILED},
    JobStatus.SUBMITTING: {JobStatus.SUBMITTED, JobStatus.SUBMIT_FAILED},
    JobStatus.SUBMIT_FAILED: {JobStatus.SUBMITTING},
    JobStatus.SUBMITTED: {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELLING, JobStatus.SUCCEEDED, JobStatus.FAILED},
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLING, JobStatus.SUCCEEDED, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.CANCELLING, JobStatus.SUCCEEDED, JobStatus.FAILED},
    JobStatus.CANCELLING: {JobStatus.CANCELLED, JobStatus.SUCCEEDED, JobStatus.FAILED},
}

SUBMIT_ACCEPTED_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.RUNNING,
    JobStatus.CANCELLING,
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def can_transition(old: JobStatus, new: JobStatus) -> bool:
    if old == new:
        return True
    return new in ALLOWED_TRANSITIONS.get(old, set())


class JobManager:
    def __init__(
        self,
        job_repository: JobRepository,
        job_log_repository: JobLogRepository,
        service_repository: ServiceRepository,
        client: GpuServiceClient,
        settings: Optional[Settings] = None,
    ):
        self.job_repository = job_repository
        self.job_log_repository = job_log_repository
        self.service_repository = service_repository
        self.client = client
        self.settings = settings or Settings()

    async def create_job(
        self,
        service_id: str,
        parameters: dict[str, Any],
        input_artifacts: Optional[list[ArtifactRef]] = None,
        rerun_of_job_id: Optional[str] = None,
        module_id: Optional[str] = None,
    ) -> Job:
        service = self.service_repository.get(service_id)
        if service is None:
            raise AppError.from_code("JOB_NOT_FOUND", "service not found", {"service_id": service_id})
        if not service.enabled:
            raise AppError.from_code("INVALID_REQUEST", "service is disabled", {"service_id": service_id})
        if service.status != ServiceStatus.ONLINE:
            raise AppError.from_code("SERVICE_BUSY", "service is offline", {"service_id": service_id})
        now = datetime.now(timezone.utc)
        job = Job(
            job_id=f"job_{now.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}",
            service_id=service_id,
            module_key=service.module_key,
            module_id=module_id,
            status=JobStatus.CREATED,
            parameters=parameters,
            input_artifacts=input_artifacts or [],
            created_at=now,
            updated_at=now,
            rerun_of_job_id=rerun_of_job_id,
        )
        created = self.job_repository.create(job)
        logger.info(
            "job created",
            extra={"job_id": job.job_id, "service_id": service_id, "module_key": job.module_key},
        )
        return created

    async def submit(self, job_id: str) -> Job:
        job = self._get(job_id)
        if job.status not in {JobStatus.CREATED, JobStatus.SUBMIT_FAILED}:
            raise AppError.from_code("INVALID_REQUEST", "job is not submittable", {"job_id": job_id})
        service = self.service_repository.get(job.service_id)
        if service is None:
            raise AppError.from_code("JOB_NOT_FOUND", "service not found", {"service_id": job.service_id})
        job = self.job_repository.update(job_id, status=JobStatus.SUBMITTING, submitted_at=None)
        logger.info("remote submit started", extra={"job_id": job_id, "service_id": service.service_id})
        try:
            response = await self.client.submit_job(
                str(service.base_url),
                job.job_id,
                job.module_key,
                [item.model_dump(mode="json") for item in job.input_artifacts],
                job.parameters,
            )
        except Exception as exc:
            logger.exception("remote submit failed", extra={"job_id": job_id, "service_id": service.service_id})
            return self.job_repository.update(
                job_id,
                status=JobStatus.SUBMIT_FAILED,
                error=JobError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=str(exc),
                    details={"service_id": service.service_id},
                ).model_dump(),
            )
        remote_status = response.get("status")
        try:
            remote_job_status = JobStatus(remote_status)
        except ValueError:
            remote_job_status = JobStatus.SUBMITTED
        if remote_job_status not in SUBMIT_ACCEPTED_STATUSES:
            remote_job_status = JobStatus.SUBMITTED
        updated = self.job_repository.update(
            job_id,
            status=remote_job_status,
            submitted_at=datetime.now(timezone.utc),
            error=None,
            consecutive_poll_failures=0,
            last_sync_error=None,
        )
        logger.info("remote submit succeeded", extra={"job_id": job_id, "status": updated.status.value})
        return updated

    async def rerun(self, job_id: str) -> Job:
        source = self._get(job_id)
        return await self.create_job(
            source.service_id,
            source.parameters,
            source.input_artifacts,
            rerun_of_job_id=source.job_id,
        )

    async def cancel(self, job_id: str) -> Job:
        job = self._get(job_id)
        if job.status in TERMINAL_STATUSES:
            raise JobAlreadyFinishedError(job_id)
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            job = self.job_repository.update(job_id, status=JobStatus.CANCELLING)
            logger.info("cancel requested", extra={"job_id": job_id})
            service = self.service_repository.get(job.service_id)
            if service is None:
                raise AppError.from_code("JOB_NOT_FOUND", "service not found", {"service_id": job.service_id})
            try:
                await self.client.cancel_job(str(service.base_url), job_id)
            except Exception as exc:
                self._append_orchestrator_log(job_id, LogLevel.WARN, f"cancel failed: {exc}")
        return self._get(job_id)

    async def sync(self, job_id: str) -> Job:
        job = self._get(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        service = self.service_repository.get(job.service_id)
        if service is None:
            raise AppError.from_code("JOB_NOT_FOUND", "service not found", {"service_id": job.service_id})
        try:
            remote = await self.client.job_status(
                str(service.base_url),
                job_id,
                log_after_seq=self.job_log_repository.max_seq(job_id),
            )
        except Exception as exc:
            failures = job.consecutive_poll_failures + 1
            logger.warning("job sync failed", extra={"job_id": job_id, "failures": failures})
            job = self.job_repository.update(
                job_id,
                consecutive_poll_failures=failures,
                last_sync_error=str(exc),
                last_synced_at=None,
            )
            self._append_orchestrator_log(job_id, LogLevel.WARN, f"sync failed: {exc}")
            return job
        if isinstance(remote, dict):
            remote = JobStatusResponse.model_validate(remote)
        current = self.job_repository.get(job_id)
        if current is not None and current.status in TERMINAL_STATUSES:
            return current
        if current is not None and not can_transition(current.status, remote.status):
            return current
        self._sync_logs(job, remote)
        output_artifacts = [ArtifactRef.model_validate(item.model_dump(mode="json")) for item in remote.output_artifacts]
        return self.job_repository.update(
            job_id,
            status=remote.status,
            progress_json=remote.progress.model_dump_json() if remote.progress else None,
            output_artifacts_json=json.dumps(
                [item.model_dump(mode="json") for item in output_artifacts],
                ensure_ascii=False,
            ),
            error_json=remote.error.model_dump_json() if remote.error else None,
            started_at=remote.started_at,
            finished_at=remote.finished_at,
            last_synced_at=datetime.now(timezone.utc),
            last_sync_error=None,
            consecutive_poll_failures=0,
        )
        updated = self.job_repository.get(job_id)
        if updated is not None:
            logger.info("job synchronized", extra={"job_id": job_id, "status": updated.status.value})
            return updated
        return job

    async def recover(self) -> None:
        jobs = self.job_repository.list_by_statuses(
            {JobStatus.SUBMITTING, JobStatus.SUBMITTED, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELLING}
        )
        logger.info("restart recovery starting", extra={"active_jobs": len(jobs)})
        for job in jobs:
            if job.status == JobStatus.SUBMITTING:
                self.job_repository.update(
                    job.job_id,
                    status=JobStatus.SUBMIT_FAILED,
                    error=JobError(
                        code=ErrorCode.INTERNAL_ERROR,
                        message="job was interrupted during submit",
                        details={},
                    ).model_dump(),
                )
                continue
            logger.info("recovering active job", extra={"job_id": job.job_id})
            await self.sync(job.job_id)

    def _get(self, job_id: str) -> Job:
        job = self.job_repository.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def _sync_logs(self, job: Job, remote) -> None:
        for entry in remote.logs:
            try:
                level = LogLevel(entry.level)
            except ValueError:
                level = LogLevel.INFO
            log = JobLog(
                log_id=f"{job.job_id}_{entry.seq}",
                job_id=job.job_id,
                service_id=job.service_id,
                seq=entry.seq,
                source=LogSource.SERVICE,
                level=level,
                message=entry.message,
                created_at=entry.created_at,
            )
            self.job_log_repository.create(log)

    def _append_orchestrator_log(self, job_id: str, level: LogLevel, message: str) -> None:
        seq = self.job_log_repository.max_seq(job_id) + 1
        log = JobLog(
            log_id=f"{job_id}_orch_{seq}_{uuid4().hex[:6]}",
            job_id=job_id,
            service_id=None,
            seq=seq,
            source=LogSource.ORCHESTRATOR,
            level=level,
            message=message,
            created_at=datetime.now(timezone.utc),
        )
        self.job_log_repository.create(log)
