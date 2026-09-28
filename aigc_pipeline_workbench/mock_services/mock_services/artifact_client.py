import httpx

from .settings import MockSettings


async def upload_artifact(
    settings: MockSettings,
    job_id: str,
    content: bytes,
    filename: str = "mock_report.json",
    artifact_type: str = "report",
):
    data = {
        "artifact_type": artifact_type,
        "job_id": job_id,
        "retention": "result",
    }
    mime_type = {
        "report": "application/json",
        "glb": "model/gltf-binary",
    }.get(artifact_type, "application/octet-stream")
    files = {"file": (filename, content, mime_type)}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{settings.control_plane_base_url.rstrip('/')}/api/v1/artifacts",
            data=data,
            files=files,
        )
        response.raise_for_status()
        return response.json()
