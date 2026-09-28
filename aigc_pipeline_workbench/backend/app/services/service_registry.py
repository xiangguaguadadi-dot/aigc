import logging
from datetime import datetime, timezone
from typing import Optional

from app.domain.enums import ArtifactType, ServiceStatus
from pydantic import HttpUrl

from app.domain.models import (
    AlgorithmService,
    GpuInfo,
    ServiceCapabilities,
)
from app.errors import AppError
from app.repositories.service_repository import ServiceRepository
from app.schemas.service import ServiceHealthResponse, ServiceMetadataResponse
from app.services.gpu_service_client import GpuServiceClient
from app.settings import Settings

logger = logging.getLogger("workbench.services")


class ServiceRegistry:
    def __init__(
        self,
        repository: ServiceRepository,
        client: GpuServiceClient,
        settings: Optional[Settings] = None,
    ):
        self.repository = repository
        self.client = client
        self.settings = settings or Settings()

    def register(self, name: str, base_url: str, instance_label: Optional[str] = None, enabled: bool = True) -> AlgorithmService:
        if not base_url.lower().startswith(("http://", "https://")):
            raise AppError.from_code("INVALID_REQUEST", "base_url must use http or https")
        now = datetime.now(timezone.utc)
        service_id = f"service_{now.strftime('%Y%m%d%H%M%S')}_{instance_label or 'instance'}"
        service = AlgorithmService(
            service_id=service_id,
            module_key="unknown",
            name=name,
            base_url=HttpUrl(base_url),
            instance_label=instance_label,
            enabled=enabled,
            status=ServiceStatus.UNKNOWN,
            version="unknown",
            capabilities=ServiceCapabilities(
                input_artifact_types=[ArtifactType.UNKNOWN],
                output_artifact_types=[ArtifactType.UNKNOWN],
            ),
            registered_at=now,
            updated_at=now,
        )
        created = self.repository.create(service)
        logger.info(
            "service registered",
            extra={
                "service_id": created.service_id,
                "module_key": created.module_key,
                "instance_label": created.instance_label,
            },
        )
        return created

    def get(self, service_id: str) -> AlgorithmService:
        service = self.repository.get(service_id)
        if service is None:
            raise AppError.from_code("JOB_NOT_FOUND", "service not found", {"service_id": service_id})
        return service

    def list(self) -> list[AlgorithmService]:
        return self.repository.list()

    async def check(self, service_id: str) -> AlgorithmService:
        service = self.get(service_id)
        try:
            health = await self.client.health(str(service.base_url))
            metadata = await self.client.metadata(str(service.base_url))
            if isinstance(health, dict):
                health = ServiceHealthResponse.model_validate(health)
            if isinstance(metadata, dict):
                metadata = ServiceMetadataResponse.model_validate(metadata)
            service = self._sync_metadata(service, health, metadata)
        except Exception as exc:
            service.status = ServiceStatus.OFFLINE
            service.last_checked_at = datetime.now(timezone.utc)
            service.last_error = str(exc)
            service.updated_at = datetime.now(timezone.utc)
            logger.warning(
                "service offline",
                extra={"service_id": service_id, "service_status": service.status.value},
            )
        else:
            logger.info(
                "service synchronized",
                extra={
                    "service_id": service_id,
                    "service_status": service.status.value,
                    "module_key": service.module_key,
                    "instance_label": service.instance_label,
                },
            )
        return self.repository.update(service)

    def _sync_metadata(
        self,
        service: AlgorithmService,
        health: ServiceHealthResponse,
        metadata: ServiceMetadataResponse,
    ) -> AlgorithmService:
        now = datetime.now(timezone.utc)
        service.module_key = metadata.module_key
        service.name = metadata.name or service.name
        service.version = metadata.version
        service.status = health.status
        service.gpu = health.gpu
        service.capabilities = ServiceCapabilities(
            input_artifact_types=[
                ArtifactType(value) for value in metadata.input_artifact_types
            ],
            output_artifact_types=[
                ArtifactType(value) for value in metadata.output_artifact_types
            ],
            parameter_schema=metadata.parameter_schema,
            supports_cancel=metadata.supports_cancel,
            supports_progress=metadata.supports_progress,
            supports_streaming_logs=False,
            estimated_duration_seconds=metadata.estimated_duration_seconds,
            max_concurrent_jobs=metadata.max_concurrent_jobs,
        )
        service.last_checked_at = now
        service.last_online_at = now if health.status == ServiceStatus.ONLINE else service.last_online_at
        service.last_error = None
        service.updated_at = now
        return service
