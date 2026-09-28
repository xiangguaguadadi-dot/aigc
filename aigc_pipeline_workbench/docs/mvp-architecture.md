# MVP 架构：远程 GPU 微服务工作台

## 1. 目标与边界

当前项目的第一阶段目标不是构建完整的 AIGC 平台，也不是直接接入所有算法，而是建立一个最小但正确的可视化调试工作台：

```text
注册算法服务
-> 查看 health / capabilities
-> 选择输入 artifact
-> 修改参数
-> 提交异步 Job
-> 观察状态、进度和日志
-> 查看输出 artifact
-> 取消或重新运行
```

第一阶段坚持以下边界：

- Main Backend 是 Control Plane，不做模型推理；
- GPU Microservice 是 Compute Plane，负责真实算法执行；
- Artifact / Object Storage 是服务之间交换大文件的枢纽；
- 前端只与 Main Backend 通信，不直接访问 GPU Service；
- 算法步骤的基本执行单元是远程异步 `Job`，不是本地 Python process；
- 服务之间传递 `artifact_id`、URL 和 metadata，不传递内部文件路径；
- 不引入 Kubernetes、Kafka、Redis、Celery、PostgreSQL、完整 DAG engine 或 Service Mesh。

## 2. 总体架构

```text
+----------------------+
| Frontend Debugger    |
| React + Vite         |
| Service Debugger     |
+----------+-----------+
           | HTTP
           v
+-----------------------------+        +--------------------+
| Main Backend                |<------>| State Store        |
| FastAPI Control Plane       |        | SQLite             |
| - Service Registry          |        +--------------------+
| - Job Manager               |
| - Artifact Metadata         |        +--------------------+
| - Log Aggregator            |<------>| Artifact Store     |
| - GPU Service Client        |        | 第一版可为本地存储 |
+----------+------------------+        +---------+----------+
           |                                     ^
           | HTTP                                |
           v                                     |
+---------------------+   +---------------------+   +----------------+
| Mock GPU Service    |   | Mock GPU Service    |   | Future GPU     |
| Fast                |   | Slow                |   | Microservices  |
| 2~5 seconds         |   | 30~60 seconds       |   | segmentation   |
| simple report       |   | progress / logs     |   | image-to-3D    |
+---------------------+   | cancel / failure    |   | physics / sim  |
                          +---------------------+   +----------------+
```

### 2.1 Frontend

- 技术栈：TypeScript + React + Vite。
- 职责：
  - 展示已注册算法服务；
  - 展示 service health、版本、GPU 信息和 capabilities；
  - 根据 `parameterSchema` 动态渲染参数表单；
  - 提交、取消、重新运行 job；
  - 展示 job status、progress、logs 和 artifacts；
  - 通过 Main Backend 提供的 URL 预览或下载 artifact。

前端不直接调用 GPU Service。

### 2.2 Main Backend / Orchestrator

第一阶段推荐使用 FastAPI / Python。

职责：

- Service Registry：手动注册服务，检查 health 和 metadata；
- Job Manager：创建、提交、轮询、取消、重跑 job；
- Log Aggregator：增量同步和存储 job logs；
- Artifact Metadata：管理 artifact ID、类型、状态和访问 URL；
- Public API：给前端提供统一接口；
- Internal Artifact API：给 GPU Service 提供下载和上传边界。

Main Backend 不理解每个算法的内部细节。

### 2.3 GPU Microservices

每个算法模块是独立部署的远程服务：

- 可以运行在不同云服务器或不同 GPU 上；
- 可以使用不同 Python 环境；
- 可以独立启动、关闭、升级和替换；
- 必须实现统一的 `/v1` 协议；
- 只负责算法执行、job 状态、日志和输出 artifact 描述。

GPU Service 之间不直接互传大文件。

### 2.4 Artifact Store

第一阶段可以先使用 Main Backend 管理的本地 artifact 目录，但对外必须保持 artifact 语义：

