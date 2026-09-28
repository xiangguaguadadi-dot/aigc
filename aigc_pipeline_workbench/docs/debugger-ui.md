# Service Debugger UI

完整页面结构、组件规划与 MVP 流程见 [`mvp-architecture.md`](mvp-architecture.md)。本文只保留 UI 信息架构和展示范围。

## 页面定位

主界面是通用 Service Debugger，不是每个算法一套专属页面。

三个入口只作为服务筛选视图：

```text
/debug/asset-generation
/debug/physics-authoring
/debug/physics-engine
```

| 入口 | 主要模块 |
| --- | --- |
| 3D 资产生成层 | segmentation、image-to-3D、texture、GLB export |
| 物理资产构建层 | physics authoring、collider generation |
| 物理引擎测试层 | simulation、robot interaction |

## 基本布局

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

## 核心交互

```text
选择 service
-> 查看 capabilities
-> 选择 input artifact
-> 修改参数
-> Run
-> 轮询 status / logs
-> 查看 output artifact
-> Cancel 或 Rerun
```

Rerun 创建新 job，不覆盖原 job。网络轮询失败时显示 sync stale，不把远端 running job 显示为 failed。

## Artifact 展示范围

| Artifact Type | 第一阶段展示 |
| --- | --- |
| image | 图片预览 |
| mask | 图片预览或 overlay |
| video | 视频播放器 |
| report | JSON / Markdown / 文本 |
| log_file | 文本 |
| mesh | 占位信息，后续接 viewer |
| glb | 占位信息，后续接 3D viewer |
| point_cloud | 占位信息，后续接 viewer |
| physics_asset | metadata 和结构信息 |
| physics_scene | metadata 和结构信息 |
| trajectory | 占位信息，后续接回放 |

所有 artifact 至少展示名称、类型、大小和下载入口。

## 新服务接入

接入新服务时，不新增专属页面。只需要：

1. 服务实现统一 `/v1` 协议；
2. 在 Main Backend 注册服务；
3. 提供 `parameterSchema`；
4. 必要时增加 artifact renderer。
