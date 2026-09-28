import json
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from app.domain.enums import LogLevel, LogSource
from app.domain.models import JobError, JobLog
from app.schemas.common import CONTRACT_VERSION
from app.schemas.job import JobStatusResponse
from app.schemas.service import ServiceHealthResponse, ServiceMetadataResponse
from app.settings import Settings


class GpuServiceClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()

    async def health(self, base_url: str) -> ServiceHealthResponse:
        response = await self._request("GET", base_url, "/v1/health")
        return ServiceHealthResponse.model_validate(response.json())

    async def metadata(self, base_url: str) -> ServiceMetadataResponse:
        response = await self._request("GET", base_url, "/v1/metadata")
        return ServiceMetadataResponse.model_validate(response.json())

    async def submit_job(
        self,
        base_url: str,
        job_id: str,
        module_key: str,
        inputs: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        contract_inputs = [
            {
                "artifact_id": item["artifact_id"],
                "type": item["type"],
                "name": item.get("name"),
                "url": item["uri"] if str(item["uri"]).startswith(("http://", "https://")) else f"{self.settings.control_plane_base_url.rstrip('/')}{item['uri']}",
            }
            for item in inputs
        ]
        response = await self._request(
            "POST",
            base_url,
            "/v1/jobs",
            payload={
                "contract_version": self.settings.contract_version,
                "job_id": job_id,
                "module_key": module_key,
                "inputs": contract_inputs,
                "parameters": parameters,
                "artifact_store": {
                    "create_artifact_url": f"{self.settings.control_plane_base_url.rstrip('/')}/api/v1/artifacts"
                },
            },
            timeout=self.settings.submit_timeout_seconds,
        )
        return response.json()

    async def job_status(
        self,
        base_url: str,
        job_id: str,
        log_after_seq: int = -1,
    ) -> JobStatusResponse:
        response = await self._request(
            "GET",
            base_url,
            f"/v1/jobs/{job_id}",
            params={"log_after_seq": log_after_seq},
            timeout=self.settings.poll_timeout_seconds,
        )
        return JobStatusResponse.model_validate(response.json())

    async def cancel_job(self, base_url: str, job_id: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            base_url,
            f"/v1/jobs/{job_id}/cancel",
            timeout=self.settings.submit_timeout_seconds,
        )
        return response.json()

    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> httpx.Response:
        url = f"{base_url.rstrip('/')}{path}"
        body = None if payload is None else json.dumps(payload)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, content=body, headers={"Content-Type": "application/json"}, params=params)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"GPU service request failed: {url}") from exc
        if response.status_code >= 400:
            raise RuntimeError(self._error_message(response))
        return response

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return f"GPU service error: HTTP {response.status_code}"
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            return error.get("message") or f"GPU service error: HTTP {response.status_code}"
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            return detail.get("message") or f"GPU service error: HTTP {response.status_code}"
        if isinstance(detail, str):
            return detail
        return f"GPU service error: HTTP {response.status_code}"
