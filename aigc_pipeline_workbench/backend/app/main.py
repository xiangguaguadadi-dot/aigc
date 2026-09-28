import asyncio
import os
import os
import contextlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import HttpUrl
from fastapi.responses import JSONResponse

from app.api.public_api import router as public_router
from app.db import Database
from app.errors import AppError
from app.domain.enums import ArtifactType, JobStatus, ParameterValueType, ServiceStatus
from app.errors import JobAlreadyFinishedError, JobNotFoundError
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.domain.models import AlgorithmService, ParameterDefinition, RuntimeSpec, ServiceCapabilities
from app.repositories.service_repository import ServiceRepository
from app.repositories.module_repository import ModuleRepository
from app.domain.models import InputSlot, ModuleDefinition, OutputSlot
from app.schemas.common import ErrorDetail, ErrorResponse
from app.services.artifact_service import ArtifactService
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.services.service_registry import ServiceRegistry
from app.settings import Settings
from app.storage.local_artifact_store import LocalArtifactStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="AIGC Pipeline Workbench Backend",
    version="0.1.0",
)

settings: Optional[Settings] = None
database: Optional[Database] = None
artifact_store: Optional[LocalArtifactStore] = None
artifact_repository: Optional[ArtifactRepository] = None
artifact_service: Optional[ArtifactService] = None
service_registry: Optional[ServiceRegistry] = None
job_manager: Optional[JobManager] = None
polling_task: Optional[asyncio.Task] = None


def initialize_runtime() -> None:
    global settings, database, artifact_store, artifact_repository, artifact_service, service_registry, job_manager
    if artifact_service is not None:
        return
    settings = Settings()
    app.state.settings = settings
    database = Database(settings.database_path)
    database.initialize()
    artifact_store = LocalArtifactStore(settings.artifact_store_root)
    artifact_repository = ArtifactRepository(database)
    artifact_service = ArtifactService(artifact_repository, artifact_store)
    service_repository = ServiceRepository(database)
    module_repository = ModuleRepository(database)
    app.state.module_repository = module_repository
    client = GpuServiceClient(settings)
    service_registry = ServiceRegistry(service_repository, client, settings)
    job_manager = JobManager(
        JobRepository(database),
        JobLogRepository(database),
        service_repository,
        client,
        settings,
    )

    if module_repository.get_by_key("image_to_3d") is None:
        now = datetime.now(timezone.utc)
        module_repository.create(ModuleDefinition(
            module_id="module_image_to_3d",
            module_key="image_to_3d",
            name="Image to Mesh",
            description="Acceptance module for the existing image-to-GLB mock service.",
            version="1.0",
            status="ready",
            input_slots=[InputSlot(name="image", artifact_type=ArtifactType.IMAGE, required=True, accepted_mime_types=["image/png", "image/jpeg"], accepted_extensions=[".png", ".jpg", ".jpeg"])],
            output_slots=[OutputSlot(name="mesh", artifact_type=ArtifactType.GLB, required=True, expected_mime_types=["model/gltf-binary"], expected_extensions=[".glb"]), OutputSlot(name="report", artifact_type=ArtifactType.REPORT, required=False, expected_mime_types=["application/json"], expected_extensions=[".json"])],
            parameter_schema=[],
            runtime_spec=RuntimeSpec(
                runtime_type="gpu",
                gpu_mode="dedicated",
                min_vram_gb=40.0,
                model_residency="persistent",
                max_concurrency=1,
                description="TRELLIS.2 requires dedicated A100 40GB+ GPU",
            ),
            created_at=now,
            updated_at=now,
        ))
    if module_repository.get_by_key("multi_input_test") is None:
        now = datetime.now(timezone.utc)
        module_repository.create(ModuleDefinition(
            module_id="module_multi_input_test",
            module_key="multi_input_test",
            name="Multi-Input Test Module",
            description="Verifies dynamic required and optional input slots.",
            version="1.0",
            status="ready",
            input_slots=[InputSlot(name="image", artifact_type=ArtifactType.IMAGE, required=True, accepted_mime_types=["image/png"], accepted_extensions=[".png"]), InputSlot(name="reference", artifact_type=ArtifactType.IMAGE, required=False, accepted_mime_types=["image/png"], accepted_extensions=[".png"])],
            output_slots=[OutputSlot(name="report", artifact_type=ArtifactType.REPORT, required=True, expected_mime_types=["application/json"], expected_extensions=[".json"])],
            parameter_schema=[],
            created_at=now,
            updated_at=now,
        ))
    if module_repository.get_by_key("frontend_demo") is None:
        now = datetime.now(timezone.utc)
        module_repository.create(ModuleDefinition(
            module_id="module_frontend_demo",
            module_key="frontend_demo",
            name="Built-in Frontend Demo",
            description="Built-in succeeded demo job without external GPU service.",
            version="1.0",
            status="ready",
            input_slots=[],
            output_slots=[OutputSlot(name="report", artifact_type=ArtifactType.REPORT, required=True, expected_mime_types=["application/json"], expected_extensions=[".json"]), OutputSlot(name="mesh", artifact_type=ArtifactType.GLB, required=True, expected_mime_types=["model/gltf-binary"], expected_extensions=[".glb"])],
            parameter_schema=[],
            created_at=now,
            updated_at=now,
        ))
    if service_repository.get("service_frontend_demo") is None:
        now = datetime.now(timezone.utc)
        service_repository.create(AlgorithmService(
            service_id="service_frontend_demo",
            module_key="frontend_demo",
            name="Built-in Frontend Demo",
            base_url=HttpUrl("http://127.0.0.1:8000"),
            enabled=True,
            status=ServiceStatus.ONLINE,
            version="0.1.0",
            capabilities=ServiceCapabilities(
                input_artifact_types=[ArtifactType.IMAGE],
                output_artifact_types=[ArtifactType.REPORT, ArtifactType.GLB],
                parameter_schema=[
                    ParameterDefinition(
                        key="message",
                        label="Demo Message",
                        value_type=ParameterValueType.STRING,
                        required=False,
                        default="Built-in demo job",
                        description="Message stored in the demo report.",
                    )
                ],
                supports_cancel=False,
                supports_progress=False,
                max_concurrent_jobs=1,
            ),
            registered_at=now,
            updated_at=now,
        ))
    
    # Seed TRELLIS service registration (enabled only if reachable)
    trellis_url = os.environ.get("TRELLIS_SERVICE_URL", "http://127.0.0.1:8201")
    if service_registry.repository.get("service_trellis") is None:
        from pydantic import HttpUrl
        now = datetime.now(timezone.utc)
        service_registry.repository.create(AlgorithmService(
            service_id="service_trellis",
            module_key="trellis_image_to_3d",
            name="TRELLIS.2 GPU Service",
            base_url=HttpUrl(trellis_url),
            instance_label="A100-dedicated",
            enabled=True,
            status=ServiceStatus.UNKNOWN,
            version="1.0.0",
            gpu=None,
            capabilities=ServiceCapabilities(
                input_artifact_types=[ArtifactType.IMAGE],
                output_artifact_types=[ArtifactType.GLB, ArtifactType.REPORT],
                parameter_schema=[
                    ParameterDefinition(key="steps", label="Sampling Steps", value_type=ParameterValueType.INTEGER, required=False, default=12, minimum=4, maximum=20, description="Number of diffusion sampling steps."),
                ],
                supports_cancel=True,
                supports_progress=True,
                max_concurrent_jobs=1,
                estimated_duration_seconds=120,
            ),
            registered_at=now,
            updated_at=now,
        ))


