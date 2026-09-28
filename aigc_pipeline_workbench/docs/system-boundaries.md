# 系统职责边界

完整架构、协议、数据模型和字段定义见 [`mvp-architecture.md`](mvp-architecture.md)。本文只做职责边界速查。

## 总体边界

```text
Frontend Debugger
-> Main Backend / Orchestrator / API Gateway
-> GPU Microservices
-> Artifact / Object Storage
```

## Frontend Debugger

职责：

- 展示服务、health、capabilities；
- 渲染参数表单；
- 提交、取消、重跑 job；
- 展示状态、progress、logs、artifacts。

禁止：

- 直接访问 GPU Service；
- 使用服务内部路径；
- 维护任务状态机；
- 拼接算法命令。

## Main Backend

技术栈：FastAPI + SQLite。

职责：

- Service Registry；
- Job Manager；
- 状态聚合；
- 日志聚合；
- Artifact metadata；
- Public API；
- Internal Artifact API。

禁止：

- 模型推理；
- spawn local Python process；
- 理解算法内部细节；
- 直接读写 GPU Service 文件系统；
- 在 route 中写业务规则。

## GPU Microservice

职责：

- 实现统一 `/v1` 协议；
- 下载 artifact URL；
- 执行算法；
- 返回 job 状态、progress、logs、output artifacts；
- 尽力支持 cancel。

禁止：

- 直接写 Main Backend 数据库；
- 更新前端状态；
- 与其他 GPU Service 直接互传大文件；
- 返回内部文件路径；
- 自行扩展核心状态枚举。

## Artifact Store

职责：

- 保存输入、中间产物和结果；
- 提供 upload / download 边界；
- 管理 artifact metadata；
- 为前端提供预览或下载 URL。

第一阶段由 Main Backend 实现 `LocalArtifactStore`，未来可替换为 S3 / MinIO。核心协议只依赖：

```text
artifact_id
metadata
download URL
upload URL
preview URL
```

禁止暴露 `storage_key` 或服务内部文件路径。

## State Store

第一阶段使用 SQLite：

```text
services
jobs
job_logs
artifacts
```

持久化访问只放在 repository 层，route 不直接写 SQL。

## 第一阶段非目标

不引入：

- Kubernetes；
- Kafka；
- Redis；
- Celery；
- PostgreSQL；
- 完整 DAG engine；
- Service Mesh；
- 用户系统和复杂权限。
