# GPU Runtime Architecture

> 长期架构文档：说明为什么 GPU Runtime 需要独立于通用 Control Plane，
> 以及 ModuleDefinition / RuntimeSpec / Service Instance / Physical GPU
> 四层分离的设计理由。
>
> 本文不记录具体实现细节，也不替代 Phase 8 acceptance 报告。
> Phase 8 的具体验证结果请见 [`phase8-acceptance.md`](phase8-acceptance.md)。

---

## 1. Purpose

Mock Service 阶段（Phase 1–7）所有 GPU 服务都是模拟的，模型加载成本被完全忽略。
真实巨型预训练模型（如 TRELLIS.2）引入了一个 Mock 阶段不存在的约束：

| 特性 | Mock Service | TRELLIS.2-class Model |
|------|-------------|----------------------|
| 显存占用 | 0 | A100 40GB 级别 |
| 模型加载 | 无 | ~30s `from_pretrained()` + `cuda()` |
| 推理耗时 | 秒级 | 分钟级 |
| 多 Job 并发 | 无限制 | OOM 风险 |
| 模型权重 | 无 | ~20GB 磁盘 + GPU 显存 |

这意味着：**不能用处理 Mock Service 的思维方式设计真实 GPU Runtime。**

核心原则：

- 模型满足 "load once, serve many"；
- 每个重型 GPU 模块对应一个长期驻留的 Service；
- 模型不随 Job 结束卸载。

---

## 2. Core Runtime Model

系统区分四个层次，不允许合并：

```
ModuleDefinition
    描述算法是什么（input slots / output slots / parameters）
        ↓
RuntimeSpec
    描述算法需要什么资源（GPU / VRAM / persistence）
        ↓
Service Instance
    描述算法当前运行在哪里（base_url / status / health）
        ↓
Physical GPU / CPU / External
    实际执行资源
```

```
```

### 2.1 ModuleDefinition

已有的概念（Phase 7 引入），与运行时无关。

- 声明 input slots、output slots、parameter schema
- 只回答 "这是什么算法"
- 不回答 "它需要什么资源"

### 2.2 RuntimeSpec

Phase 8 新增，附着在 ModuleDefinition 上。

- 声明 runtime type (cpu / gpu / external)
- 声明 GPU 模式 (dedicated / shared_allowed)
- 声明最低显存需求
- 声明模型驻留策略 (persistent / on_demand)
- 声明最大并发数

RuntimeSpec 只描述**资源要求**，不实现 GPU Scheduler。

### 2.3 Service Instance

已有的概念（Phase 4 引入），描述一个已注册的运行中服务。

- 包含 base_url、status、version、capabilities
- 包含 GPU 信息（通过 `/v1/health` 同步）
- 回答 "这个算法当前在哪里运行、是否在线"

### 2.4 Physical GPU

实际执行硬件。当前一个 Service 对应一个 GPU，未来可能变化。

---

## 3. Heavy GPU Runtime Policy

以 TRELLIS.2 为第一个真实案例：

```json
{
  "runtime_type": "gpu",
  "gpu_mode": "dedicated",
  "min_vram_gb": 40.0,
  "model_residency": "persistent",
  "max_concurrency": 1
}
```

对于 Heavy GPU Module，当前部署策略为：

```
1 GPU
→ 1 persistent algorithm service
→ 1 main heavy model
```

```
```

**这不是整个系统的永久规则。**

- 轻量 GPU 模块（如 CPU 推理、小模型）未来可以使用 `shared_allowed` + `on_demand`
- CPU 模块不需要 GPU Runtime
- External 模块（如调用外部 API）不需要 GPU Runtime

不要把 "1 GPU = 1 Algorithm" 写死为整个系统的架构原则。

---

## 4. Persistent Model Lifecycle

目标生命周期：

```
Service startup
  → load pretrained model once (from_pretrained / cuda)
  → move model to GPU
  → READY (status = online)
  → Job 1 inference (reuse resident model)
  → Job 2 inference (reuse resident model)
  → Job 3 inference (reuse resident model)
  → model remains resident until service termination
```