def get_settings() -> Settings:
    return Settings()


def get_database() -> Database:
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    return database


def get_artifact_repository() -> ArtifactRepository:
    return ArtifactRepository(get_database())


def get_artifact_store() -> LocalArtifactStore:
    store = getattr(app.state, "artifact_store", None)
    if store is not None:
        return store
    initialize_runtime()
    assert artifact_store is not None
    return artifact_store


def get_artifact_service() -> ArtifactService:
    initialize_runtime()
    assert artifact_service is not None
    return artifact_service


def artifact_store_path(storage_key: Optional[str]) -> Path:
    if storage_key is None:
        raise AppError.from_code("INVALID_REQUEST", "artifact has no file")
    store = get_artifact_store()
    assert storage_key is not None
    return store._resolve(storage_key)


async def poll_active_jobs() -> None:
    settings = get_settings()
    logger = logging.getLogger("workbench.polling")
    while True:
        await asyncio.sleep(settings.poll_interval_seconds)
        try:
            active_statuses = {"submitting", "submitted", "queued", "running", "cancelling"}
            database = get_database()
            repository = JobRepository(database)
            job_log_repository = JobLogRepository(database)
            service_repository = ServiceRepository(database)
            manager = JobManager(
                repository,
                job_log_repository,
                service_repository,
                GpuServiceClient(settings),
                settings,
            )
            jobs = repository.list_by_statuses(
                {
                    JobStatus(status)
                    for status in active_statuses
                }
            )
            if settings.start_background_polling and not jobs:
                continue
            logger.info("restart recovery starting", extra={"active_jobs": len(jobs)})
            for job in jobs:
                if job.consecutive_poll_failures >= 3 and job.status != JobStatus.CANCELLING:
                    logger.warning(
                        "poll failures threshold reached",
                        extra={"job_id": job.job_id, "service_id": job.service_id, "failures": job.consecutive_poll_failures},
                    )
                    continue
                await manager.sync(job.job_id)
        except Exception:
            logger.exception("polling cycle failed")
            continue


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    global polling_task
    settings = get_settings()
    initialize_runtime()
    if settings.start_background_polling:
        logger = logging.getLogger("workbench.runtime")
        logger.info("background polling enabled", extra={"poll_interval_seconds": settings.poll_interval_seconds})
        polling_task = asyncio.create_task(poll_active_jobs())
    try:
        yield
    finally:
        if polling_task is not None:
            polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await polling_task


app.router.lifespan_context = lifespan
app.state.settings = None
app.include_router(public_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=error_detail_from_code(exc)).model_dump(),
    )


@app.exception_handler(JobNotFoundError)
async def job_not_found_handler(request: Request, exc: JobNotFoundError):
    return await app_error_handler(request, exc)


@app.exception_handler(JobAlreadyFinishedError)
async def job_already_finished_handler(request: Request, exc: JobAlreadyFinishedError):
    return await app_error_handler(request, exc)


def error_detail_from_code(exc: AppError):
    return ErrorDetail(code=exc.code, message=exc.message, details=exc.details)
