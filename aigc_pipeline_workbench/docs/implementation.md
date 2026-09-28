# Implementation Record

本文档记录各阶段实现结果。完整架构与协议的权威来源是 [`mvp-architecture.md`](mvp-architecture.md)。

后续每个 Phase 的实现情况、文件变更、验证结果和未完成范围都会追加到本文档，方便随时查看。

## Phase 状态总览

| Phase | 内容 | 状态 | 记录 |
| --- | --- | --- | --- |
| Phase 1 | 核心领域模型与 GPU Service Contract v1 | Completed | [Phase 1](#phase-1协议与核心领域模型) |
| Phase 2 | SQLite State Store 与 LocalArtifactStore | Completed | [Phase 2](#phase-2sqlite-与-localartifactstore) |
| Phase 3 | Mock GPU Service | Completed | [Phase 3](#phase-3mock-gpu-service) |
| Phase 4 | Service Registry + Job Manager | Completed | 本节 Phase 4 |
| Phase 5 | E2E Integration & Runtime Hardening | Completed | 本节 Phase 5 |
| Phase 6 | Frontend MVP | Completed | 本节 Phase 6 |
| Phase 7 | Module Studio & Generic Workbench | Completed | 本节 Phase 7 |
| Phase 8 | Real GPU Algorithm Integration (RuntimeSpec + TRELLIS Service + Manual Chaining) | TECHNICAL READY | 本节 Phase 8 |
| Phase 9 | Workflow / Pipeline | Deferred | - |

# Phase 1：协议与核心领域模型

## 实现范围

Phase 1 只实现数据契约，不实现数据库、服务注册、任务调度、文件存储或 Mock GPU Service。

## 代码结构

```text
backend/
  pyproject.toml
  app/
    main.py
    domain/
      enums.py
      models.py
    schemas/
      common.py
      service.py
      job.py
  tests/
    test_models.py
    test_contracts.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `app/domain/enums.py` | 状态、类型、错误码、日志级别等核心枚举 |
| `app/domain/models.py` | 与持久化无关的核心领域模型 |
| `app/schemas/common.py` | Contract version、统一错误、基础 artifact 协议模型 |
| `app/schemas/service.py` | GPU Service health / metadata schema |
| `app/schemas/job.py` | GPU Service job submit / status / cancel schema |

## 核心枚举

### `JobStatus`

严格遵循架构约定：

```text
created
submitting
submitted
queued
running
cancelling
cancelled
succeeded
failed
timeout
submit_failed
```

### `ArtifactType`

```text
image
mask
video
mesh
glb
texture
point_cloud
physics_asset
physics_scene
trajectory
report
log_file
unknown
```

### 其他核心枚举

```text
ArtifactRetention = temporary | result
ArtifactVisibility = public | internal | temporary
LogLevel = debug | info | warn | error | stdout | stderr
LogSource = service | orchestrator
ParameterValueType = string | number | integer | boolean | enum | json
ServiceStatus = online | offline | degraded | busy | unknown
```

## 核心领域模型

### `AlgorithmService`

```ts
AlgorithmService {
  service_id
  module_key
  name
  base_url
  status
  version
  gpu?
  capabilities
  registered_at
  updated_at
  last_checked_at?
  last_online_at?
  last_error?
}
```

### `ServiceCapabilities`

```ts
ServiceCapabilities {
  input_artifact_types
  output_artifact_types
  parameter_schema
  supports_cancel
  supports_progress
  supports_streaming_logs
  estimated_duration_seconds?
  max_concurrent_jobs?
}
```

### `Job`

```ts
Job {
  job_id
  run_id?
  service_id
  module_key
  status
  parameters
  input_artifacts
  output_artifacts
  progress?
  error?
  created_at
  submitted_at?
  started_at?
  finished_at?
  updated_at
  rerun_of_job_id?
  last_synced_at?
  last_sync_error?
  consecutive_poll_failures
}
```

### `Artifact` 与 `ArtifactRef`

```ts
Artifact {
  artifact_id
  run_id?
  job_id?
  type
  name
  mime_type?
  size_bytes?
  uri?
  storage_key?
  visibility
  retention
  created_at
  expires_at?
  metadata
}

ArtifactRef {
  artifact_id
  type
  name?
  uri?
}
```

规则：

- `artifact_id` 是系统稳定 ID；
- `storage_key` 只属于 backend / storage 内部；
- `ArtifactRef` 不携带本地路径；
- `Artifact` 可以在 backend 内部持有 `storage_key`。

### `JobLog`

```ts
JobLog {
  log_id
  job_id
  service_id?
  seq
  source
  level
  message
  created_at
}
```

`seq` 支持增量日志拉取。

### `ParameterDefinition`

```ts
ParameterDefinition {
  key
  label
  value_type
  required
  default?
  minimum?
  maximum?
  options?
  description?
}
```

## GPU Service Contract v1

Contract version 固定为 `v1`。

### 强制接口

```http
GET  /v1/health
GET  /v1/metadata
POST /v1/jobs
GET  /v1/jobs/{job_id}?log_after_seq=0
POST /v1/jobs/{job_id}/cancel
```

### `POST /v1/jobs`

```json
{
  "contract_version": "v1",
  "job_id": "job_001",
  "module_key": "image_segmentation",
  "inputs": [
    {
      "artifact_id": "artifact_001",
      "type": "image",
      "name": "input.png",
      "url": "https://example.com/artifacts/artifact_001/file"
    }
  ],
  "parameters": {
    "threshold": 0.62
  },
  "artifact_store": {
    "create_artifact_url": "https://example.com/internal/v1/artifacts"
  }
}
```

关键规则：

- `job_id` 由 Main Backend 生成并下发；
- 输入只使用 HTTP/HTTPS URL；
- 不能用普通文件路径构造 `ArtifactInput`；
- `parameters` 是统一 key/value 结构；
- 服务扩展信息放在 metadata 或 extension，不污染核心字段。

### `GET /v1/jobs/{job_id}`

```json
{
  "job_id": "job_001",
  "status": "running",
  "progress": {
    "percent": 45,
    "phase": "inference"
  },
  "logs": [
    {
      "seq": 1,
      "level": "info",
      "message": "loading model",
      "created_at": "2026-09-08T00:00:00Z"
    }
  ],
  "output_artifacts": [],
  "error": null,
  "updated_at": "2026-09-08T00:00:00Z"
}
```

成功时返回 `output_artifacts`：

```json
{
  "artifact_id": "artifact_mask_001",
  "type": "mask",
  "name": "object_001_mask.png",
  "uri": "https://example.com/artifacts/artifact_mask_001/file",
  "mime_type": "image/png",
  "size_bytes": 128443,
  "metadata": {
    "class": "bottle",
    "confidence": 0.91
  }
}
```

### `POST /v1/jobs/{job_id}/cancel`

返回：

```json
{
  "job_id": "job_001",
  "status": "cancelling"
}
```

或：

```json
{
  "job_id": "job_001",
  "status": "cancelled"
}
```

cancel 是 best effort。

### 统一错误结构

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "threshold must be between 0 and 1",
    "details": {
      "parameter": "threshold"
    }
  }
}
```

Phase 1 错误码：

```text
INVALID_REQUEST
INVALID_PARAMETER
JOB_NOT_FOUND
JOB_ALREADY_FINISHED
NOT_IMPLEMENTED
SERVICE_BUSY
INTERNAL_ERROR
```

### Phase 1 测试

Phase 1 覆盖了：

1. 合法 `Job` 创建；
2. 非法 `JobStatus` 拒绝；
3. number 参数的 min / max；
4. `ArtifactRef` 不暴露 storage path；
5. 最小 health response；
6. segmentation 风格 metadata；
7. running job response；
8. succeeded job response 与 output artifacts；
9. error response 序列化。

# Phase 2：SQLite 与 LocalArtifactStore

## 实现范围

Phase 2 只实现 Main Backend 最小状态存储和 Artifact 读写能力。

未实现：

- Service Registry 行为；
- Job Manager；
- GPU Service Client；
- 后台 polling；
- cancel / rerun；
- Mock GPU Service；
- Frontend；
- Workflow / Pipeline；
- S3 / MinIO；
- Redis / Celery / PostgreSQL。

## 代码结构

```text
backend/
  app/
    settings.py
    db.py
    errors.py
    api/
      public_api.py
    repositories/
      artifact_repository.py
    services/
      artifact_service.py
    storage/
      artifact_store.py
      local_artifact_store.py
    schemas/
      artifact.py
  tests/
    conftest.py
    test_artifacts.py
    test_restart.py
    test_failure_cleanup.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `settings.py` | 数据库路径、artifact root、版本号 |
| `db.py` | SQLite schema 和连接管理 |
| `errors.py` | 统一业务错误 |
| `repositories/artifact_repository.py` | Artifact SQL 持久化 |
| `storage/artifact_store.py` | ArtifactStore 抽象 |
| `storage/local_artifact_store.py` | 本地存储实现 |
| `services/artifact_service.py` | 上传与失败清理流程 |
| `api/public_api.py` | Health 与 Artifact HTTP API |
| `main.py` | 应用组装与统一异常处理 |

## SQLite Schema

Phase 2 已初始化四张表，但当前只有 `artifacts` repository 完整实现。

### `artifacts`

```sql
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT,
    job_id TEXT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    uri TEXT,
    storage_key TEXT,
    visibility TEXT NOT NULL,
    retention TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

### 其他表

```text
services
jobs
job_logs
```

这些表当前只完成 schema 初始化，行为逻辑留给后续阶段。

## ArtifactStore 抽象

```python
class ArtifactStore(ABC):
    def save(storage_key, content, mime_type=None) -> int
    def open(storage_key)
    def exists(storage_key) -> bool
    def delete(storage_key) -> bool
```

第一版实现是 `LocalArtifactStore`：

- root 由 `Settings.artifact_store_root` 配置；
- 只接受 `storage_key`；
- 内部负责解析真实路径；
- 拒绝绝对路径、`..` 和越界路径；
- 支持 save / open / exists / delete。

默认存储结构：

```text
data/artifacts/
  artifacts/
    <artifact_id>/
      <safe_filename>
```

`data/` 只在 backend 内部使用，不会通过 API 暴露真实路径。

## Artifact API

### `GET /api/v1/health`

响应：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "contract_version": "v1"
}
```

### `POST /api/v1/artifacts`

multipart/form-data 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | yes | 二进制文件 |
| `artifact_type` | yes | `ArtifactType` |
| `metadata` | no | JSON string |
| `run_id` | no | run ID |
| `job_id` | no | job ID |
| `retention` | no | `temporary` 或 `result` |

响应：

```json
{
  "artifact_id": "artifact_xxx",
  "type": "image",
  "name": "input.png",
  "mime_type": "image/png",
  "size_bytes": 128443,
  "uri": "/api/v1/artifacts/artifact_xxx/file"
}
```

### `GET /api/v1/artifacts/{artifact_id}`

返回 metadata：

```json
{
  "artifact_id": "artifact_xxx",
  "type": "image",
  "name": "input.png",
  "mime_type": "image/png",
  "size_bytes": 128443,
  "uri": "/api/v1/artifacts/artifact_xxx/file",
  "metadata": {
    "source": "test"
  }
}
```

不返回：

- `storage_key`；
- 真实本地路径；
- artifact root。

### `GET /api/v1/artifacts/{artifact_id}/file`

返回原始文件内容。

## Artifact 写入顺序与失败清理

当前上传顺序：

```text
生成 artifact_id
-> 清理并确定 safe filename
-> storage_key = artifacts/{artifact_id}/{safe_filename}
-> LocalArtifactStore.save()
-> 构造 Artifact metadata
-> ArtifactRepository.create()
-> 若数据库写入失败，删除已保存文件
```

这个顺序保证数据库中不会出现指向不存在文件的记录。MVP 不做分布式事务。

## 安全规则

- `filename` 只取 basename；
- 空文件名或 `.` / `..` 使用默认名；
- `storage_key` 拒绝绝对路径和 `..`；
- 解析后的路径必须位于 configured artifact root 内；
- Public API 不暴露 `storage_key` 和真实路径。

## 测试与验证

Phase 2 新增测试覆盖：

1. Artifact 上传成功；
2. metadata 写入 SQLite；
3. 文件确实保存在 LocalArtifactStore；
4. `GET metadata` 正常；
5. `GET file` 返回原内容；
6. 不存在 artifact 返回统一错误；
7. `artifact_id` 不暴露真实路径；
8. `storage_key` 不通过公共 API 暴露；
9. 非法文件名不能造成路径穿越；
10. 重启 repository / app 后 metadata 仍可读取；
11. 数据库失败时清理已保存文件。

最终验证结果：

```text
pytest: 24 passed
mypy:   Success: no issues found in 29 source files
compileall: passed
```

## 当前依赖

```toml
dependencies = [
  "fastapi>=0.115.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "python-multipart>=0.0.9",
]

[dependency-groups]
dev = [
  "pytest>=8.3.0",
  "mypy>=1.11.0",
]
```

## 明确留给后续 Phase

# Phase 3：Mock GPU Service

## 实现范围

Phase 3 实现两个独立运行的 Mock GPU Microservice，不将其放入 Main Backend 进程：

```text
mock_services/
  pyproject.toml
  mock_services/
    settings.py
    contract.py
    job_store.py
    base.py
    artifact_client.py
    fast_service.py
    slow_service.py
  tests/
    test_mock_services.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `settings.py` | 读取 `CONTROL_PLANE_BASE_URL` |
| `contract.py` | Mock Service 使用的最小 `/v1` contract 类型 |
| `job_store.py` | in-memory job 状态与增量日志 |
| `base.py` | 两个 mock 共用的 FastAPI `/v1` 协议与异步执行 |
| `artifact_client.py` | 通过 HTTP 调用 Main Backend Artifact API |
| `fast_service.py` | `mock-fast` app |
| `slow_service.py` | `mock-slow` app |

## `mock-fast`

- `module_key = mock_fast`；
- 默认端口 `8101`；
- 默认运行 3 秒；
- `queued -> running -> succeeded`；
- progress 变化到 100；
- 至少输出三条日志；
- 参数 `message`；
- 输出 `report` artifact。

## `mock-slow`

- `module_key = mock_slow`；
- 默认端口 `8102`；
- 默认运行 45 秒；
- 支持参数 `duration_seconds` 和 `failure_rate`；
- progress 持续变化；
- 支持 `log_after_seq` 增量日志；
- 支持 cancel；
- 支持 failure 模拟；
- 终态不会被后台任务覆盖。

## JobStore 设计

`JobStore` 是 in-memory store，保存：

```ts
StoredJob {
  job_id
  module_key
  status
  progress_percent
  progress_phase
  logs
  output_artifacts
  error?
  created_at
  started_at?
  finished_at?
  updated_at
  cancel_requested
  failure_rate
  parameters
}
```

MVP 不要求 Mock Service 重启后恢复 job。

## 异步执行方式

`POST /v1/jobs` 只做参数校验、创建 job、写入首条日志，然后立即返回 `queued`。

实际执行通过 `asyncio.create_task` 在后台运行：

```text
queued
-> running
-> succeeded / failed / cancelled
```

## Cancel 实现

cancel 是 best effort：

```text
queued / running
-> cancelling
-> task.cancel()
-> cancelled
```

如果 job 已经是 `succeeded / failed / cancelled / timeout`，返回：

```json
{
  "detail": {
    "code": "JOB_ALREADY_FINISHED",
    "message": "job already finished",
    "details": {
      "job_id": "..."
    }
  }
}
```

## Artifact 上传数据流

Mock Service 不直接访问 Main Backend 的 SQLite、文件目录或 `LocalArtifactStore`。

输出 artifact 通过 HTTP 上传：

```text
Mock GPU Service
-> POST {CONTROL_PLANE_BASE_URL}/api/v1/artifacts
-> Main Backend ArtifactService
-> LocalArtifactStore + ArtifactRepository
-> 返回 artifact_id / uri
-> Mock GPU Service 写入 output_artifacts
```

`CONTROL_PLANE_BASE_URL` 可通过环境变量配置，默认值：

```text
http://127.0.0.1:8000
```

当前测试环境下，未启动 Main Backend 的 artifact 上传会失败，因此任务按协议进入：

```text
failed / INTERNAL_ERROR / artifact upload failed
```

这仍然是正确的 GPU Service 行为，不会返回假的 `succeeded`。

## 启动方式

### Terminal 1：Main Backend

```bash
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Terminal 2：mock-fast

```bash
cd mock_services
uvicorn mock_services.fast_service:app --host 127.0.0.1 --port 8101
```

### Terminal 3：mock-slow

```bash
cd mock_services
CONTROL_PLANE_BASE_URL=http://127.0.0.1:8000 uvicorn mock_services.slow_service:app --host 127.0.0.1 --port 8102
```

## curl 手工验证

### Health

```bash
curl http://127.0.0.1:8101/v1/health
curl http://127.0.0.1:8102/v1/health
```

### Metadata

```bash
curl http://127.0.0.1:8101/v1/metadata
curl http://127.0.0.1:8102/v1/metadata
```

### Submit fast job

```bash
curl -X POST http://127.0.0.1:8101/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_id":"job_fast_001","module_key":"mock_fast","parameters":{"message":"hello"}}'
```

### Query job

```bash
curl http://127.0.0.1:8101/v1/jobs/job_fast_001
curl "http://127.0.0.1:8101/v1/jobs/job_fast_001?log_after_seq=0"
```

### Submit slow job

```bash
curl -X POST http://127.0.0.1:8102/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_id":"job_slow_001","module_key":"mock_slow","parameters":{"duration_seconds":10,"failure_rate":0}}'
```

### Cancel slow job

```bash
curl -X POST http://127.0.0.1:8102/v1/jobs/job_slow_001/cancel
```

## 验证结果

```text
backend:
pytest:       24 passed
mypy:         Success: no issues found in 29 source files
compileall:   passed

mock_services:
pytest:       5 passed
mypy:         Success: no issues found in 10 source files
compileall:   passed
```

## 留给 Phase 4

- Service Registry；
- 手动注册 mock-fast / mock-slow；
- health / metadata 同步；
- Job Manager；
- GPU Service Client；
- job 提交；
- 远端 job 状态聚合；
- 日志同步；
- cancel 转发；
- rerun。

### Phase 4

- Service Registry 行为；
- Job Manager；
- GPU Service Client；
- job 后台轮询；
- 日志聚合；
- cancel / rerun。

### 更后续阶段

- curl 端到端验收；
- Frontend Service Debugger；
- 第一个真实云端 GPU Service；
- 第二个服务与手动串联；
- Workflow / Pipeline。

## Phase 4 — Service Registry 与 Job 编排

### 新增/修改文件

- backend/app/db.py：扩展 services.instance_label，新增 jobs/services 索引与 SQLite 轻量迁移。
- backend/app/repositories/service_repository.py：AlgorithmService 持久化与查询。
- backend/app/repositories/job_repository.py：Job 持久化、状态过滤与增量字段更新。
- backend/app/repositories/job_log_repository.py：job logs 持久化与 seq 增量查询。
- backend/app/services/gpu_service_client.py：统一封装 /v1/health、/v1/metadata、/v1/jobs、/v1/jobs/{id}、cancel。
- backend/app/services/service_registry.py：手动注册、health/metadata 同步、online/offline 状态维护。
- backend/app/services/job_manager.py：创建、提交、sync、cancel、rerun、restart recovery。
- backend/app/api/public_api.py：新增 Service / Job Public API。
- backend/app/main.py：组装运行时对象并启动后台 polling。
- backend/app/settings.py：新增 control plane URL、submit/poll/execution timeout、poll interval。
- backend/tests/test_phase4_services_jobs.py：Phase 4 集成测试。
- backend/pyproject.toml / backend/uv.lock：新增 backend httpx。
- backend/app/schemas/common.py：ArtifactDescriptor.uri 允许 Main Backend 相对 URI。
- backend/app/domain/models.py：AlgorithmService 增加 instance_label / enabled。

### SQLite schema 变化

- services 新增 instance_label，保持同一 module_key 多实例能力；
- 新增 idx_jobs_status、idx_services_module_key；
- Database.initialize() 会为已有 SQLite 数据库执行轻量列迁移。

### Service Registry 行为

- POST /api/v1/services 只要求 name、base_url；
- module_key 不信任用户输入，由远程 /v1/metadata 同步；
- 注册时不要求服务在线，失败仍保存 registration，状态进入 offline；
- POST /services/{id}/check 重新拉取 health / metadata；
- 支持 enable / disable，不执行自动负载均衡。

### Public API

- GET /api/v1/services
- POST /api/v1/services
- GET /api/v1/services/{service_id}
- POST /api/v1/services/{service_id}/check
- POST /api/v1/services/{service_id}/enable
- POST /api/v1/services/{service_id}/disable
- POST /api/v1/jobs
- GET /api/v1/jobs/{job_id}
- POST /api/v1/jobs/{job_id}/cancel
- POST /api/v1/jobs/{job_id}/rerun
- POST /api/v1/jobs/{job_id}/sync
- GET /api/v1/jobs/{job_id}/logs?after_seq=...

### Job 状态与同步规则

- Main Backend 控制：created、submitting、submitted、submit_failed；
- 服务接受后以远程 queued / running / cancelling / succeeded / failed / cancelled 为准；
- 终态不会被 polling 覆盖；
- 网络失败保留最近状态，只递增 consecutive_poll_failures 并写 orchestrator log；
- cancel 转发是 best effort；
- rerun 创建新 job，复制参数、输入和 rerun_of_job_id；
- Main Backend 重启时通过 recover() 同步仍活跃的 job。

### 后台 polling

FastAPI lifespan 会启动 polling task：

- 查询 submitting / submitted / queued / running / cancelling；
- 调用 JobManager.sync()；
- 增量拉取远端 logs；
- 保存 progress、error、output artifacts；
- 不因单次网络错误直接失败。

### 验证结果

backend:
pytest:       32 passed
mypy:         Success: no issues found in 28 source files
compileall:   passed

### 留给 Phase 5

- Frontend Service Debugger；
- 真实云端 GPU Service；
- Artifact 签名 URL；
- Workflow / Pipeline 编排；
- 自动服务调度与负载均衡。

## Phase 5 — End-to-End Integration & Runtime Hardening

### Changes

- Added scripts/e2e_smoke.py for a real HTTP-boundary smoke test.
- Added backend/tests/test_phase5_runtime_hardening.py.
- Added a centralized can_transition() state-machine check in JobManager.
- Added runtime diagnostics for service registration/sync, job lifecycle, polling, cancel, and recovery.
- Added docs/phase5-e2e.md with local startup, environment variables, smoke test, restart recovery, and common errors.

### State Machine

Terminal states are succeeded, failed, cancelled, and timeout. The local state transition is centralized in can_transition(). Polling never overwrites terminal states. Cancelling may resolve to cancelled, succeeded, or failed depending on the remote result.

### Polling and Recovery

Polling failures preserve the last known status and increment consecutive_poll_failures. After the configured threshold, polling skips that job until reset or recovery. Backend restart calls recover() for active jobs and continues polling the same remote job_id.

### Artifact Boundary

Artifact APIs continue to expose only artifact_id, public URI, type, name, MIME type, size, and metadata. Tests explicitly assert that storage_key and local filesystem paths are not leaked.

### Validation

Backend tests: 39 passed. Mock service tests: 5 passed. Backend mypy: clean. Backend compileall: passed.

### Phase 5 最终验证与修正

- 修复 mock-fast 单测中 artifact 上传失败路径意外依赖宿主机 8000 端口真实 Backend 的问题。
- 该用例现在将 Control Plane URL 隔离为不可达地址，验证服务在 artifact 上传失败时会进入 failed。
- 最终验证结果：Backend pytest 39 passed；Mock services pytest 5 passed。
- Backend mypy 28 个源文件无问题；Mock services mypy 8 个源文件无问题。
- Backend 与 Mock services compileall 均通过。
- 真实 HTTP smoke test 已通过，覆盖 service registration、input artifact upload、fast job success、logs、output artifact 和 slow job cancel。

## Phase 6

### Changes

- 实现了 Frontend Service Debugger 与后续 Generic Module Workbench 所需的前端基础。
- 增加 React UI、API client、job polling、参数表单、日志视图、artifact 预览和 Three.js GLB 预览。
- 增加默认 frontend demo job，使浏览器端无需真实 GPU service 也能验证 job 详情、日志、输出映射和 GLB 预览。
- 修复 frontend 交互选择与页面导航问题。
- 配置 Vite dev proxy，使 frontend 只访问 Main Backend。

### Validation

- Backend pytest 46 passed。
- Frontend TypeScript check passed。
- Production build passed。
- Real HTTP E2E passed。

## Phase 7

### Final Result

Phase 7 — DONE。详细验收记录见 `phase7-acceptance.md`。

### Changes

- 引入持久化 ModuleDefinition，与 AlgorithmService 分离。
- 实现 Module CRUD API、模块校验、模块/服务兼容性判断和 module-aware job 关联。
- SQLite 新增 modules 表和 jobs 的 nullable module_id。
- 实现 Module-centric Home、Module Studio 和 data-driven Generic Module Workbench。
- 增加 artifact metadata.output_slot 与前端 output slot mapping。
- 修复 WSL/Windows Node 构建路径污染，恢复 Linux-native production build。
- 将默认 demo job 与 Recent Jobs 集成到 Generic Workbench。
- 修正 backend runtime 状态注入与独立进程启动脚本。

### Semantics

- Module ready 表示定义结构有效。
- Runtime Available 表示存在 compatible、enabled、online service。
- Module 定义状态与 runtime 可用性分离。
- Job 可携带 nullable module_id，旧 job 保持兼容。
- artifact metadata 中的 output_slot 是 output mapping 的运行时线索，不是新协议必填字段。

### Validation

- Backend pytest: 46 passed。
- Backend mypy: pass，31 files。
- Backend compileall: pass。
- Mock pytest: 6 passed。
- Mock mypy: pass。
- Frontend typecheck: pass。
- Frontend production build: pass。
- Real HTTP E2E: PASS，最终下载 956-byte GLB。
- Backend restart persistence: PASS。
- Vite dev proxy: PASS。

### Accepted Boundaries

- Frontend 只访问 Main Backend。
- Main Backend 拥有 orchestration、state、registry、artifact metadata 和 storage。
- GPU Service 只负责 execution，并使用 Contract v1。
- artifact 文件和 storage_key 不得跨越 service boundary。
- Phase 7 未引入 Workflow、DAG、scheduler、retry engine 或 real GPU integration。

### Deferred

- MIME、extension、parameter 和 runtime capacity 不参与兼容性匹配。
- optional output capability matching 暂缓。
- module archive/delete 暂缓。
- GLB 视觉质量仍需人工检查。

## Phase 8 — Real GPU Algorithm Integration

### Status

Phase 8 — TECHNICAL READY / REAL GPU ACCEPTANCE PENDING.

真实 A100 GPU 的 E2E 验收需要实际部署到 A100 环境后完成。

### Changes

- 新增 `RuntimeSpec` 领域模型，描述模块的 GPU 资源要求（runtime_type、gpu_mode、min_vram_gb、model_residency、max_concurrency）
- `RuntimeSpec` 持久化：`modules` 表新增 `runtime_spec_json` 列，通过 Module CRUD API 传播
- 新增 `services/trellis_service/` — 符合 Contract v1 的真实 TRELLIS.2 GPU Service
  - 启动时一次性加载模型，Job 间持久驻留
  - `max_concurrency = 1` 异步队列
  - Artifact API 作为唯一数据交换边界
  - 使用环境变量配置，无硬编码凭据
- 前端 Generic Workbench 新增 Existing Artifact Reuse：input slot 支持 "Upload New" 或 "Use Existing"（手动串联，非 Workflow）
- 新增 `docs/gpu-runtime-architecture.md` — 长期 GPU Runtime 架构文档
- 新增 `docs/phase8-acceptance.md` — Phase 8 验收报告
- 新增 `backend/app/domain/runtime_spec.py` — 独立 RuntimeSpec 枚举与模型（作为过去保留，当前定义在 `models.py` 中）
- `backend/app/schemas/module.py` — ModuleResponse、ModuleCreateRequest、ModuleUpdateRequest 均包含 runtime_spec

### Key Semantics

- `RuntimeSpec` 只描述资源要求，不实现 GPU Scheduler
- Heavy GPU 模块当前部署策略：1 GPU = 1 persistent service，但这不是永久系统规则
- 轻量 GPU、CPU、External 模块未来可采用不同 RuntimeSpec
- Existing Artifact Reuse 不是 Workflow — 无 WorkflowRun、StepRun、dependsOn、DAG

### Validation

- Backend pytest: 52 passed (46 legacy + 6 Phase 8)
- Backend mypy: pass，32 files
- Backend compileall: pass
- RuntimeSpec 持久化与序列化 roundtrip: pass
- Module CRUD 携带 RuntimeSpec: pass
- Legacy 模块（无 runtime_spec）兼容: pass
- TRELLIS 服务结构验证: pass（无法在无 A100 环境执行推理）

### Accepted Boundaries

Phase 8 未引入：
- Workflow / DAG
- GPU Scheduler / automatic placement / load balancing
- S3 / MinIO / multipart upload
- 自动 timeout enforcement
- 认证 / 多用户隔离

### Deferred (Phase 8 内已知未修复)

- submitting restart recovery 不完整
- terminal-state transition validation
- 自动 timeout enforcement
- Polling 连续 3 次失败后跳过
- 无 artifact checksum
- 无 signed URL

### Phase 8 Gate

Phase 8 is closed at TECHNICAL READY / REAL GPU ACCEPTANCE PENDING.
进入 Phase 9 前应先明确范围；不得默认开始 Workflow / DAG。
