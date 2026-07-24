# AIGC 3D Reconstruction and Robot Interaction

从单张图片、多视角图片或视频生成 3D 资产，并将资产接入 PyBullet 与 Blender，完成实例分离、物理仿真和机器人实时交互。

## 项目结构

```text
aigc/
|-- 01_TRELLIS2_core/   # TRELLIS2 感知、重建、物理、仿真与交互流水线
|-- 02_ComfyUI_current/ # ComfyUI 工作流集成
|-- 03_3Dchannel/       # Tripo 与 Blender 3D 通道工具
|-- 04_tool/            # 图片转 3D 应用工具
|-- generate_3Dmodel/   # 单图转 3D 代码与示例资产
|-- video_to_3d/        # 视频转 3D 网格流水线
`-- simulation/         # PyBullet + Blender 机器人交互系统
```

## TRELLIS2 图片转 3D

```bash
cd 01_TRELLIS2_core
pip install -r requirements.txt
python app.py
```

`01_TRELLIS2_core/modules/` 包含五个阶段：感知、重建、物理属性、仿真和交互。服务器部署说明见 [SETUP_SERVER.md](01_TRELLIS2_core/docs/SETUP_SERVER.md)。

其他入口：

```bash
cd 03_3Dchannel
pip install -r requirements.txt
python pipeline.py
```

```bash
cd 04_tool
python start_img23d.py
```

## 视频转 3D

手机平稳环绕物体拍摄 10 至 30 秒视频，建议覆盖 180 至 360 度，并保持光线均匀、背景简单。

```bash
conda activate x
python -m video_to_3d.scripts.run_video_to_3d --video chair.mp4
```

常用参数：

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--video` / `-i` | 输入视频路径 | 必填 |
| `--frames` / `-n` | 关键帧数量 | `6` |
| `--asset-id` / `-a` | 自定义资产 ID | 自动生成 |
| `--output-root` / `-o` | 输出目录 | `outputs/` |
| `--force` / `-f` | 覆盖已有输出 | 否 |
| `--target-faces` | 目标网格面数 | `50000` |

输出结构：

```text
outputs/<session_id>/
|-- export/<session_id>.glb
|-- preview/preview.png
`-- asset_manifest.json
```

## 机器人实时交互

使用已有 GLB 启动桌面物体交互：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --object "generate_3Dmodel\generate_3Dmodel\output_apple.glb" `
  --object-scale 0.06 `
  --object-mass 0.18 `
  --object-friction 0.6
```

系统使用 PyBullet 计算 Panda 机械臂的力矩控制、碰撞、摩擦和接触力，通过 Blender 插件实时显示机器人、物体、6D 抓取候选和 Target 操作。

完整说明见 [LIVE_INTERACTION.md](simulation/LIVE_INTERACTION.md)。

## 自动多物体交互

将一个包含多个实体的 GLB 自动拆分为独立物理对象：

```powershell
python -m simulation.scripts.prepare_interactive_scene `
  --input scene.glb `
  --output outputs\prepared_scene `
  --target-max-dimension 1.0

python -m simulation.scripts.launch_live_interaction `
  --scene-profile floor `
  --scene-manifest outputs\prepared_scene\scene_manifest.json
```

场景清单记录各实体的尺寸、质量和摩擦估计区间、属性来源与置信度。动作是否允许由几何、接触受力、机器人负载、IK 可达性和碰撞路径共同决定。

## 环境说明

- TRELLIS2 推荐 Python 3.10+、CUDA 12.1+ 和兼容 GPU。
- 视频重建与机器人仿真使用 Conda 环境 `x`。
- Blender 实时交互已针对 Blender 4.5 验证。
- 模型权重、运行输出和本地环境文件不提交到 Git。

## 相关文档

- [项目开发说明](CLAUDE.md)
- [机器人实时交互](simulation/LIVE_INTERACTION.md)
- [TRELLIS2 服务端部署](01_TRELLIS2_core/docs/SETUP_SERVER.md)
- [TRELLIS2](https://github.com/microsoft/TRELLIS)