```text
artifact_id
-> metadata
-> download / upload URL
-> preview URL
```

未来可以替换成 S3、MinIO 或云对象存储，前端和 GPU Service 的核心协议不应变化。

### 2.5 State Store

第一阶段使用 SQLite 即可。

推荐核心表：

```text
services
jobs
job_logs
artifacts
```

State Store 不作为分布式强一致性系统使用，只满足 MVP 调试需要。

## 3. GPU Microservice Contract

所有 GPU Service 使用统一前缀 `/v1`。

### 3.1 最小强制接口

```http
GET  /v1/health
GET  /v1/metadata
POST /v1/jobs
GET  /v1/jobs/{job_id}?log_after_seq=0
POST /v1/jobs/{job_id}/cancel
```

### 3.2 协议分级

#### 强制统一

- `GET /v1/health`；
- `GET /v1/metadata`；
- `POST /v1/jobs`；
- `GET /v1/jobs/{job_id}`；
- `POST /v1/jobs/{job_id}/cancel`；
- 统一错误对象；
- `job_id` 由 Main Backend 生成并下发；
- 统一 `status` 枚举；
- 输入使用 artifact URL，不使用内部路径；
- 输出以 artifact descriptor 返回；
- 即使没有参数，`parameterSchema` 也要返回空数组。

#### 推荐统一但可选

- `progress.percent`；
- `progress.phase`；
- `progress.message`；
- GPU 信息；
- `estimated_duration_seconds`；
- `max_concurrent_jobs`；
- `supports_cancel`；
- `supports_progress`。

#### 服务自行扩展

- 服务特有 metadata；
- output artifact 的 `metadata`；
- 模型名称、checkpoint、分辨率等算法专属信息；
- 自定义 artifact metadata。

扩展字段不应破坏核心协议。

### 3.3 `GET /v1/health`

最小响应：

```json
{
  "status": "online",
  "service": "image_segmentation",
  "version": "0.1.0"
}
```

推荐响应：

```json
{
  "status": "online",
  "service": "image_segmentation",
  "version": "0.1.0",
  "gpu": {
    "name": "RTX 4090",
    "vram_bytes": 25757220864
  },
  "load": {
    "running_jobs": 1,
    "max_concurrent_jobs": 2
  }
}
```

### 3.4 `GET /v1/metadata`

```json
{
  "module_key": "image_segmentation",
  "name": "Image Segmentation",
  "version": "0.1.0",
  "input_artifact_types": ["image"],
  "output_artifact_types": ["mask", "report"],
  "parameter_schema": [
    {
      "key": "threshold",
      "label": "Confidence Threshold",
      "value_type": "number",
      "required": false,
      "default": 0.5,
      "minimum": 0,
      "maximum": 1
    }
  ],
  "supports_cancel": true,
  "supports_progress": true,
  "max_concurrent_jobs": 1
}
```

`parameter_schema` 的值类型第一阶段保持简单：

```text
string
number
integer
boolean
enum
json
```

### 3.5 `POST /v1/jobs`

请求示例：

```json
{
  "job_id": "job_20260907_001",
  "module_key": "image_segmentation",
  "inputs": [
    {
      "artifact_id": "artifact_image_001",
      "type": "image",
      "name": "input.png",
      "url": "https://control-plane.example.com/internal/v1/artifacts/artifact_image_001/file"
    }
  ],
  "parameters": {
    "threshold": 0.62
  },
  "artifact_store": {
    "create_artifact_url": "https://control-plane.example.com/internal/v1/artifacts"
  }
}
```

响应：

```json
{
  "job_id": "job_20260907_001",
  "status": "queued"
}
```

### 3.6 `GET /v1/jobs/{job_id}`

使用 `log_after_seq` 做增量日志拉取。

```http
GET /v1/jobs/job_20260907_001?log_after_seq=20
```

响应示例：

