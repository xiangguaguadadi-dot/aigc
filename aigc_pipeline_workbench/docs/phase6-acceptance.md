# Phase 6 Acceptance Report

Last verified: 2026-09-13 15:31:09 +0800

# Acceptance Decision

**Phase 6 - TECHNICAL PASS**

Built-in Frontend Demo is available for browser-side UI and 3D viewer checks. The demo job does not require an external GPU service.

Service and Recent Job selection were confirmed working by the user. WebGL rotation, zoom, and pan still require manual confirmation.


# 1. Scope

Phase 6 target: Single-Module Debugging Workbench MVP.

```text
Image -> Job -> Logs -> GLB -> Interactive 3D Preview
```

The baseline scope is documented in `docs/backend-mvp-baseline.md`.

# 2. Final Architecture

```text
Frontend Debugger
   ↓ HTTP
Main Backend / Control Plane
   ├─ ServiceRegistry
   ├─ JobManager
   ├─ GpuServiceClient
   └─ ArtifactService
        ├─ SQLite
        └─ LocalArtifactStore
   ↓ HTTP / GPU Contract v1
GPU Microservices
   ├─ mock-fast
   └─ mock-slow
   ↓ HTTP Artifact Upload
Main Backend Artifact API
```

边界不变：

- Frontend 只访问 Main Backend。
- Main Backend 是唯一 Control Plane。
- GPU Service 是独立 Compute Plane。
- Artifact 通过 Artifact API 交换。
- 内部文件路径和 `storage_key` 不跨边界。

# 3. Backend Additions

## 3.1 Minimal Job List API

新增：

```text
GET /api/v1/jobsservice_id=&status=&limit=
```

用途：

- Frontend 加载 recent jobs。
- 支持 optional service filter。
- 支持 optional status filter。
- 支持 simple limit。

这不是 pagination system，也没有引入 cursor 或 scheduler。

相关实现：

| 文件 | 职责 |
| --- | --- |
| `backend/app/api/public_api.py` | 暴露 `GET /api/v1/jobs`。 |
| `backend/app/repositories/job_repository.py` | 增加 minimal query 能力。 |
| `backend/tests/test_phase6_frontend_api.py` | 覆盖 list、filter、invalid status 和排序。 |

新增测试：

```text
test_job_list_returns_recent_jobs_desc
test_job_list_filters_by_service_and_status
test_job_list_rejects_invalid_status
```

# 4. Mock GPU Service Additions

`mock-fast` 与 `mock-slow` 的成功任务现在输出两个 artifacts：

```text
report
glb
```

GLB 是 mock binary payload，用于验证 Frontend 3D preview 链路；它不是真实 mesh 算法结果。

相关实现：

| 文件 | 职责 |
| --- | --- |
| `mock_services/mock_services/base.py` | 统一模拟执行、日志、状态、输出 artifact 上传。 |
| `mock_services/mock_services/artifact_client.py` | 通过 Main Backend Artifact API 上传文件。 |
| `mock_services/mock_services/fast_service.py` | 快速成功服务。 |
| `mock_services/mock_services/slow_service.py` | 慢速、progress、cancel、随机失败服务。 |

Mock 测试结果：

```text
5 passed
```

# 5. Frontend MVP

## 5.1 Technology

```text
React 19
TypeScript
Vite 7
Three.js 0.186
```

没有引入 router、state library、UI framework 或 WebSocket。当前规模不需要。

## 5.2 Files and Responsibilities

