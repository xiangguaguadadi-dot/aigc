# 开发路线图

各阶段具体任务与协议字段见 [mvp-architecture.md](mvp-architecture.md)。本文维护阶段顺序和当前状态。

## 阶段总览

| Phase | 目标 | 状态 |
| --- | --- | --- |
| 1 | 协议与类型 | Completed |
| 2 | Main Backend 最小骨架 | Completed |
| 3 | Mock GPU Service | Completed |
| 4 | Service Registry + Job Manager | Completed |
| 5 | E2E Integration & Runtime Hardening | Completed |
| 6 | Frontend MVP | Completed |
| 7 | Module Studio & Generic Workbench | Completed |
| 8 | TBD - 启动前明确范围 | Not started |
| 9 | Workflow / Pipeline | Deferred |

## 已固定基线

Phase 7 已关闭并固化为当前基线：

- ModuleDefinition 与 AlgorithmService 分离。
- Module CRUD、兼容性检查、module-aware job 已稳定。
- Module Studio 与 Generic Module Workbench 已可用。
- artifact metadata.output_slot 已成为前端输出映射依据。
- 默认 frontend demo job 可在无 GPU service 时验证核心 UI 链路。
- Frontend production build、backend/mock 回归、HTTP E2E 和重启持久化均已通过。
- Workflow / DAG 仍然明确排除在 MVP 之外。

## 进入 Phase 8 的约束

- 必须先明确 Phase 8 的目标和验收范围。
- 不得默认开始 WorkflowRun、WorkflowStep、dependsOn、自动提交、step retry 或 DAG engine。
- 不得破坏既有边界：Frontend 只访问 Main Backend；artifact 文件与 storage_key 不跨服务边界。
- 优先评估 submitting recovery、terminal-state validation、polling failure recovery 和 timeout enforcement。

## MVP 完成标准

`	ext
注册 Service -> 查看 health / capabilities
创建 / 选择 Module -> 上传 required inputs -> 修改参数
Submit Job -> running / progress / logs -> output artifacts 与 slot mapping
rerun / cancel long job
`

## 暂缓项

- WorkflowRun；WorkflowStep；dependsOn；自动提交；step retry；workflow status。
- Kubernetes；Kafka；Redis；Celery；PostgreSQL；完整 DAG engine。
