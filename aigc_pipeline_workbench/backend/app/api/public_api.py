import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.domain.enums import ArtifactRetention, ArtifactType, ArtifactVisibility, JobStatus, LogLevel, LogSource
from app.domain.models import Artifact, ArtifactRef, Job, JobLog, JobProgress
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_log_repository import JobLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.service_repository import ServiceRepository
from app.schemas.artifact import ArtifactMetadataResponse, ArtifactUploadResponse
from app.schemas.common import CONTRACT_VERSION
from app.errors import ArtifactNotFoundError
from app.repositories.module_repository import ModuleRepository
from app.schemas.module import ModuleCompatibilityResponse, ModuleCreateRequest, ModuleResponse, ModuleUpdateRequest
from app.services.module_validation import ModuleValidation
from app.services.artifact_service import ArtifactService
from app.services.gpu_service_client import GpuServiceClient
from app.services.job_manager import JobManager
from app.services.service_registry import ServiceRegistry
from app.settings import Settings


def get_settings() -> Settings:
    from app.main import app, initialize_runtime

    settings = app.state.settings
    if settings is None:
        initialize_runtime()
        settings = app.state.settings
    return settings

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {
        "status": "ok",
        "version": settings.app_version,
        "contract_version": settings.contract_version,
}


def artifact_service_from_request(request: Request) -> ArtifactService:
    service = getattr(request.app.state, "artifact_service", None)
    if service is not None:
        return service
    from app.main import get_artifact_service
    return get_artifact_service()


def artifact_repository_from_request(request: Request) -> ArtifactRepository:
    repository = getattr(request.app.state, "artifact_repository", None)
    if repository is not None:
        return repository
    from app.main import get_artifact_repository
    return get_artifact_repository()


def service_registry_from_request(request: Request) -> ServiceRegistry:
    registry = getattr(request.app.state, "service_registry", None)
    if registry is not None:
        return registry
    settings = get_settings()
    from app.main import get_database
    database = get_database()
    repository = ServiceRepository(database)
    return ServiceRegistry(repository, GpuServiceClient(settings), settings)


def job_manager_from_request(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is not None:
        return manager
    settings = get_settings()
    from app.main import get_database
    database = get_database()
    service_registry = service_registry_from_request(request)
    return JobManager(
        JobRepository(database),
        JobLogRepository(database),
        service_registry.repository,
        service_registry.client,
        settings,
    )


def module_repository_from_request(request: Request) -> ModuleRepository:
    repository = getattr(request.app.state, "module_repository", None)
    if repository is not None:
        return repository
    return ModuleRepository(request.app.state.database)


@router.post("/artifacts", response_model=ArtifactUploadResponse)
def upload_artifact(
    file: UploadFile = File(...),
    artifact_type: ArtifactType = Form(...),
    metadata: Optional[str] = Form(default=None),
    run_id: Optional[str] = Form(default=None),
    job_id: Optional[str] = Form(default=None),
    retention: ArtifactRetention = Form(default=ArtifactRetention.TEMPORARY),
    service: ArtifactService = Depends(artifact_service_from_request),
):
    parsed_metadata = {}
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="metadata must be valid JSON") from exc
    artifact = service.upload(
        content=file.file,
        artifact_type=artifact_type,
        filename=file.filename or "upload.bin",
        mime_type=file.content_type,
        metadata=parsed_metadata,
        run_id=run_id,
        job_id=job_id,
        retention=retention,
    )
    return ArtifactUploadResponse(
        artifact_id=artifact.artifact_id,
        type=artifact.type,
        name=artifact.name,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        uri=artifact.uri,
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactMetadataResponse)
def get_artifact(
    artifact_id: str,
    repository: ArtifactRepository = Depends(artifact_repository_from_request),
):
    artifact = repository.get(artifact_id)
    return ArtifactMetadataResponse(
        artifact_id=artifact.artifact_id,
        type=artifact.type,
        name=artifact.name,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        uri=artifact.uri,
        metadata=artifact.metadata,
    )


@router.get("/artifacts/{artifact_id}/file")
def get_artifact_file(
    artifact_id: str,
    repository: ArtifactRepository = Depends(artifact_repository_from_request),
):
    artifact = repository.get(artifact_id)
    from app.main import get_artifact_store
    store = get_artifact_store()
    storage_key = artifact.storage_key
    if storage_key is None:
        raise HTTPException(status_code=404, detail="artifact file not found")
    path = store._resolve(storage_key)
    return FileResponse(path, media_type=artifact.mime_type, filename=artifact.name)


@router.get("/services")
def list_services(registry: ServiceRegistry = Depends(service_registry_from_request)):
    return [service.model_dump(mode="json") for service in registry.list()]


@router.post("/services")
async def register_service(
    name: str = Form(...),
    base_url: str = Form(...),
    instance_label: Optional[str] = Form(default=None),
    enabled: bool = Form(default=True),
    registry: ServiceRegistry = Depends(service_registry_from_request),
):
    service = registry.register(name, base_url, instance_label, enabled)
    return await registry.check(service.service_id)