```json
{
  "job_id": "job_20260907_001",
  "status": "running",
  "progress": {
    "percent": 45,
    "phase": "inference"
  },
  "logs": [
    {
      "seq": 21,
      "level": "info",
      "message": "loaded checkpoint",
      "created_at": "2026-09-07T10:00:12Z"
    }
  ],
  "output_artifacts": [],
  "error": null,
  "started_at": "2026-09-07T10:00:05Z",
  "updated_at": "2026-09-07T10:00:20Z"
}
```

成功后返回：

```json
{
  "job_id": "job_20260907_001",
  "status": "succeeded",
  "output_artifacts": [
    {
      "artifact_id": "artifact_mask_001",
      "type": "mask",
      "name": "object_001_mask.png",
      "uri": "https://control-plane.example.com/api/v1/artifacts/artifact_mask_001/file",
      "mime_type": "image/png",
      "size_bytes": 128443,
      "metadata": {
        "class": "bottle",
        "confidence": 0.91
      }
    }
  ],
  "error": null
}
```

### 3.7 `POST /v1/jobs/{job_id}/cancel`

响应：

```json
{
  "job_id": "job_20260907_001",
  "status": "cancelling"
}
```

cancel 是 best effort，不是强事务保证。GPU Service 应尽力停止推理、释放显存，并在 `GET /jobs/{job_id}` 中返回真实终态。

### 3.8 统一错误对象

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

MVP 基础错误码：

```text
INVALID_REQUEST
INVALID_PARAMETER
JOB_NOT_FOUND
JOB_ALREADY_FINISHED
NOT_IMPLEMENTED
SERVICE_BUSY
INTERNAL_ERROR
```

## 4. Job 模型与状态机

### 4.1 Job 模型

```ts
type JobStatus =
  | "created"
  | "submitting"
  | "submitted"
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "succeeded"
  | "failed"
  | "timeout"
  | "submit_failed";

interface Job {
  jobId: string;
  runId?: string;
  serviceId: string;
  moduleKey: string;
  status: JobStatus;
  parameters: Record<string, unknown>;
  inputArtifacts: ArtifactRef[];
  outputArtifacts: ArtifactRef[];
  progress?: {
    percent?: number;
    phase?: string;
    message?: string;
  };
  error?: JobError;
  createdAt: string;
  submittedAt?: string;
  startedAt?: string;
  finishedAt?: string;
  updatedAt: string;
  rerunOfJobId?: string;
  lastSyncedAt?: string;
  lastSyncError?: string;
  consecutivePollFailures?: number;
}
```

### 4.2 状态机

```text
created
  -> submitting
      -> submitted
          -> queued
              -> running
                  -> succeeded
                  -> failed
                  -> cancelled
                  -> timeout
      -> submit_failed

queued / running
  -> cancelling
      -> cancelled
```

### 4.3 状态来源

| 状态 | 来源 | 说明 |
| --- | --- | --- |
| `created` | Main Backend | job 已创建，尚未提交 |
| `submitting` | Main Backend | 正在调用 GPU Service |
| `submitted` | Main Backend | GPU Service 已接受 job |
| `queued` | GPU Service | 服务端排队 |
| `running` | GPU Service | 正在执行 |
| `cancelling` | Main Backend | 已发送 cancel，但尚未确认 |
| `cancelled` | GPU Service | 服务确认取消 |
| `succeeded` | GPU Service | 执行成功 |
| `failed` | GPU Service 或 Main Backend | 执行失败或 job 丢失 |
| `timeout` | Main Backend | 超过执行时限 |
| `submit_failed` | Main Backend | 提交失败 |

规则：

1. `created / submitting / submitted / submit_failed` 由 Main Backend 决定；
2. job 被服务接受后，`queued / running / succeeded / failed / cancelled` 以 GPU Service 返回为准；
3. Main Backend 是前端看到的聚合 source of truth；
4. 网络轮询失败时不要立刻把 running job 标记为 failed；
5. 只有明确收到错误、达到 timeout、job 丢失或 cancel 最终确认时才进入终态。

### 4.4 网络断开与重启

Main Backend 轮询失败时：

