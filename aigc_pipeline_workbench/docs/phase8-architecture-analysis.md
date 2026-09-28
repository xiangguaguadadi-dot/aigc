# Phase 8 — Real GPU Algorithm Integration: Architecture Analysis

## 1. Repository Analysis: `aigc` (xiangguaguadadi-dot/aigc)

### 1.1 Structure

| Directory | Purpose | Relevance to Phase 8 |
|-----------|---------|----------------------|
| `01_TRELLIS2_core/` | TRELLIS.2 perception, reconstruction, physics, simulation pipeline | **Primary** — Image→3D core |
| `video_to_3d/` | Video-to-GLB pipeline (8 stages) | Secondary — future module |
| `simulation/` | PyBullet + Blender robot interaction | Future — downstream |
| `generate_3Dmodel/` | Single image to 3D (legacy toggle) | Overlaps with TRELLIS.2 |
| `03_3Dchannel/` | Tripo + Blender channel tool | External tooling |
| `02_ComfyUI_current/` | ComfyUI workflow integration | External tooling |

### 1.2 Current Execution Model

**TRELLIS.2 current flow (real A100):**

```
Gradio UI (app.py)
    → paramiko SSH to A100 cloud server (px-cloud2.matpool.com:28105)
    → SFTP upload image
    → SSH exec_command('python3 /tmp/demo_run.py', timeout=600)
        → Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
        → pipeline.cuda()
        → pipeline.run(image)
        → o_voxel.postprocess.to_glb(...)
        → glb.export(...)
    → SFTP download GLB
    → Gradio 3D preview
```

**Critical findings:**

| Issue | Detail |
|-------|--------|
| **Model loads every connection** | `from_pretrained()` + `cuda()` inside every SSH invocation — ~30s overhead |
| **No model persistence** | Each Gradio request re-downloads weights (~20GB) and reloads |
| **No job queue** | Concurrent Gradio requests → OOM |
| **No contract** | Uses Gradio + SSH, no `/v1` protocol |
| **Hardcoded credentials** | HOST/PORT/USER/PASSWORD in `app.py` — **SECURITY ACTION REQUIRED** |
| **Artifact boundary** | Local file paths used directly — `/tmp/demo_*.glb` |
| **No retry** | Single connection attempt, no backoff |
| **Hardcoded HF mirror** | `HF_ENDPOINT=https://hf-mirror.com` — fine for China |
| **No log streaming** | Stderr read after execution completes |
| **SSH timeout = 600s** | Single hard timeout, no heartbeat |

### 1.3 Algorithm ↔ Glue Separation

**Algorithm logic (should stay in service layer):**
- `Trellis2ImageTo3DPipeline.from_pretrained()` → `pipeline.run(image)` → mesh
- `o_voxel.postprocess.to_glb()` — GLB export with PBR textures
- EnvMap loading, mesh simplification, decimation

**Deployment glue (should be replaced by Contract v1 service):**
- Gradio UI (`gr.Blocks`, `gr.Image`, `gr.Model3D`)
- SSH paramiko connection management
- SFTP upload/download
- `exec_command` script generation (embedded Python in Python string)
- Temporary file management

### 1.4 Input / Output Specification

**Input:**
- Single RGB image (PIL Image, any format)
- Steps parameter (int, 4–20, default 12)

**Output:**
- GLB file with PBR textures (baseColor + metallic + roughness)
- Vertex count: ~500k after decimation
- File size: 5–15 MB typical
- Texture size: 2048×2048

**Model requirements:**
- NVIDIA A100 40GB (minimum)
- CUDA 12.1+
- Python 3.10+
- ~20GB model weights cache
- ~30s model load, ~60–120s inference (12 steps)

---

## 2. Runtime Architecture

### 2.1 RuntimeSpec

Introduced as part of Phase 8. Defined in `app/domain/models.py`:

```python
class RuntimeSpec(BaseModel):
    runtime_type: str       # "cpu" | "gpu" | "external"
    gpu_mode: str | None    # "dedicated" | "shared_allowed"
    min_vram_gb: float | None
    model_residency: str    # "persistent" | "on_demand"
    max_concurrency: int    # default 1
```