```
```

**明确禁止的行为：**

- 在 Job 的主执行路径中调用 `from_pretrained()` 或 `cuda()`
- 在 Job 完成后卸载模型（卸载只在服务终止时发生）
- 每次 SSH 连接到一个远程服务器执行推理（这是旧路径的做法）

**区分两个概念：**

| 概念 | 含义 |
|------|------|
| process alive | 服务进程在运行，但不代表模型已加载 |
| model ready | 模型已加载到 GPU，可以接受 Job |

Service 的 `GET /v1/health` 返回 `online` 只表示 process alive + model ready。
如果模型尚未加载完成，应返回 `starting`。

---

## 5. TRELLIS Before / After

### 旧路径（legacy / demo execution path）

```
Gradio UI
→ paramiko SSH
→ SFTP upload input image
→ remote Python process (每次连接都 from_pretrained + cuda)
→ inference
→ GLB export
→ SFTP download result
→ Gradio 3D preview
```

问题：

- 每次请求都重新加载模型（~30s 浪费）
- 无 job queue（并发请求 → OOM）
- 无状态追踪（断开后不知道 job 状态）
- 无增量日志、无进度汇报
- 使用 SSH 凭据直接访问服务器（安全风险）
- 使用本地文件路径而非 artifact URL

### 新架构（Control Plane 生产路径）

```
Generic Workbench
→ Main Backend (ServiceRegistry / JobManager)
→ TRELLIS GPU Service (persistent resident model on A100)
→ Artifact API (HTTP upload / download)
→ GLB
→ Generic Workbench MeshPreview (Three.js)
```

改进：

- 模型启动时加载一次，永久驻留
- Job 通过 Contract v1 异步提交
- 所有数据传输通过 Artifact API（HTTP URL）
- 增量日志、进度汇报、状态追踪
- 凭据通过环境变量管理
- max_concurrency = 1 防 OOM

---

## 6. Artifact Boundary

长期架构原则：

```
Frontend
  → Main Backend Public API
     → JobManager
        → GPU Service (Contract v1)
           ↔ Artifact API (HTTP upload/download)
```

```
```

**明确禁止的通信路径：**

- Frontend 直接访问 GPU Service
- GPU Service 直接访问 Main Backend SQLite
- GPU Service 直接读写 Main Backend 的本地文件路径
- 通过共享文件系统路径在服务之间传输数据
- 在 Public API 或 Contract v1 中暴露 `storage_key` 或内部路径

**模块间数据交换只使用：**

| 概念 | 说明 |
|------|------|
| `artifact_id` | 系统稳定标识符 |
| HTTP URL | 数据传输地址 |
| `ArtifactDescriptor` | 元信息（type / name / mime_type / size） |
| `output_slot` | 输出映射标识（前端 UI 排序依据） |

---

## 7. Concurrency

TRELLIS.2 当前策略：

| 参数 | 值 |
|------|-----|
| max_concurrency | 1 |

原因：重型模型不能默认允许多个 inference 同时占用同一张 GPU，否则 OOM。

后续 Job 的行为：

- 如果 service 报告 `load.running_jobs >= load.max_concurrent_jobs`，Main Backend 应暂不提交新 Job
- 当前 Phase 8 没有 queued/waiting 行为——第二个 Job 直接返回 HTTP 503

**当前不实现：**

- GPU scheduler
- automatic service placement
- load balancing
- autoscaling
- dynamic GPU allocation

---

## 8. Manual Chaining

Phase 8 当前支持的跨模块数据传递方式：

```
Module A Job
  → Output Artifact (with output_slot)
    → 用户在 Generic Workbench 中手动选择
      → 作为 Module B 的 Input
```

Generic Workbench 的每个 input slot 提供两种选择：

- **Upload New** — 上传新文件
- **Use Existing** — 从 Recent Jobs 的输出中选择兼容的 Artifact