@router.get("/services/{service_id}")
def get_service(service_id: str, registry: ServiceRegistry = Depends(service_registry_from_request)):
    return registry.get(service_id).model_dump(mode="json")


@router.post("/services/{service_id}/check")
async def check_service(service_id: str, registry: ServiceRegistry = Depends(service_registry_from_request)):
    return (await registry.check(service_id)).model_dump(mode="json")


@router.post("/services/{service_id}/disable")
def disable_service(service_id: str, registry: ServiceRegistry = Depends(service_registry_from_request)):
    service = registry.get(service_id)
    service.enabled = False
    service.updated_at = service.updated_at.now()
    return registry.repository.update(service).model_dump(mode="json")


@router.post("/services/{service_id}/enable")
def enable_service(service_id: str, registry: ServiceRegistry = Depends(service_registry_from_request)):
    service = registry.get(service_id)
    service.enabled = True
    service.updated_at = service.updated_at.now()
    return registry.repository.update(service).model_dump(mode="json")


@router.post("/jobs")
async def create_job(
    service_id: str = Form(...),
    parameters: Optional[str] = Form(default="{}"),
    input_artifacts: Optional[str] = Form(default="[]"),
    module_id: Optional[str] = Form(default=None),
    manager: JobManager = Depends(job_manager_from_request),
    module_repository: ModuleRepository = Depends(module_repository_from_request),
):
    try:
        parsed_parameters = json.loads(parameters or "{}")
        parsed_inputs = json.loads(input_artifacts or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="parameters and input_artifacts must be valid JSON") from exc
    inputs = [ArtifactRef.model_validate(value) for value in parsed_inputs]
    module = module_repository.get(module_id) if module_id else None
    if module_id and module is None:
        raise HTTPException(status_code=404, detail="module not found")
    if module is not None:
        ModuleValidation.validate_job_inputs(module, inputs, parsed_parameters)
    job = await manager.create_job(service_id, parsed_parameters, inputs, module_id=module_id)
    return await manager.submit(job.job_id)


@router.get("/jobs")
def list_jobs(
    service_id: Optional[str] = None,
    module_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    manager: JobManager = Depends(job_manager_from_request),
):
    try:
        job_status = JobStatus(status) if status is not None else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid job status") from exc
    jobs = manager.job_repository.list(
        service_id=service_id,
        module_id=module_id,
        status=job_status,
        limit=limit,
    )
    return [job.model_dump(mode="json") for job in jobs]


@router.get("/jobs/demo")
def get_demo_job(
    artifact_service: ArtifactService = Depends(artifact_service_from_request),
    manager: JobManager = Depends(job_manager_from_request),
):
    now = datetime.now(timezone.utc)
    from app.main import get_artifact_store
    artifact_store = get_artifact_store()

    report_id = "artifact_demo_report"
    glb_id = "artifact_demo_glb"
    if artifact_service.repository.get_optional(report_id) is None:
        report_content = json.dumps({
            "job_id": "job_frontend_demo",
            "message": "Frontend demo succeeded",
            "status": "succeeded",
        }, ensure_ascii=False).encode("utf-8")
        artifact_service.repository.create(Artifact(
            artifact_id=report_id,
            job_id="job_frontend_demo",
            type=ArtifactType.REPORT,
            name="demo_report.json",
            mime_type="application/json",
            size_bytes=len(report_content),
            uri=f"/api/v1/artifacts/{report_id}/file",
            storage_key="demo/demo_report.json",
            visibility=ArtifactVisibility.INTERNAL,
            retention=ArtifactRetention.RESULT,
            created_at=now,
            metadata={"demo": True, "output_slot": "report"},
        ))
        artifact_store.save("demo/demo_report.json", io.BytesIO(report_content))
    if artifact_service.repository.get_optional(glb_id) is None:
        glb_content = (Path(__file__).resolve().parents[3] / "mock_services" / "fixtures" / "simple_cube.glb").read_bytes()
        artifact_service.repository.create(Artifact(
            artifact_id=glb_id,
            job_id="job_frontend_demo",
            type=ArtifactType.GLB,
            name="demo_cube.glb",
            mime_type="model/gltf-binary",
            size_bytes=len(glb_content),
            uri=f"/api/v1/artifacts/{glb_id}/file",
            storage_key="demo/demo_cube.glb",
            visibility=ArtifactVisibility.INTERNAL,
            retention=ArtifactRetention.RESULT,
            created_at=now,
            metadata={"demo": True, "output_slot": "mesh"},
        ))
        artifact_store.save("demo/demo_cube.glb", io.BytesIO(glb_content))

    job = manager.job_repository.get("job_frontend_demo")
    if job is None:
        job = manager.job_repository.create(Job(
            job_id="job_frontend_demo",
            service_id="service_frontend_demo",
            module_key="frontend_demo",
            status=JobStatus.SUCCEEDED,
            parameters={"source": "built-in demo"},
            input_artifacts=[],
            output_artifacts=[
                ArtifactRef(artifact_id=report_id, type=ArtifactType.REPORT, name="demo_report.json", uri=f"/api/v1/artifacts/{report_id}/file", metadata={"demo": True, "output_slot": "report"}),
                ArtifactRef(artifact_id=glb_id, type=ArtifactType.GLB, name="demo_cube.glb", uri=f"/api/v1/artifacts/{glb_id}/file", metadata={"demo": True, "output_slot": "mesh"}),
            ],
            progress=JobProgress(percent=100, phase="succeeded", message="Built-in frontend demo"),
            created_at=now,
            submitted_at=now,
            started_at=now,
            finished_at=now,
            updated_at=now,
        ))
    else:
        job = manager.job_repository.update(
            job.job_id,
            status=JobStatus.SUCCEEDED,
            output_artifacts_json=json.dumps([
                {"artifact_id": report_id, "type": "report", "name": "demo_report.json", "uri": f"/api/v1/artifacts/{report_id}/file", "metadata": {"demo": True, "output_slot": "report"}},
                {"artifact_id": glb_id, "type": "glb", "name": "demo_cube.glb", "uri": f"/api/v1/artifacts/{glb_id}/file", "metadata": {"demo": True, "output_slot": "mesh"}},
            ]),
            progress_json=JobProgress(percent=100, phase="succeeded", message="Built-in frontend demo").model_dump_json(),
            error_json=None,
            module_id="module_frontend_demo",
        )

    log_repository = JobLogRepository(manager.job_repository.database)
    if log_repository.max_seq(job.job_id) < 0:
        for seq, level, message in [
            (0, LogLevel.INFO, "Built-in demo job received"),
            (1, LogLevel.INFO, "Built-in demo inference completed"),
            (2, LogLevel.INFO, "Demo GLB artifact ready"),
        ]:
            log_repository.create(JobLog(
                log_id=f"log_frontend_demo_{seq}",
                job_id=job.job_id,
                service_id="service_frontend_demo",
                seq=seq,
                source=LogSource.SERVICE,
                level=level,
                message=message,
                created_at=now,
            ))
    return job.model_dump(mode="json")