**Current usage:**
- Persisted as `runtime_spec_json` column in `modules` table
- Included in `ModuleDefinition`, `ModuleCreateRequest`, `ModuleUpdateRequest`, `ModuleResponse`
- Seeded for `image_to_3d` and `trellis_image_to_3d` modules
- Propagated through `extension.runtime_spec` in GPU Service `/v1/metadata`

### 2.2 Deployment Model for Heavy GPU Modules

```
1 GPU = 1 Service = 1 Model (persistent)
┌──────────────────────┐
│  TRELLIS Service     │
│  ┌────────────────┐  │
│  │ Model (A100)   │  │  ← loaded once at startup
│  │                │  │
│  │ Job1 → Job2 →  │  │  ← serial inference, max_concurrency=1
│  └────────────────┘  │
└──────────────────────┘
```

**Key constraint:** This applies to TRELLIS.2 specifically. The system does NOT hardcode `1 GPU = 1 Algorithm` as a permanent rule. Lightweight CPU, external API, or shared-GPU modules can use different RuntimeSpec values.

### 2.3 Model Lifecycle

| Phase | Action | Detail |
|-------|--------|--------|
| Startup | `load_model()` | `Trellis2ImageTo3DPipeline.from_pretrained()` + `cuda()` |
| Resident | stays in GPU | NO `from_pretrained()` between jobs |
| Per Job | `pipeline.run()` | Reuses loaded model weights |
| Shutdown | cleanup | Service termination releases GPU memory |

### 2.4 Concurrency

- `max_concurrency = 1` (enforced by async queue)
- Second job returns `HTTP 503 service busy`
- No GPU scheduler, no dynamic allocation

---

## 3. TRELLIS GPU Service

### 3.1 Implementation

Location: `services/trellis_service/app/main.py`

**Contract v1 endpoints:**

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /v1/health` | ✅ | Includes GPU info (name, vram, cuda version) |
| `GET /v1/metadata` | ✅ | Includes `extension.runtime_spec` |
| `POST /v1/jobs` | ✅ | Enforces max_concurrency, validates module_key |
| `GET /v1/jobs/{id}` | ✅ | Supports `log_after_seq` for incremental logs |
| `POST /v1/jobs/{id}/cancel` | ✅ | Best-effort cancel |

**Added for Phase 8:**
- `artifact_client.py` — retry wrapper (3 attempts, exponential backoff)
- `RuntimeSpec` in `/v1/metadata` extension field — enables frontend/backend to read constraints without hardcoding
- Input checksum verification (optional `sha256` field on artifact upload)

### 3.2 Model Loading

```python
def load_model():
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(CACHE_DIR)
    pipeline.low_vram = True
    pipeline.default_pipeline_type = "512"
    pipeline.cuda()
    # Pipeline stays resident in _pipeline global
```

Called once in `lifespan()` startup. Never called in `run_inference()`.

### 3.3 Job Execution

```python
async def _run_inference(job):
    # 1. Download input artifact from Main Backend
    input_bytes = await download_artifact(job.inputs[0].url)
    img = Image.open(BytesIO(input_bytes)).convert("RGB")

    # 2. Inference (reuses resident model)
    mesh = pipeline.run(img, ...)

    # 3. Export GLB
    glb = o_voxel.postprocess.to_glb(...)
    glb_bytes = export_to_bytes(glb)

    # 4. Upload output artifact to Main Backend
    await upload_artifact(create_url, job.job_id, glb_bytes, ...)

    # 5. Resident model stays in GPU — ready for next job
```

### 3.4 Artifact Flow

```
User uploads image → Main Backend Artifact API
    → artifact_id stored in SQLite
    → Job submitted to TRELLIS Service
        → TRELLIS downloads artifact via /api/v1/artifacts/{id}/file
        → Inference → GLB
        → TRELLIS uploads GLB via /api/v1/artifacts (Artifact API)
        → Main Backend stores GLB
    → Frontend downloads GLB via /api/v1/artifacts/{id}/file
    → MeshPreview (Three.js)