```text
保持最近已知状态
-> 记录 orchestrator log
-> 标记 sync stale
-> 继续重试
-> 若明确 404 JOB_NOT_FOUND，重试若干次后标记 failed / JOB_LOST
-> 若超过 execution_timeout，标记 timeout 并尝试 cancel
```

GPU Service 重启时：

- 如果服务能恢复 job 状态，轮询继续；
- 如果服务是 in-memory 实现，重启后 job 丢失，Main Backend 应在确认 `JOB_NOT_FOUND` 后标记 failed；
- GPU Service 不允许返回假的 running 状态。

### 4.5 Timeout

| 类型 | 建议默认值 | 说明 |
| --- | --- | --- |
| `submit_timeout_seconds` | 10 秒 | `POST /jobs` 必须快速返回 |
| `poll_timeout_seconds` | 5~10 秒 | 单次远端查询超时 |
| `execution_timeout_seconds` | 每个服务可配置，默认 30 分钟 | 超时后标记 timeout 并尝试 cancel |

`estimated_duration_seconds` 只用于 UI 提示，不作为强制 timeout。

### 4.6 Cancel 与 Rerun

cancel 是 best effort。如果服务已经 `succeeded`，不允许被覆盖为 `cancelled`。

rerun 不复用原 job，而是创建新 job：

```text
source job
-> 新 job
-> 复制 parameters
-> 复制 input artifact refs
-> 记录 rerunOfJobId
-> 重新提交
```

## 5. Artifact 模型与数据流

### 5.1 Artifact 模型

```ts
type ArtifactType =
  | "image"
  | "mask"
  | "video"
  | "mesh"
  | "glb"
  | "texture"
  | "point_cloud"
  | "physics_asset"
  | "physics_scene"
  | "trajectory"
  | "report"
  | "log_file"
  | "unknown";

interface ArtifactRef {
  artifactId: string;
  type: ArtifactType;
  name?: string;
  uri?: string;
}

interface Artifact {
  artifactId: string;
  runId?: string;
  jobId?: string;
  type: ArtifactType;
  name: string;
  mimeType?: string;
  sizeBytes?: number;
  uri?: string;
  storageKey?: string;
  visibility: "public" | "internal" | "temporary";
  retention: "temporary" | "result";
  createdAt: string;
  expiresAt?: string;
  metadata: Record<string, unknown>;
}
```

`artifactId` 是对外稳定 ID；`storageKey` 只属于 backend / storage 内部实现。前端和 GPU Service 不依赖内部路径。

### 5.2 第一阶段 Artifact 数据流

```text
Frontend 上传图片
-> Main Backend
-> LocalArtifactStore 保存文件
-> SQLite 保存 artifact metadata
-> 返回 artifact_id

Frontend 提交 job
-> Main Backend 创建 job
-> 生成 GPU Service 可访问的 input download URL
-> POST GPU Service /v1/jobs

GPU Service
-> HTTP 下载 input artifact
-> 执行算法
-> 请求输出 artifact 上传位置
-> 上传 output artifact
-> 在 job status 中返回 output artifact descriptor

Main Backend
-> 保存或确认 output artifact metadata
-> 前端通过 Main Backend 预览或下载
```

即使第一阶段存储在本地目录，GPU Service 也不直接读取 Main Backend 的文件系统，而是通过 HTTP URL 下载和上传。

### 5.3 存储演进

| 场景 | 存储方案 |
| --- | --- |
| 本地 Mock 闭环 | LocalArtifactStore |
| 本地或同网段真实服务 | Main Backend 管理的 storage endpoint |
| 云端 GPU 服务 | 公网可访问的 object storage，例如 S3 / MinIO / Cloud Storage |

引入真实云端 GPU Service 前，必须确认 Main Backend 或 Artifact Store 对该服务可访问。否则应把 backend/storage 部署到云端，或使用对象存储。

### 5.4 输出上传方式