#### 这不是 Workflow

当前系统中**不存在**：

- `WorkflowRun`
- `WorkflowStep`
- `dependsOn`
- 自动触发（上游 Job 完成后自动提交下游 Job）
- 拓扑排序
- DAG engine

Manual chaining 本质上是前端辅助的用户操作，不是后端编排。

---

## 9. Future Workflow Decision

现在不设计 Workflow 架构。

原因：

未来必须基于至少第二、第三个真实算法的实际连接关系决定 Workflow 形态。
不同算法之间的依赖关系可能是：

- linear pipeline（A → B → C）
- DAG（A → B, A → C, B → D）
- independent（A, B, C 互不依赖）
- mixed topology

**不要把未来一定会用 DAG 写死。**

等以下条件满足后再设计：

1. 至少两个真实 GPU 算法已通过 Contract v1 接入
2. 实际的手动串联使用数据已累积
3. 算法之间的输入/输出类型映射关系已明确

---

## 10. Runtime Categories

RuntimeSpec 未来允许的值范围：

| Category | runtime_type | gpu_mode | model_residency | 典型场景 |
|----------|-------------|----------|-----------------|---------|
| Heavy GPU | `gpu` | `dedicated` | `persistent` | TRELLIS.2 (A100 40GB) |
| Light GPU | `gpu` | `shared_allowed` | `persistent` / `on_demand` | 轻量分割模型 |
| CPU | `cpu` | — | `on_demand` | 视频帧提取、文件处理 |
| External | `external` | — | — | 调用外部 API |

**注意：** `RuntimeSpec` 当前只描述资源要求，它不是 Scheduler。
系统目前不会根据 `RuntimeSpec` 自动分配 GPU 或调度 Job。

---

## 11. Security

长期安全原则：

- **credentials 不得写入 repository**
- GPU endpoint secret 使用 environment variables 或 secret management
- 任何发现公开仓库中包含的密码、token、SSH credential，不得使用、不得复制

当前状态：

**SECURITY ACTION REQUIRED**

在 `xiangguaguadadi-dot/aigc` 仓库中：

- `01_TRELLIS2_core/app.py` 包含 A100 服务器地址、端口、用户名、密码
- `01_TRELLIS2_core/docs/SETUP_SERVER.md` 包含明文 SSH 密码

这些凭据未复制到本项目。
Phase 8 实现的 TRELLIS Service 只使用环境变量，不含任何硬编码凭据。

---

## 12. Current Status

| 维度 | 状态 |
|------|------|
| Phase 8 architecture implementation | **TECHNICAL READY** |
| Real TRELLIS A100 E2E | **PENDING** |

Phase 8 的实际完成需要实现以下 E2E：

```
Real Image
→ Generic Workbench (Upload)
→ Main Backend (Artifact API + JobManager)
→ TRELLIS GPU Service (resident model on A100)
→ Artifact download via HTTP
→ Inference (persistent model)
→ GLB export
→ Artifact upload via HTTP
→ Generic Workbench MeshPreview
```

并且需要至少连续运行两个 Job 以确认：

- 第二个 Job 没有触发 `from_pretrained()` 或 `cuda()`
- 模型驻留显存没有被卸载
- max_concurrency = 1 正确工作（第三个请求被拒绝）

---

## 参考文档

| 文档 | 内容 |
|------|------|
| [`phase8-acceptance.md`](phase8-acceptance.md) | Phase 8 实现验收详情 |
| [`mvp-architecture.md`](mvp-architecture.md) | 系统整体架构 |
| [`backend-mvp-baseline.md`](backend-mvp-baseline.md) | 当前 MVP 基线状态 |
| [`system-boundaries.md`](system-boundaries.md) | 系统职责边界 |

---

*本文不包含未经验证的 GPU 性能数字。所有架构决策基于 TRELLIS.2 的实际代码分析和 A100 40GB 的公开规格。*
