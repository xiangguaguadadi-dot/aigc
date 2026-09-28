import asyncio
import json
import random
from importlib import resources
import uuid
from typing import Optional
from uuid import UUID

from fastapi import FastAPI

from .artifact_client import upload_artifact
from .contract import JobSubmitRequest, OutputArtifact
from .job_store import JobStore, StoredJob, utcnow
from .settings import MockSettings


class MockGPUService(FastAPI):
    def __init__(
        self,
        module_key: str,
        service_name: str,
        version: str,
        parameter_schema: list[dict],
        default_duration: float,
        max_duration: float = 300,
    ):
        super().__init__(title=service_name, version=version)
        self.module_key = module_key
        self.service_name = service_name
        self.version = version
        self.parameter_schema = parameter_schema
        self.default_duration = default_duration
        self.max_duration = max_duration
        self.settings = MockSettings()
        self.store = JobStore()
        self.tasks: dict[str, asyncio.Task] = {}
        self._register_routes()

    def _register_routes(self):
        @self.get("/v1/health")
        def health():
            return {
                "status": "online",
                "service": self.module_key,
                "version": self.version,
                "load": {
                    "running_jobs": sum(
                        1 for task in self.tasks.values() if not task.done()
                    ),
                    "max_concurrent_jobs": 1,
                },
            }

        @self.get("/v1/metadata")
        def metadata():
            return {
                "module_key": self.module_key,
                "name": self.service_name,
                "version": self.version,
                "input_artifact_types": ["image", "mask"],
                "output_artifact_types": ["report", "glb"],
                "parameter_schema": self.parameter_schema,
                "supports_cancel": True,
                "supports_progress": True,
                "max_concurrent_jobs": 1,
            }

        @self.post("/v1/jobs")
        async def submit_job(request: JobSubmitRequest):
            if request.module_key != self.module_key:
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="module_key mismatch")
            self.validate_parameters(request.parameters)
            duration = float(request.parameters.get("duration_seconds", self.default_duration))
            if duration <= 0 or duration > self.max_duration:
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="duration_seconds out of range")
            failure_rate = float(request.parameters.get("failure_rate", 0))
            if failure_rate < 0 or failure_rate > 1:
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="failure_rate out of range")
            force_failure = request.parameters.get("force_failure", False)
            if not isinstance(force_failure, bool):
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="force_failure must be a boolean")
            if self.module_key != "mock_slow" and (force_failure or failure_rate):
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="failure parameters not supported")
            job = StoredJob(
                job_id=request.job_id,
                module_key=request.module_key,
                status="queued",
                created_at=utcnow(),
                updated_at=utcnow(),
                failure_rate=1 if force_failure else failure_rate,
            )
            self.store.create(job)
            self.store.add_log(job.job_id, "info", "job received")
            setattr(job, "parameters", request.parameters)
            self.tasks[job.job_id] = asyncio.create_task(self.execute(job.job_id, duration))
            return {"job_id": job.job_id, "status": "queued"}

        @self.get("/v1/jobs/{job_id}")
        def job_status(job_id: str, log_after_seq: int = -1):
            job = self.store.get(job_id)
            if job is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "job not found", "details": {"job_id": job_id}})
            logs = job.logs
            if log_after_seq >= 0:
                logs = [log for log in logs if log.seq > log_after_seq]
            return {
                "job_id": job.job_id,
                "status": job.status,
                "progress": {
                    "percent": job.progress_percent,
                    "phase": job.progress_phase,
                },
                "logs": [log.model_dump() for log in logs],
                "output_artifacts": [a.model_dump() for a in job.output_artifacts],
                "error": job.error,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "updated_at": job.updated_at,
            }

        @self.post("/v1/jobs/{job_id}/cancel")
        def cancel_job(job_id: str):
            job = self.store.get(job_id)
            if job is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "job not found", "details": {"job_id": job_id}})
            if job.status in {"succeeded", "failed", "cancelled", "timeout"}:
                from fastapi import HTTPException
                raise HTTPException(status_code=409, detail={"code": "JOB_ALREADY_FINISHED", "message": "job already finished", "details": {"job_id": job_id}})
            if job.status in {"queued", "running"}:
                self.store.update(job_id, status="cancelling", cancel_requested=True)
                task = self.tasks.get(job_id)
                if task:
                    task.cancel()
                return {"job_id": job_id, "status": "cancelling"}
            return {"job_id": job_id, "status": job.status}

    def validate_parameters(self, parameters: dict) -> None:
        for definition in self.parameter_schema:
            key = definition["key"]
            if key not in parameters:
                continue
            if key not in {"duration_seconds", "failure_rate", "force_failure"}:
                continue
            value = parameters[key]
            value_type = definition["value_type"]
            if value_type == "integer" and not isinstance(value, int):
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail=f"{key} must be an integer")
            if value_type == "number" and not isinstance(value, (int, float)):
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail=f"{key} must be a number")
            if value_type == "boolean" and not isinstance(value, bool):
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail=f"{key} must be a boolean")

    async def execute(self, job_id: str, duration: float) -> None:
        try:
            await asyncio.sleep(0)
            job = self.store.get(job_id)
            if job is None or job.cancel_requested:
                return
            self.store.update(job_id, status="running", started_at=utcnow(), progress_phase="loading")
            self.store.add_log(job_id, "info", "fake inference started")
            steps = max(1, int(duration * 4))
            for index in range(steps):
                await asyncio.sleep(duration / steps)
                job = self.store.get(job_id)
                if job is None or job.cancel_requested:
                    return
                percent = min(99, int((index + 1) * 100 / steps))
                self.store.update(job_id, progress_percent=percent, progress_phase="inference")
            job = self.store.get(job_id)
            if job is None:
                return
            if job.failure_rate > 0 and random.random() < job.failure_rate:
                raise RuntimeError("simulated GPU failure")
            await self.finish_successfully(job_id)
        except asyncio.CancelledError:
            self.store.update(job_id, status="cancelled", finished_at=utcnow(), progress_phase="cancelled")
            self.store.add_log(job_id, "warn", "job cancelled")
        except Exception:
            self.store.update(
                job_id,
                status="failed",
                finished_at=utcnow(),
                progress_phase="failed",
                error={"code": "INTERNAL_ERROR", "message": "simulated GPU failure", "details": {}},
            )
            self.store.add_log(job_id, "error", "fake inference failed")

    async def finish_successfully(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        glb_bytes = resources.files("mock_services.fixtures").joinpath("simple_cube.glb").read_bytes()
        report = {
            "job_id": job_id,
            "message": job.parameters.get("message", "mock job succeeded"),
            "status": "succeeded",
        }
        try:
            uploaded_report = await upload_artifact(
                self.settings,
                job_id,
                json.dumps(report, ensure_ascii=False).encode("utf-8"),
                f"{job_id}_report.json",
                artifact_type="report",
            )
            uploaded_glb = await upload_artifact(
                self.settings,
                job_id,
                glb_bytes,
                "simple_cube.glb",
                artifact_type="glb",
            )
            artifacts = [
                OutputArtifact(
                    artifact_id=item["artifact_id"],
                    type=item["type"],
                    name=item["name"],
                    uri=item["uri"],
                    mime_type=item["mime_type"],
                    size_bytes=item["size_bytes"],
                    metadata={"job_id": job_id, "output_slot": "report" if item is uploaded_report else "mesh"},
                )
                for item in (uploaded_report, uploaded_glb)
            ]
        except Exception:
            self.store.update(
                job_id,
                status="failed",
                finished_at=utcnow(),
                progress_phase="failed",
                error={"code": "INTERNAL_ERROR", "message": "artifact upload failed", "details": {}},
            )
            self.store.add_log(job_id, "error", "artifact upload failed")
            return
        self.store.update(job_id, status="succeeded", finished_at=utcnow(), progress_percent=100, progress_phase="done")
        self.store.update(job_id, output_artifacts=artifacts)
        self.store.add_log(job_id, "info", "fake inference finished")