推荐 GPU Service 直接上传到 ArtifactStore 边界，而不是把大文件 POST 给 Main Backend 的业务 API。

第一阶段 ArtifactStore 可以暂时由 Main Backend 暴露内部 upload endpoint 代替：

```text
GPU Service
-> POST create artifact metadata
<- artifact_id + upload_url
-> PUT upload_url binary
```

以后可以把 upload URL 替换成 S3 / MinIO presigned URL，GPU Service 核心逻辑不需要大改。

### 5.5 临时与长期结果

| 类型 | retention | 说明 |
| --- | --- | --- |
| 调试输入 | `temporary` | 可定期清理 |
| 中间产物 | `temporary` 或 `result` | 由用户或服务声明 |
| 最终 GLB / physics asset / report | `result` | 默认长期保留 |
| debug log file | `temporary` | 只用于排查 |

第一阶段不强制自动清理，但必须保留字段语义。

## 6. Service Registry

### 6.1 MVP 范围

第一阶段不做 Kubernetes 风格服务发现，只做：

```text
手动注册 service URL
-> Main Backend 调用 /v1/health
-> Main Backend 调用 /v1/metadata
-> 前端显示 online / offline
-> 提交 job 前重新 check
-> 云端 GPU 关机后自然 offline
```

### 6.2 数据模型

```ts
type ServiceStatus =
  | "online"
  | "offline"
  | "degraded"
  | "busy"
  | "unknown";

interface ServiceRegistration {
  serviceId: string;
  moduleKey: string;
  name: string;
  baseUrl: string;
  enabled: boolean;
  instanceLabel?: string;
  priority?: number;
  createdAt: string;
  updatedAt: string;
}

interface ServiceRuntimeInfo {
  status: ServiceStatus;
  version?: string;
  gpu?: {
    name?: string;
    vramBytes?: number;
    cudaVersion?: string;
    driverVersion?: string;
  };
  capabilities?: {
    inputArtifactTypes: string[];
    outputArtifactTypes: string[];
    parameterSchema: ParameterDefinition[];
    supportsCancel: boolean;
    supportsProgress: boolean;
    maxConcurrentJobs?: number;
    estimatedDurationSeconds?: number;
  };
  lastCheckedAt?: string;
  lastOnlineAt?: string;
  lastError?: string;
}
```

同一个 `moduleKey` 允许注册多个 endpoint。MVP 不自动负载均衡，前端让用户手动选择。该模型为未来 4090 / A100 多实例扩展预留了 `instanceLabel`、`priority` 和 `gpu` 信息。

## 7. Frontend Service Debugger

三个调试入口继续保留，但它们只是按 `moduleKey` 筛选的视图，不是三套独立页面：

```text
/debug/asset-generation
/debug/physics-authoring
/debug/physics-engine
```

通用页面结构：

```text
+----------------------------------------------------------------+
| Backend: connected        Debug Layer: 3D Asset Generation     |
+-------------------+--------------------------------------------+
| Service List      | Service Header                             |
|                   | endpoint / version / status / GPU          |
| - Segmentation    |--------------------------------------------|
| - Image to 3D     | Capabilities                               |
| - Physics Asset   | input types / output types / limits        |
| - Simulation      |--------------------------------------------|
|                   | Input Artifacts                            |
|                   | upload / select artifact / preview         |
|                   |--------------------------------------------|
|                   | Parameter Form                             |
|                   | generated from parameterSchema             |
|                   |--------------------------------------------|
|                   | Run / Cancel / Rerun                       |
|                   |--------------------------------------------|
|                   | Job Status                                 |
|                   | status / progress / started / finished     |
|                   |--------------------------------------------|
|                   | Logs                                       |
|                   | afterSeq polling / level filter            |
|                   |--------------------------------------------|
|                   | Output Artifacts                           |
|                   | image / mask / mesh / glb / report preview |
+-------------------+--------------------------------------------+
```

接入新服务时，前端只增加对应的 artifact renderer，不新增服务专属页面。

## 8. Mock GPU Service 设计