| File | Responsibility |
| --- | --- |
| `frontend/src/api/types.ts` | Public API 的 typed view：Service、Job、Artifact、Log、Parameter。 |
| `frontend/src/api/client.ts` | 封装所有 Frontend → Main Backend HTTP 调用和错误提取。 |
| `frontend/src/hooks/useJobPolling.ts` | 对 active Job 做 1 秒 polling，终态停止。 |
| `frontend/src/page/workbench/ServiceWorkbench.tsx` | 主工作台：Service selection、input、parameters、run/cancel/rerun、Job detail。 |
| `frontend/src/components/ParameterForm.tsx` | 根据 `parameter_schema` 渲染 string、integer、number、boolean、enum。 |
| `frontend/src/components/LogView.tsx` | 展示 seq、source、level、message，自动滚动，显示 Job error。 |
| `frontend/src/components/ArtifactPreview.tsx` | 展示 image artifact，隐藏 GLB，避免重复渲染。 |
| `frontend/src/components/MeshPreview.tsx` | Three.js GLB viewer。 |
| `frontend/src/App.tsx` | 指向 Service Workbench。 |
| `frontend/src/main.tsx` | React entrypoint。 |
| `frontend/src/vite-env.d.ts` | Vite client types。 |
| `frontend/src/styles.css` | Workbench 布局、状态、日志、输出和 3D preview 样式。 |
| `frontend/index.html` | Frontend entry HTML。 |
| `frontend/vite.config.ts` | 前端本地 Vite 配置，解决仓库根配置在当前 WSL/subst 环境不可稳定加载的问题。 |

## 5.3 User Flow

### Service selection

Frontend 调用：

```text
GET /api/v1/services
```

展示：

- name；
- status；
- module_key；
- service_id；
- version；
- input types；
- output types。

### Input upload

用户选择文件后 Frontend 调用：

```text
POST /api/v1/artifacts
```

上传成功后得到：

```text
artifact_id
type
name
uri
```

### Parameter editing

Frontend 使用 service metadata 的 `parameter_schema` 渲染表单，不硬编码任何 algorithm field。

### Job creation

Frontend 调用：

```text
POST /api/v1/jobs
```

带：

```text
service_id
parameters
input_artifacts
```

### Status / progress / logs polling

活跃 Job 使用：

```text
GET /api/v1/jobs/{job_id}
GET /api/v1/jobs/{job_id}/logsafter_seq=...
```

终态停止轮询。

### Output artifacts

Job succeeded 后展示：

- report；
- GLB。

GLB 下载地址为：

```text
GET /api/v1/artifacts/{artifact_id}/file
```

### Cancel / rerun

Cancel 调用：

```text
POST /api/v1/jobs/{job_id}/cancel
```

Rerun 调用：

```text
POST /api/v1/jobs/{job_id}/rerun
```

Rerun 创建新 `job_id`。

## 5.4 Interactive 3D Preview

`MeshPreview` 使用 Three.js 实现：

- GLTFLoader 加载 Backend artifact URL；
- OrbitControls 支持拖拽旋转、滚轮缩放、右键平移；
- 自动根据 GLB bounding box 居中和缩放；
- Reset View；
- 组件卸载时 dispose renderer / controls；
- ResizeObserver 自适应。

## 5.5 Runbook

本地启动三个独立进程：

```bash
scripts/start_phase6.sh
```

启动 Frontend：

```bash
npm run dev
```

# 6. Real HTTP E2E

## 6.1 Independent processes

真实 smoke test 中，以下三个服务以独立进程运行：

```text
Main Backend :8000
mock-fast   :8101
mock-slow   :8102
```

本地可复现启动脚本：

```bash
scripts/start_phase6.sh
```

脚本使用独立 runtime 目录，不污染仓库内的 `backend/data`。启动后可运行：

```bash
uv run --project mock_services python scripts/e2e_phase6_http.py
```

验证使用真实 HTTP，不是 TestClient / ASGI transport。

## 6.2 Latest clean restart verification

```text
service_id:
  service_20260913030141_5094ea3b

input artifact_id:
  artifact_7b15fce77d2e4ebbaf8be8d0ccceef0c

job_id:
  job_20260913030141_46644ada

transitions:
  queued -> running -> succeeded

progress:
  100

log seq:
  0 -> 1 -> 2

glb_artifact_id:
  artifact_1ba47bd23f4c443797e462aa57b53106

glb_bytes:
  956

command result:
  PHASE 6 HTTP E2E PASS
```

Smoke lifecycle verification also passed on the same runtime:

```text
SMOKE TEST PASS
fast lifecycle:
  queued -> running -> succeeded
logs:
  seq 0 -> 1 -> 2
slow cancel:
  queued -> running -> cancelling -> cancelled
```

