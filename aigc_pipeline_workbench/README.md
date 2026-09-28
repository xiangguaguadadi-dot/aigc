# AIGC Pipeline Workbench

`aigc_pipeline_workbench` 是一个面向 AIGC 3D 资产生成与物理交互流程的可视化调试工作台。

当前目标不是构建完整平台，也不是直接接入所有算法，而是建立一个最小但正确的远程 GPU 微服务调试闭环：

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

## 当前架构

```text
Frontend Debugger
-> Main Backend / Orchestrator
-> Remote GPU Microservices
-> Artifact / Object Storage
```

核心边界：

- Frontend 只与 Main Backend 通信；
- Main Backend 是 Control Plane，不执行模型推理；
- GPU Microservice 是 Compute Plane，独立部署在云端或本地 GPU 环境；
- 算法步骤的基本执行单元是远程异步 `Job`；
- Artifact Store 是服务之间交换大文件的枢纽；
- 服务之间传递 `artifact_id`、URL 和 metadata，不传递内部文件路径。

## 当前技术栈

| 层 | 技术 |
| --- | --- |
| Frontend | TypeScript + React + Vite + Three.js |
| Main Backend | Python + FastAPI |
| State Store | SQLite |
| GPU Microservices | Python / CUDA 服务，统一 `/v1` HTTP 协议 |
| Artifact Store | 第一阶段 LocalArtifactStore，后续可替换为 S3 / MinIO |

## 当前代码状态

Phase 1–6 已完成：

- `backend/` 提供 Contract v1、ArtifactStore、Service Registry、Job Manager 和 Public API；
- `mock_services/` 提供 mock-fast / mock-slow 两个独立 GPU Service 调试服务；
- `frontend/` 提供 Single-Module Debugging Workbench，包括参数表单、Job 状态、日志、输出 artifacts 和 GLB 交互预览；
- `docs/backend-mvp-baseline.md` 是当前 MVP 架构基线；
- `docs/phase6-acceptance.md` 是 Phase 6 验收报告。

## 文档结构

- [`docs/backend-mvp-baseline.md`](docs/backend-mvp-baseline.md)：当前 MVP 架构基线。
- [`docs/phase6-acceptance.md`](docs/phase6-acceptance.md)：Phase 6 验收报告。
- [`docs/mvp-architecture.md`](docs/mvp-architecture.md)：早期架构文档，保留用于历史对照。
- [`docs/system-boundaries.md`](docs/system-boundaries.md)：系统职责边界速查。
- [`docs/debugger-ui.md`](docs/debugger-ui.md)：Service Debugger UI 与 artifact 展示范围。
- [`docs/roadmap.md`](docs/roadmap.md)：阶段顺序与 MVP 完成标准。
- [`docs/implementation.md`](docs/implementation.md)：各 Phase 实现记录。

> 旧的 Scala/http4s 和 local process 方案已废弃，不再作为当前架构。