```

Key boundary: GPU Service never accesses SQLite or backend local paths. Artifact files stay behind Main Backend.

### 3.5 Retry Behavior

| Operation | Retries | Backoff | Details |
|-----------|---------|---------|---------|
| Artifact download | 3 | None (single GET) | Timeout 300s for large files |
| Artifact upload | 3 | None (single POST) | Timeout 60s for GLB |

No S3, multipart, quota, or retention in Phase 8 scope.

---

## 4. Existing Artifact Reuse

### 4.1 Frontend Implementation (GenericModuleWorkbench.tsx)

The input section now shows both "Upload new file" and "Use Existing" buttons for each input slot:

```
┌───────────────────────────────────────────────┐
│  Inputs                                        │
│                                                │
│  image *                                       │
│  [Choose File] [Upload] [Use Existing]         │
│  ┌─────────────────────────────────────────┐   │
│  │ ▼ Existing Artifacts from Recent Jobs   │   │
│  │   output_001.glb (from job_2026...)     │   │
│  │   scene_mesh.glb (from job_2026...)     │   │
│  └─────────────────────────────────────────┘   │
│  ✓ uploaded_artifact_id                        │
└───────────────────────────────────────────────┘
```

**Behavior:**
- Filters recent job output artifacts by slot type compatibility
- Clicking an existing artifact sets it as the input without re-uploading
- Uploaded state shows artifact name/ID
- This is manual chaining preparation — no automatic DAG, no dependsOn

### 4.2 What is NOT implemented

| Feature | Status | Reason |
|---------|--------|--------|
| WorkflowRun | ❌ | Explicitly deferred |
| WorkflowStep | ❌ | Explicitly deferred |
| dependsOn | ❌ | Explicitly deferred |
| Auto-trigger | ❌ | Explicitly deferred |
| DAG engine | ❌ | Explicitly deferred |
| Topological sort | ❌ | Explicitly deferred |

---

## 5. Security

**SECURITY ACTION REQUIRED** in the source repository:

The `app.py` in `01_TRELLIS2_core/` contains hardcoded SSH credentials:

```python
HOST = os.environ.get('A100_HOST', 'px-cloud2.matpool.com')
PORT = int(os.environ.get('A100_PORT', '28105'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')
```

The `SETUP_SERVER.md` contains plaintext password:

```
ssh -p 27258 root@px-cloud1.matpool.com
密码: 5ZPy](PPjow[KBa+
```

These have **not** been copied, used, or recorded in this codebase. The `services/trellis_service/` implementation uses environment variables only, with no hardcoded defaults for credentials.

---

## 6. Boundary Preservation

| Rule | Status | Evidence |
|------|--------|----------|
| Frontend only talks to Main Backend | ✅ | All API calls go through `/api/v1/...` |
| Main Backend owns orchestration state | ✅ | SQLite services/jobs/logs/artifacts |
| GPU Service owns execution | ✅ | Only pipeline.run() on service side |
| Contract v1 preserved | ✅ | All endpoints fully implemented |
| No filesystem paths cross boundaries | ✅ | Artifact API is sole exchange mechanism |
| job_id generated by Main Backend | ✅ | job_id passed to GPU Service |
| Cancel is best effort | ✅ | cancel_requested flag, no forced kill |
| Rerun creates new Job | ✅ | Unchanged from Phase 7 |
| storage_key never in Public API | ✅ | Artifact metadata returns uri not storage_key |
| No Workflow/DAG introduced | ✅ | Explicitly excluded |

---

## 7. Known Limitations

| Issue | Impact | Target |
|-------|--------|--------|
| No real A100 access to test inference | Cannot confirm model loading or inference time | Real GPU integration phase |
| No GPU scheduler | Manual service allocation only | Future |
| No automatic timeout enforcement | Long-running jobs may hang | Phase 8+ |
| Polling failure recovery is PARTIAL | submitting state lost on crash | Phase 8+ |
| No S3/MinIO | Local storage only | Deployment phase |
| No checksum verification on download | Silent corruption possible | Phase 8+ |
| No signed URLs | Artifact access goes through backend | Deployment phase |