第一阶段实现两个 Mock Service，用于验证协议、异步状态机、日志、artifact 和 cancel。

### 8.1 `mock-fast`

```text
module_key = mock_fast
port      = 8101
```

行为：

- 2~5 秒完成；
- 接受 0 或 1 个输入 artifact；
- 输出 3~5 条日志；
- progress 简单变化；
- 输出一个 `report` artifact；
- 参数 `message` 会写入输出 report。

### 8.2 `mock-slow`

```text
module_key = mock_slow
port      = 8102
```

行为：

- 默认运行 30~60 秒；
- progress 从 0 到 100；
- 每秒产生日志；
- 支持 cancel；
- 支持配置随机失败率；
- 输出一个 `report` artifact。

参数：

```json
[
  {
    "key": "duration_seconds",
    "label": "Duration Seconds",
    "value_type": "integer",
    "required": false,
    "default": 45,
    "minimum": 5,
    "maximum": 300
  },
  {
    "key": "failure_rate",
    "label": "Random Failure Rate",
    "value_type": "number",
    "required": false,
    "default": 0,
    "minimum": 0,
    "maximum": 1
  }
]
```

### 8.3 Mock Service 接口

Mock Service 与真实 GPU Service 使用完全相同的协议：

```http
GET  /v1/health
GET  /v1/metadata
POST /v1/jobs
GET  /v1/jobs/{job_id}?log_after_seq=0
POST /v1/jobs/{job_id}/cancel
```

### 8.4 端到端流程

```text
注册 Mock Service
-> Main Backend 检查 health / metadata
-> 前端展示服务
-> 上传或选择输入 artifact
-> 动态生成参数表单
-> Submit Job
-> Main Backend 每 1~2 秒轮询 GPU Service
-> 同步 status / progress / logs / artifacts
-> 前端展示结果
-> rerun 或 cancel
```

### 8.5 验收标准

1. 注册 mock-fast 和 mock-slow；
2. 显示 online / offline；
3. 读取 `/v1/metadata` 并动态生成参数表单；
4. 创建 job 后立即返回 `jobId`；
5. 状态按 `created -> submitting -> submitted -> queued -> running -> succeeded` 变化；
6. 日志增量显示；
7. progress 正确更新；
8. mock-slow 可以 cancel；
9. mock-slow 可以配置随机失败并显示统一 error；
10. 输出 artifact 能通过 Main Backend 预览或下载；
11. rerun 创建新 job，并保留原 job 历史；
12. 修改参数后 rerun 生效。

## 9. 代码结构规划

### 9.1 Backend

```text
backend/
  pyproject.toml
  app/
    __init__.py
    main.py
    settings.py
    db.py
    domain.py
    schemas.py
    api/
      public_api.py
      internal_api.py
    repositories/
      service_repository.py
      job_repository.py
      artifact_repository.py
      log_repository.py
    services/
      service_registry.py
      job_manager.py
      gpu_client.py
      artifact_service.py
    storage/
      local_artifact_store.py
```

职责：

- `main.py`：FastAPI 启动；
- `settings.py`：端口、SQLite 路径、storage root、timeout；
- `db.py`：SQLite 初始化；
- `domain.py`：领域模型；
- `schemas.py`：HTTP request / response 模型；
- `public_api.py`：前端 API；
- `internal_api.py`：GPU Service 的 artifact download / upload API；
- `service_registry.py`：注册、health、metadata；
- `job_manager.py`：创建、提交、轮询、cancel、rerun；
- `gpu_client.py`：封装 GPU Service 协议；
- `artifact_service.py`：artifact metadata；
- `local_artifact_store.py`：本地存储实现。

### 9.2 Mock Services

```text
mock_services/
  pyproject.toml
  mock_services/
    __init__.py
    contract.py
    job_store.py
    artifact_uploader.py
    fast_service.py
    slow_service.py
```

### 9.3 Frontend