Force-failure verification passed:

```text
force_failure = true
initial lifecycle:
  queued -> running -> failed
rerun lifecycle:
  queued -> running -> failed
```

GLB fixture verification:

```text
GLB bytes: 956
GLB version: 2
Header validation: PASS
Node GLTFLoader parse: PASS
Mesh count: 1
Bounding box: (-1, -1, -1) to (1, 1, 1)
```

# 7. Frontend HTTP Verification

已验证：

```text
TypeScript check:
  tsc --noEmit passed

Frontend production build:
  vite build passed
```

已通过真实 HTTP 验证的链路：

```text
Image → Job → Logs → GLB → GLB artifact download
```

专用 Phase 6 HTTP E2E 脚本 `scripts/e2e_phase6_http.py` 已验证：

```text
service_id:
  service_20260912133734_3b9414da

input artifact_id:
  artifact_c25adb8ea06345d5881ad14fee5d802a

job_id:
  job_20260912133734_c24a3232

transitions:
  queued → running → succeeded

progress:
  100

log seq:
  0 → 1 → 2

glb_artifact_id:
  artifact_e4fb746f653944b7b3b599c5860280d5

glb_bytes:
  956
```

Three.js 是从下载的 GLB artifact URL 创建 viewer。该代码路径已完成类型检查和生产构建，但当前没有自动化浏览器测试断言 WebGL 场景的交互行为。

因此：

| 能力 | 状态 |
| --- | --- |
| Image upload | READY |
| Job creation / submit | READY |
| Status / progress polling | READY |
| Logs polling | READY |
| Report + GLB output | READY |
| GLB artifact HTTP download | READY |
| Three.js GLB viewer | CODE READY |
| Human interactive WebGL confirmation | NOT AUTOMATED |

# 8. Phase 6 Fixes

Phase 6 收尾阶段发现并修复：

| Bug | Cause | Fix | Verification |
| --- | --- | --- | --- |
| `vite build` 找不到 `frontend/index.html` | 根目录 Vite config 在当前 WSL UNC + subst 环境下不稳定。 | 新增 `frontend/vite.config.ts`，将 frontend root 显式限定在前端目录。 | `vite build passed` |
| PostCSS 解析 `package.json` 失败 | 根 `package.json` 带 UTF-8 BOM。 | 移除 BOM。 | `vite build passed` |
| Subst/UNC 环境下 symlink 解析导致路径错误 | Node `realpath` 把 `W:` 映射回 UNC 路径。 | Vite config 设置 `resolve.preserveSymlinks: true`。 | `vite build passed` |

除此之外，Phase 6 收尾没有发现其他代码 bug。

# 8.1 Later Frontend Runtime Fixes and Enhancements

| Issue | Cause | Fix | Verification |
| --- | --- | --- | --- |
| Frontend started with an empty Services list, so no Service could be selected. | No local GPU service was running, and `GET /api/v1/services` returned an empty list. | Auto-register a built-in `Built-in Frontend Demo` service during backend runtime initialization. | Services and Recent Jobs can be selected in the browser. |
| Root Vite dev server did not proxy `/api` requests. | The root `vite.config.ts` had no `/api` proxy configuration. | Add `/api -> http://127.0.0.1:8000`. | Vite dev-server `/api/v1/*` requests reach the backend JSON API. |
| `frontend/vite.config.ts` contained a UTF-8 BOM. | Node/Vite failed to parse the config. | Remove the BOM. | Vite dev config loads normally. |

Built-in Frontend Demo Job:

```text
GET /api/v1/jobs/demo
```

The endpoint creates a deterministic succeeded job with report and 956-byte GLB artifacts. It allows browser-side UI and 3D-viewer checks without an external GPU service.

# 9. Public API Used by Frontend

## Health

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/health` |

## Artifacts

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/artifacts` |
| `GET` | `/api/v1/artifacts/{artifact_id}` |
| `GET` | `/api/v1/artifacts/{artifact_id}/file` |

