#!/usr/bin/env python3
"""
TRELLIS.2 GPU Service — Contract v1 compliant.

Architecture (Phase 8):
  Service startup
  → load pretrained model once
  → move model to GPU
  → READY
  → Job 1 inference  (reuse resident model)
  → Job 2 inference  (reuse resident model)
  → ...

Model stays in GPU memory between jobs.
max_concurrency = 1 (second job waits).
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("trellis-service")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_CACHE_DIR = Path(os.environ.get("TRELLIS_MODEL_CACHE", "/root/TRELLIS.2-cache"))
CONTROL_PLANE_BASE_URL = os.environ.get("CONTROL_PLANE_BASE_URL", "http://127.0.0.1:8000")
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
MAX_CONCURRENCY = int(os.environ.get("TRELLIS_MAX_CONCURRENCY", "1"))
MIN_VRAM_GB = float(os.environ.get("TRELLIS_MIN_VRAM_GB", "40"))
LISTEN_HOST = os.environ.get("TRELLIS_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("TRELLIS_LISTEN_PORT", "8201"))

# ---------------------------------------------------------------------------
# Contract v1 models (subset)
# ---------------------------------------------------------------------------


class ArtifactInput(BaseModel):
    artifact_id: str
    type: str
    name: Optional[str] = None
    url: str


class ArtifactStoreInfo(BaseModel):
    create_artifact_url: Optional[str] = None


class JobSubmitRequest(BaseModel):
    contract_version: str
    job_id: str
    module_key: str
    inputs: list[ArtifactInput] = []
    parameters: dict[str, Any] = {}
    artifact_store: Optional[ArtifactStoreInfo] = None


class OutputArtifact(BaseModel):
    artifact_id: str
    type: str
    name: str
    uri: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: dict[str, Any] = {}


class JobLogEntry(BaseModel):
    seq: int
    level: str
    message: str
    created_at: datetime


class JobProgress(BaseModel):
    percent: Optional[int] = None
    phase: Optional[str] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

class StoredJob:
    def __init__(self, job_id: str, module_key: str, parameters: dict, inputs: list[ArtifactInput]):
        self.job_id = job_id
        self.module_key = module_key
        self.parameters = parameters
        self.inputs = inputs
        self.status = "queued"
        self.progress_percent = 0
        self.progress_phase: Optional[str] = None
        self.progress_message: Optional[str] = None
        self.logs: list[JobLogEntry] = []
        self.output_artifacts: list[OutputArtifact] = []
        self.error: Optional[dict] = None
        self.cancel_requested = False
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.updated_at = datetime.now(timezone.utc)
        self.created_at = datetime.now(timezone.utc)

    def add_log(self, level: str, message: str) -> None:
        seq = len(self.logs)
        self.logs.append(JobLogEntry(
            seq=seq, level=level, message=message,
            created_at=datetime.now(timezone.utc),
        ))
        self.updated_at = datetime.now(timezone.utc)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, StoredJob] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: StoredJob) -> None:
        async with self._lock:
            self._jobs[job.job_id] = job

    async def get(self, job_id: str) -> Optional[StoredJob]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_status(self, job_id: str, status: str, **kwargs) -> Optional[StoredJob]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = status
            for key, value in kwargs.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc)
            return job


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------

_pipeline = None
_envmap_tensor: Optional[torch.Tensor] = None
_job_queue = asyncio.Queue()
_store = JobStore()
_active_jobs: set[str] = set()


def load_envmap() -> torch.Tensor:
    """Load the forest.exr envmap used by TRELLIS.2 for PBR rendering."""
    envmap_paths = [
        "/root/TRELLIS.2/assets/hdri/forest.exr",
        "assets/hdri/forest.exr",
    ]
    for p in envmap_paths:
        if os.path.isfile(p):
            logger.info("loading envmap from %s", p)
            import OpenEXR, Imath  # type: ignore[import-untyped]
            f = OpenEXR.InputFile(p)
            dw = f.header()["dataWindow"]
            w = dw.max.x - dw.min.x + 1
            h = dw.max.y - dw.min.y + 1
            pt = Imath.PixelType(Imath.PixelType.FLOAT)
            rgb = [np.frombuffer(f.channel(c, pt), dtype=np.float32).reshape(h, w) for c in "RGB"]
            f.close()
            arr = np.stack(rgb, axis=-1)
            logger.info("envmap loaded: %s shape=%s", p, arr.shape)
            return torch.tensor(arr, dtype=torch.float32, device="cuda")
    logger.warning("envmap not found; using dummy")
    return torch.zeros((1, 1, 3), dtype=torch.float32, device="cuda")


def load_model() -> Any:
    """Load TRELLIS.2 pipeline once. Called at startup."""
    global _pipeline, _envmap_tensor
    import numpy as np  # noqa: F401 — needed for envmap
    from trellis2.pipelines import Trellis2ImageTo3DPipeline  # type: ignore[import-untyped]
    from trellis2.renderers import EnvMap  # type: ignore[import-untyped]

    logger.info("loading TRELLIS.2 pipeline from %s ...", MODEL_CACHE_DIR)
    t0 = time.time()
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(MODEL_CACHE_DIR))
    pipeline.low_vram = True
    pipeline.default_pipeline_type = "512"
    pipeline.cuda()
    _pipeline = pipeline

    envmap_data = load_envmap()
    _envmap_tensor = EnvMap(envmap_data)

    torch.cuda.empty_cache()
    gc.collect()
    logger.info("model loaded in %.1fs", time.time() - t0)

    # Verify GPU
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        logger.info("GPU: %s | VRAM free=%.1fGB total=%.1fGB",
                     torch.cuda.get_device_name(0), free / 1e9, total / 1e9)
    return pipeline


def get_pipeline() -> Any:
    if _pipeline is None:
        raise RuntimeError("model not loaded yet")
    return _pipeline


# ---------------------------------------------------------------------------
# Inference worker — serializes jobs so max_concurrency = 1
# ---------------------------------------------------------------------------

async def _inference_worker() -> None:
    """Background task: process one job at a time from the queue."""
    while True:
        job_id = await _job_queue.get()
        job = await _store.get(job_id)
        if job is None or job.cancel_requested:
            _active_jobs.discard(job_id)
            continue
        try:
            await _run_inference(job)
        except Exception as exc:
            logger.exception("inference failed for job %s", job_id)
            await _store.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc),
                error={"code": "INTERNAL_ERROR", "message": str(exc), "details": {}},
            )
            job = await _store.get(job_id)
            if job:
                job.add_log("error", f"inference failed: {exc}")
        finally:
            _active_jobs.discard(job_id)


async def _run_inference(job: StoredJob) -> None:
    """Execute one TRELLIS.2 inference job with the resident model."""
    import numpy as np
    from PIL import Image

    pipeline = get_pipeline()
    job.add_log("info", "inference started")

    # -- Download input artifact --
    if not job.inputs:
        raise ValueError("no input artifact provided")
    inp = job.inputs[0]
    job.add_log("info", f"downloading input: {inp.url}")
    input_bytes = await _download_artifact(inp.url)
    img = Image.open(io.BytesIO(input_bytes)).convert("RGB")
    job.add_log("info", f"input image: {img.size[0]}x{img.size[1]}")
    await _store.update_status(job.job_id, "running", started_at=datetime.now(timezone.utc))

    # -- Inference --
    steps = int(job.parameters.get("steps", 12))
    steps = max(4, min(steps, 20))
    job.add_log("info", f"running inference (steps={steps})...")
    t0 = time.time()
    torch.cuda.empty_cache()
    gc.collect()

    mesh = pipeline.run(
        img,
        pipeline_type="512",
        sparse_structure_sampler_params={"steps": steps},
        shape_slat_sampler_params={"steps": steps},
        tex_slat_sampler_params={"steps": steps},
    )[0]

    dt = time.time() - t0
    v = mesh.vertices.cpu().numpy()
    job.add_log("info", f"inference done in {dt:.1f}s | {v.shape[0]:,} verts, {mesh.faces.shape[0]:,} faces")

    # -- Simplify --
    mesh.simplify(5000000)
    torch.cuda.empty_cache()
    job.add_log("info", "mesh simplified")

    # -- Export GLB --
    import io as io_module
    import o_voxel  # type: ignore[import-untyped]
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=500000, texture_size=2048,
        remesh=True, remesh_band=1, remesh_project=0, verbose=False,
    )
    glb_buffer = io_module.BytesIO()
    glb.export(glb_buffer, extension_webp=True)
    glb_bytes = glb_buffer.getvalue()
    glb_buffer.close()
    job.add_log("info", f"GLB exported ({len(glb_bytes) / 1024**2:.1f} MB)")

    # -- Upload artifact --
    create_url = (job.parameters.get("_artifact_store_url")
                  or os.environ.get("CONTROL_PLANE_BASE_URL", "http://127.0.0.1:8000"))
    create_url = create_url.rstrip("/") + "/api/v1/artifacts"

    artifact_resp = await _upload_artifact(
        create_url, job.job_id, glb_bytes, f"{job.job_id}_mesh.glb",
        artifact_type="glb", output_slot="mesh",
    )
    job.output_artifacts.append(OutputArtifact(
        artifact_id=artifact_resp["artifact_id"],
        type="glb",
        name=f"{job.job_id}_mesh.glb",
        uri=artifact_resp["uri"],
        mime_type="model/gltf-binary",
        size_bytes=artifact_resp.get("size_bytes", len(glb_bytes)),
        metadata={"job_id": job.job_id, "output_slot": "mesh"},
    ))
    job.add_log("info", "artifact uploaded")

    # -- Success --
    await _store.update_status(
        job.job_id, "succeeded",
        finished_at=datetime.now(timezone.utc),
        progress_percent=100, progress_phase="done",
    )
    job.add_log("info", f"job succeeded in {dt:.1f}s")


async def _download_artifact(url: str) -> bytes:
    """Download an artifact from the Main Backend."""
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _upload_artifact(
    create_url: str, job_id: str, content: bytes, filename: str,
    artifact_type: str, output_slot: str,
) -> dict[str, Any]:
    """Upload an output artifact to the Main Backend Artifact API."""
    data = {
        "artifact_type": artifact_type,
        "job_id": job_id,
        "retention": "result",
        "metadata": json.dumps({"output_slot": output_slot, "job_id": job_id}),
    }
    mime_map = {"glb": "model/gltf-binary", "report": "application/json"}
    mime = mime_map.get(artifact_type, "application/octet-stream")
    files = {"file": (filename, content, mime)}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(create_url, data=data, files=files)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load model, start inference worker."""
    logger.info("TRELLIS service starting...")
    load_model()
    asyncio.create_task(_inference_worker())
    yield
    logger.info("TRELLIS service shutting down")