```text
frontend/src/
  api/
    http.ts
    workbench.ts
  objects/
    service.ts
    job.ts
    artifact.ts
    parameter.ts
  page/
    debug-home/
      DebugHomePage.tsx
      DebugLayerSelector.tsx
      DebugLayerButton.tsx
    service-debugger/
      ServiceDebuggerPage.tsx
      ServiceList.tsx
      ServiceHeader.tsx
      ServiceCapabilities.tsx
      InputArtifactPanel.tsx
      ParameterForm.tsx
      JobActionPanel.tsx
      JobStatusPanel.tsx
      JobLogPanel.tsx
      ArtifactList.tsx
      ArtifactPreview.tsx
```

第一阶段可以适当合并组件，但 `ParameterForm`、`JobStatusPanel`、`JobLogPanel` 和 `ArtifactPanel` 应该保持独立，因为它们会被所有服务复用。

## 10. 开发顺序

### Phase 1：协议与类型

1. 固化 GPU Service Contract `/v1`；
2. 定义 `AlgorithmService`、`Job`、`Artifact`、`JobLog`、`JobError`；
3. 定义统一 API 错误；
4. 定义 parameter schema；
5. 生成或手写前端 TypeScript 类型。

### Phase 2：Main Backend 最小骨架

1. 初始化 FastAPI；
2. 创建 SQLite 表：`services`、`jobs`、`job_logs`、`artifacts`；
3. 实现 `/api/v1/health`；
4. 实现 artifact upload / download API；
5. 实现 `LocalArtifactStore`。

### Phase 3：Mock GPU Service

1. 实现 mock-fast；
2. 实现 mock-slow；
3. 两者遵守 `/v1` 协议；
4. 输出 artifact 通过 artifact upload URL 上传；
5. 用 curl 验证 health、metadata、jobs、cancel。

### Phase 4：Service Registry + Job Manager

1. 手动 service 注册；
2. health check 和 metadata 同步；
3. job 创建；
4. 参数校验；
5. job 提交；
6. 后台轮询；
7. 日志同步；
8. artifact metadata 注册；
9. cancel / rerun。

### Phase 5：curl 端到端验收

先验证：

```text
register mock service
-> check health
-> get metadata
-> upload artifact
-> submit job
-> poll job
-> poll logs
-> cancel slow job
-> download output artifact
-> rerun
```

### Phase 6：Frontend Service Debugger

1. service list；
2. service detail；
3. health / capabilities；
4. input artifact 选择；
5. parameter form；
6. run / cancel / rerun；
7. job status；
8. logs；
9. output artifacts；
10. artifact preview。

### Phase 7：第一个真实云端 GPU Service

建议选择耗时稳定、输入输出明确的模块，例如 segmentation：

```text
image artifact
-> segmentation job
-> mask artifact
-> preview
```

前提：

- Main Backend 或 ArtifactStore 对 GPU Service 可访问；
- Service 正确实现 `/v1` 协议；
- GPU 环境隔离；
- timeout / cancel 可测试。

### Phase 8：第二个服务 + 手动串联

例如：

```text
image
-> segmentation
-> image-to-3D
```

第一阶段不做 DAG，只支持把上一个 job 的 output artifact 手动选为下一个 job 的 input artifact。

### Phase 9：Workflow / Pipeline

只有手动串联稳定后，再考虑：

- WorkflowRun；
- WorkflowStep；
- dependsOn；
- 自动提交；
- step retry；
- workflow status。

## 11. 最终 MVP 验收闭环

```text
React Service Debugger
-> FastAPI Control Plane
-> Mock GPU Service

选择 service
-> 查看 health / capabilities
-> 配置输入 artifact 和参数
-> submit job
-> 状态从 queued / running 到 succeeded
-> 查看增量日志
-> 查看输出 artifact
-> 修改参数 rerun
-> cancel 长任务
```

这个闭环跑通后，真实 GPU Service 接入只需要满足同一协议并接入 ArtifactStore，而不需要继续修改前端和 Main Backend 的整体架构。