@router.get("/jobs/{job_id}")
def get_job(job_id: str, manager: JobManager = Depends(job_manager_from_request)):
    job = manager._get(job_id)
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, manager: JobManager = Depends(job_manager_from_request)):
    return (await manager.cancel(job_id)).model_dump(mode="json")


@router.post("/jobs/{job_id}/rerun")
async def rerun_job(job_id: str, manager: JobManager = Depends(job_manager_from_request)):
    job = await manager.rerun(job_id)
    return await manager.submit(job.job_id)


@router.post("/jobs/{job_id}/sync")
async def sync_job(job_id: str, manager: JobManager = Depends(job_manager_from_request)):
    return (await manager.sync(job_id)).model_dump(mode="json")


@router.get("/jobs/{job_id}/logs")
def get_job_logs(
    job_id: str,
    after_seq: Optional[int] = None,
    manager: JobManager = Depends(job_manager_from_request),
):
    manager._get(job_id)
    logs = JobLogRepository(manager.job_repository.database).list(job_id, after_seq)
    return [log.model_dump(mode="json") for log in logs]


def request_database():
    from app.main import get_database
    return get_database()


@router.get("/modules", response_model=list[ModuleResponse])
def list_modules(
    status: Optional[str] = None,
    module_key: Optional[str] = None,
    repository: ModuleRepository = Depends(module_repository_from_request),
):
    return [ModuleResponse.model_validate(module.model_dump(mode="json")) for module in repository.list(status, module_key)]


@router.post("/modules", response_model=ModuleResponse)
def create_module(
    payload: ModuleCreateRequest,
    repository: ModuleRepository = Depends(module_repository_from_request),
):
    now = datetime.now(timezone.utc)
    module_id = f"module_{now.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    module = ModuleValidation.validate_and_build(
        payload,
        module_id=module_id,
        created_at=now,
        updated_at=now,
        existing=repository.get_by_key(payload.module_key),
    )
    repository.create(module)
    return ModuleResponse.model_validate(module.model_dump(mode="json"))


@router.get("/modules/{module_id}", response_model=ModuleResponse)
def get_module(
    module_id: str,
    repository: ModuleRepository = Depends(module_repository_from_request),
):
    module = repository.get(module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")
    return ModuleResponse.model_validate(module.model_dump(mode="json"))


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
def update_module(
    module_id: str,
    payload: ModuleUpdateRequest,
    repository: ModuleRepository = Depends(module_repository_from_request),
):
    existing = repository.get(module_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="module not found")
    now = datetime.now(timezone.utc)
    module = ModuleValidation.validate_and_update(existing, payload, now, repository)
    repository.update(module)
    return ModuleResponse.model_validate(module.model_dump(mode="json"))


@router.get("/modules/{module_id}/services", response_model=list[ModuleCompatibilityResponse])
def module_compatible_services(
    module_id: str,
    repository: ModuleRepository = Depends(module_repository_from_request),
    registry: ServiceRegistry = Depends(service_registry_from_request),
):
    module = repository.get(module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")
    return ModuleValidation.compatibility_list(module, registry.list())