## Services

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/services` |
| `GET` | `/api/v1/services/{service_id}` |
| `POST` | `/api/v1/services/{service_id}/check` |

## Jobs

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/jobs` |
| `GET` | `/api/v1/jobs` |
| `GET` | `/api/v1/jobs/demo` |
| `GET` | `/api/v1/jobs/{job_id}` |
| `POST` | `/api/v1/jobs/{job_id}/cancel` |
| `POST` | `/api/v1/jobs/{job_id}/rerun` |
| `POST` | `/api/v1/jobs/{job_id}/sync` |
| `GET` | `/api/v1/jobs/{job_id}/logs` |

# 10. Test Matrix

| Category | Result |
| --- | --- |
| Backend repository / artifact tests | PASSED |
| Backend service registry tests | PASSED |
| Backend Job lifecycle / polling / cancel / rerun tests | PASSED |
| Backend state transition tests | PASSED |
| Backend restart recovery tests | PASSED |
| Backend Phase 6 Job list tests | PASSED |
| Mock Service tests | PASSED |
| Backend mypy | PASSED |
| Mock mypy | PASSED |
| Backend compileall | PASSED |
| TypeScript check | PASSED |
| Frontend production build | PASSED |
| Real HTTP backend + mock-fast + mock-slow smoke | PASSED |
| Real HTTP Phase 6 GLB E2E | PASSED |
| Force-failure rerun lifecycle | PASSED |

最终计数：

```text
backend pytest:
  42 passed

mock pytest:
  5 passed

backend mypy:
  Success: no issues found in 28 source files

mock mypy:
  Success: no issues found in 8 source files

TypeScript:
  tsc --noEmit passed

Frontend build:
  vite build passed

Real HTTP smoke:
  SMOKE TEST PASS
```

# 11. Known Limitations

## Frontend

- 没有自动化浏览器 E2E。
- 没有自动化断言 WebGL render。
- 没有 history filter UI，只使用 recent jobs。
- 没有 WebSocket / SSE，仍使用 polling。
- 没有持久化 UI state。
- 没有 accessibility audit。

## Backend / Runtime

- Restart recovery 仍是 PARTIAL，特别是 submitting 状态。
- 没有自动 timeout enforcement。
- 没有 service health background probe。
- Polling 连续 3 次失败后跳过。
- Job list 没有 cursor pagination。
- 没有 authentication。

## Deliberately Not Implemented

Phase 6 仍未引入：

- Workflow / DAG；
- Scheduler；
- Load balancing；
- Real GPU algorithms；
- Authentication；
- Object storage；
- Distributed queue；
- WebSocket / SSE；
- Kubernetes / Kafka / Redis / Celery / PostgreSQL；
- Service Mesh。

# 12. Final Decision

| Check | Result |
| --- | --- |
| Valid GLB v2 fixture (956 bytes) | PASS |
| GLTFLoader parses 1 non-empty Mesh | PASS |
| Viewer status and mesh-count observability | PASS |
| Camera fit and Reset View programmatic behavior | PASS |
| Rotation / zoom / pan | MANUAL CHECK REQUIRED |
| Image -> Job -> Logs -> GLB artifact HTTP E2E | PASS |
| Built-in Frontend Demo service and job | PASS |
| Frontend service / recent-job selection in browser | USER CONFIRMED |
| Force-failure deterministic job lifecycle and rerun | PASS |
| Backend + mock + frontend regression | PASS |
| Persistence across runtime restart | PASS |
| Public API boundary isolation | PASS |

# 13. Human Manual Check

**UI SELECTION: USER CONFIRMED.**

User confirmed that the current frontend behaves well after adding the built-in demo service and job. Service and Recent Job selection now work in the browser.

**WEBGL INTERACTION: PENDING.**

Open the debugger in a browser, select `Built-in Frontend Demo`, then select `job_frontend_demo`, and manually confirm the GLB viewer:

- Rotation: MANUAL CHECK REQUIRED
- Zoom: MANUAL CHECK REQUIRED
- Pan: MANUAL CHECK REQUIRED

Camera fit and Reset View are programmatically implemented and type-checked; browser rendering and interaction remain outside automated coverage.