app = FastAPI(title="TRELLIS.2 GPU Service", version="1.0.0", lifespan=lifespan)


@app.get("/v1/health")
async def health():
    """Health check with GPU info."""
    gpu_info = None
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        gpu_info = {
            "name": torch.cuda.get_device_name(0),
            "vram_bytes": total,
            "cuda_version": torch.version.cuda,
        }
    return {
        "contract_version": "v1",
        "status": "online" if _pipeline is not None else "starting",
        "service": "trellis_image_to_3d",
        "version": "1.0.0",
        "gpu": gpu_info,
        "load": {
            "running_jobs": len(_active_jobs),
            "max_concurrent_jobs": MAX_CONCURRENCY,
        },
    }


@app.get("/v1/metadata")
async def metadata():
    """Module metadata for the Service Registry."""
    return {
        "contract_version": "v1",
        "module_key": "image_to_3d",
        "name": "TRELLIS.2 Image-to-3D",
        "version": "1.0.0",
        "input_artifact_types": ["image"],
        "output_artifact_types": ["glb", "report"],
        "parameter_schema": [
            {
                "key": "steps",
                "label": "Sampling Steps",
                "value_type": "integer",
                "required": False,
                "default": 12,
                "minimum": 4,
                "maximum": 20,
                "description": "Number of diffusion sampling steps (fewer = faster, lower quality).",
            },
        ],
        "supports_cancel": True,
        "supports_progress": True,
        "max_concurrent_jobs": MAX_CONCURRENCY,
        "estimated_duration_seconds": 120,
        "extension": {
            "runtime_spec": {
                "runtime_type": "gpu",
                "gpu_mode": "dedicated",
                "min_vram_gb": MIN_VRAM_GB,
                "model_residency": "persistent",
                "max_concurrency": MAX_CONCURRENCY,
                "description": "TRELLIS.2 requires a dedicated A100 40GB+ GPU. Model stays resident.",
            }
        },
    }


