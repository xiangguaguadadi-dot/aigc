# Video-to-3D Mesh Pipeline

手机环绕物体拍一段视频 → 输出可用于物理仿真的 3D 网格（GLB 格式）。

## 快速开始

```bash
conda activate x
python -m video_to_3d.scripts.run_video_to_3d --video 你的视频.mp4
```

第一次运行会自动下载 DepthAnythingV2 模型（约 90MB）。

## 示例

```bash
# 基本
python -m video_to_3d.scripts.run_video_to_3d --video chair.mp4

# 8 帧，强制覆盖
python -m video_to_3d.scripts.run_video_to_3d --video chair.mp4 --frames 8 --force

# 自定义资产 ID
python -m video_to_3d.scripts.run_video_to_3d --video chair.mp4 --asset-id my_chair_001
```

## 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--video` / `-i` | 输入视频路径 | 必填 |
| `--frames` / `-n` | 关键帧数量 | 6 |
| `--asset-id` / `-a` | 资产 ID（自动生成） | auto |
| `--output-root` / `-o` | 输出根目录 | `outputs/` |
| `--force` / `-f` | 覆盖已有输出 | 否 |
| `--target-faces` | 目标网格面数 | 50000 |
| `--verbose` / `-v` | 详细日志 | 否 |
| `--compare-triposr` | 与 TripoSR 比较 | 否 |

## 拍摄建议

- 物体放在桌面或地面，背景简单
- 手机平稳环绕物体走 **半圈以上**（180°-360°）
- 光线均匀，避免强烈阴影
- 视频长度 10-30 秒
- 不要快速移动手机，避免运动模糊

## 输出

```
outputs/<session_id>/
├── export/<session_id>.glb      # 最终 3D 网格
├── preview/preview.png          # 预览图
└── asset_manifest.json          # 资产清单
```

## 环境要求

- Windows 11
- Conda 环境 `x`（Python 3.10）
- Blender 4.5（已安装）
- 不需要 GPU

## 技术路线

多视角深度融合管线，参考 D4RT 思路：

```
视频 → 帧提取 → 背景去除 → SIFT 相机估计 → DepthAnythingV2 深度 → 点云融合 → Poisson 表面重建 → Blender 标准化 → GLB
```

## 项目文档

- 视频转 3D 总体说明：[CLAUDE.md](CLAUDE.md)
- PyBullet + Blender 实时机器人交互：[simulation/LIVE_INTERACTION.md](simulation/LIVE_INTERACTION.md)

## 自动多物体交互

将合并的未知 GLB 自动拆分为独立物理实体并启动 Blender 实时交互：

```powershell
python -m simulation.scripts.prepare_interactive_scene `
  --input scene.glb `
  --output outputs\prepared_scene `
  --target-max-dimension 1.0

python -m simulation.scripts.launch_live_interaction `
  --scene-profile floor `
  --scene-manifest outputs\prepared_scene\scene_manifest.json
```

预处理结果包含物体尺寸、质量/摩擦估计区间、来源和置信度。Blender 的 `Active Object` 选择决定当前操作对象，动作是否允许仍由 PyBullet 几何、受力和可达性检查决定。
