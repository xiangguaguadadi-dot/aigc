# Video-to-3D Mesh Pipeline

> 从单目视频重建物体 3D 网格，输出可用于物理仿真的 GLB 资产。

---

## 1. 项目目标

输入一段手机拍摄的**物体环绕视频**（绕物体走半圈以上），输出：

- `outputs/<session_id>/export/<asset_id>.glb` — 标准化网格
- `outputs/<session_id>/preview/preview.png` — 渲染预览
- `outputs/<session_id>/asset_manifest.json` — 完整资产清单

技术路线：多视角深度融合（非 TripoSR 逐帧独立推理），参考 D4RT 思路但使用现成组件拼装。

参考论文：D4RT — *Efficiently Reconstructing Dynamic Scenes One D4RT at a Time* (Google DeepMind, arXiv 2512.08924v2)。

---

## 2. 架构（8 阶段）

```
输入视频
  │
  ▼
Stage 1: 帧提取 + 质量评估     OpenCV → 均匀采样 → Laplacian 锐度评分
  │                             选择最清晰的 N 帧（默认 6）
  ▼
Stage 2: 背景去除               rembg → 前景 RGBA + 二值蒙版
  │
  ▼
Stage 3: 相机位姿估计           原始帧 SIFT 特征 → FLANN 匹配 →
  │                             本质矩阵分解 → 增量式全局对齐
  ▼
Stage 4: 深度估计               DepthAnythingV2-Small → 逐帧深度图
  │                             (CPU only, 2-5 秒/帧)
  ▼
Stage 5: 点云融合               反投影 → 世界坐标变换 →
  │                             统计离群点去除 → 体素下采样
  ▼
Stage 6: 表面重建               Open3D Poisson 重建 →
  │                             移除小分量 → Taubin 平滑 → 减面(50k)
  ▼
Stage 7: Blender 标准化         导入 → 居中 + 底部 z=0 →
  │                             导出 GLB + Cycles 渲染预览
  ▼
Stage 8: 资产清单               asset_manifest.json + 日志
```

## 3. 运行环境（Windows 11）

```
OS:               Windows 11 Home China
Python:           3.10.20 (conda env: x)
PyTorch:          2.13.0 CPU-only (无 NVIDIA GPU)
Blender:          4.5.11 LTS → C:\Users\NewUser\Applications\blender-4.5.11-windows-x64\blender.exe
open3d:           0.19.0
rembg:            2.0.69
transformers:     4.35.0
Depth Model:      depth-anything/Depth-Anything-V2-Small-hf
```

## 4. 项目文件结构

```
video_to_3d/
├── __init__.py                  # 包入口
├── config.py                    # 默认参数、路径配置
├── pipeline.py                  # 主编排器（stage runner + checkpoint）
├── stages/
│   ├── extract_frames.py        # Stage 1: 帧提取 + 质量评估
│   ├── remove_bg.py             # Stage 2: rembg 去背景
│   ├── estimate_camera.py       # Stage 3: SIFT 相机位姿估计
│   ├── estimate_depth.py        # Stage 4: DepthAnythingV2
│   ├── fuse_pointcloud.py       # Stage 5: 点云融合
│   ├── reconstruct_mesh.py      # Stage 6: Poisson 重建
│   └── triposr_compare.py       # 可选: TripoSR 独立比较
├── blender/
│   └── normalize.py             # Stage 7: Blender 后台标准化
├── utils/
│   ├── camera.py                # 投影/反投影, 相机模型
│   ├── geometry.py              # Umeyama对齐, 包围盒, 归一化
│   ├── io.py                    # 文件读写 (PLY/NPY/PNG)
│   ├── validation.py            # 逐阶段质量检查
│   └── manifest.py              # 资产清单生成
├── quality/
│   ├── sharpness.py             # Laplacian 方差评分
│   └── coverage.py              # 角度覆盖估算
└── scripts/
    └── run_video_to_3d.py       # CLI 入口
```

## 5. 运行命令

```bash
conda activate x
python -m video_to_3d.scripts.run_video_to_3d --video 物体视频.mp4
python -m video_to_3d.scripts.run_video_to_3d --video 物体视频.mp4 --frames 8 --force
python -m video_to_3d.scripts.run_video_to_3d --video 物体视频.mp4 --asset-id my_chair_001
```

## 6. 输出目录协议

```
outputs/<session_id>/
├── selected/                    # 选中的关键帧 + 去背景 + 蒙版
├── depth/                       # 深度图
├── cameras.json                 # 相机位姿
├── pointcloud/                  # 点云
├── mesh/                        # 重建网格
├── blender/                     # Blender 产物
├── export/<session_id>.glb      # 最终输出
├── preview/preview.png          # 预览图
├── logs/pipeline.log            # 日志
├── asset_manifest.json          # 资产清单
└── stage_checkpoints.json       # 断点恢复
```

## 7. 坐标与物理属性约定

```
坐标系:     右手系 +Z 向上
长度:       米（但 scale_status: unscaled）
四元数:     [x, y, z, w]
Provenance: estimated
```

所有输出以 `unscaled` 标记，不伪造真实尺度。

## 8. 已知限制

- **CPU-only**：深度模型使用 Small 版本，帧数限制 4-6
- **无度量尺度**：输出归一化到单位包围盒
- **SIFT 相机估计在弱纹理物体上可能失败**
- **TripoSR 比较路径**需要单独配置
- **场景级重建**（Phase B）尚未实现