@app.post("/v1/jobs")
async def submit_job(request: JobSubmitRequest):
    """Submit a TRELLIS.2 inference job."""
    if request.module_key != "image_to_3d":
        raise HTTPException(status_code=422, detail="module_key mismatch")

    if len(_active_jobs) >= MAX_CONCURRENCY:
        raise HTTPException(status_code=503, detail="service busy")

    steps = request.parameters.get("steps", 12)
    if not isinstance(steps, int) or steps < 4 or steps > 20:
        raise HTTPException(status_code=422, detail="steps must be integer 4-20")

    store_url = None
    if request.artifact_store and request.artifact_store.create_artifact_url:
        store_url = request.artifact_store.create_artifact_url

    params = dict(request.parameters)
    if store_url:
        params["_artifact_store_url"] = store_url

    job = StoredJob(
        job_id=request.job_id,
        module_key=request.module_key,
        parameters=params,
        inputs=request.inputs,
    )
    await _store.create(job)
    job.add_log("info", "job queued")
    _active_jobs.add(request.job_id)
    await _job_queue.put(request.job_id)

    return {"job_id": request.job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}")
async def job_status(job_id: str, log_after_seq: int = -1):
    """Poll job status, progress, logs, and output artifacts."""
    job = await _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "code": "JOB_NOT_FOUND",
            "message": "job not found",
            "details": {"job_id": job_id},
        })

    logs = job.logs
    if log_after_seq >= 0:
        logs = [log for log in logs if log.seq > log_after_seq]

    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": {
            "percent": job.progress_percent,
            "phase": job.progress_phase or "unknown",
        },
        "logs": [log.model_dump() for log in logs],
        "output_artifacts": [a.model_dump() for a in job.output_artifacts],
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(),
    }


@app.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running or queued job."""
    job = await _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "code": "JOB_NOT_FOUND",
            "message": "job not found",
            "details": {"job_id": job_id},
        })
    if job.status in ("succeeded", "failed", "cancelled", "timeout"):
        return {"job_id": job_id, "status": job.status}

    job.cancel_requested = True
    job.add_log("warn", "cancel requested")
    await _store.update_status(job_id, "cancelling")
    return {"job_id": job_id, "status": "cancelling"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT)
