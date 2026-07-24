# 3D Physics Pipeline

**照片 → 3D场景 → 物理仿真 → 可交互资产**

> CVPR-style modular pipeline: RGB images in, physics-ready interactive 3D scene out.

---

## 快速开始

```bash
git clone https://github.com/YOUR_USERNAME/3d-physics-pipeline.git
cd 3d-physics-pipeline
bash setup.sh
python app_final.py   # 打开 http://localhost:7860
```

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│ Input: RGB Images + COLMAP Poses + Reference Object      │
└─────────────────────────────────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────────┐
    ▼                     ▼                          ▼
┌────────┐    ┌──────────────┐    ┌──────────────────────┐
│  M1    │    │  TRELLIS.2   │    │  COLMAP IO            │
│ 感知   │    │  单图→3D     │    │  位姿解析+尺度校准    │
│ OWL-ViT│    │  (可选)      │    │  colmap_io.py         │
│ + SAM  │    └──────────────┘    └──────────────────────┘
└────────┘
    │ 物体标签 + 掩码
    ▼
┌──────────────────────────────────────────────────────────┐
│  M2: 单物体重建                                           │
│  顶点分离 → 水密网格 → 归一化 → 独立 .glb                 │
└──────────────────────────────────────────────────────────┘
    │ per-object.glb
    ▼
┌──────────────────────────────────────────────────────────┐
│  M3: 物理属性推断                                         │
│  VLM看图 → 材质识别 → 密度查表 → 质量=ρV → 碰撞凸包      │
│  输出: 标准JSON (符合需求文档 §Module 2)                  │
└──────────────────────────────────────────────────────────┘
    │ physics JSON + collision mesh
    ▼
┌──────────────────────────────────────────────────────────┐
│  M4: 场景组装 + 物理仿真                                  │
│  PyBullet: 重力 + 碰撞 + 稳定检测 → 仿真动画              │
└──────────────────────────────────────────────────────────┘
    │ settled state
    ▼
┌──────────────────────────────────────────────────────────┐
│  M5: 交互控制                                             │
│  射线检测 → 抓取 → 拖拽 → 投掷 → 状态同步                │
└──────────────────────────────────────────────────────────┘
    │
    ▼
  🎮 物理交互资产 (.glb + .json + .gif)
```

---

## 核心模块

| 模块 | 功能 | 技术 | 文件 |
|------|------|------|------|
| **M1** | 物体检测+分割 | OWL-ViT + SAM + NMS | `pipeline/module1_perception/` |
| **M2** | 重建+归一化 | Poisson水密/preserve原始 | `pipeline/module2_reconstruction/` |
| **M3** | 物理推断 | Qwen2-VL + 密度LUT | `pipeline/module3_physics/` |
| **引擎** | 尺度+水密+碰撞 | 参照物校准 + 复合凸包 | `pipeline/engineering.py` |
| **规范** | 标准JSON输出 | 完全匹配需求文档 §M2 | `pipeline/spec_compliant.py` |
| **COLMAP** | 位姿解析 | cameras.bin / transforms.json | `pipeline/colmap_io.py` |
| **M4** | 物理仿真 | PyBullet + GIF动画 | `pipeline/module4_simulation/` |
| **M5** | 交互控制 | 射线→约束→速度传递 | `pipeline/module5_interaction/` |
| **生产** | 端到端管线 | 全自动M1→M5 | `pipeline/production.py` |

---

## 标准 JSON 输出格式

每个物体输出完全符合需求文档 §Module 2 规格：

```json
{
  "object_id": "chair_000",
  "category": "wood_chair",
  "material": "wood",
  "confidence": 0.92,
  "physical_params": {
    "density": 700,
    "static_friction": 0.55,
    "dynamic_friction": 0.48,
    "restitution": 0.30,
    "young_modulus": 1.1e10,
    "is_deformable": false
  },
  "geometry_params": {
    "volume": 3.88e-4,
    "mass": 0.27,
    "bounding_box": [0.33, 0.29, 0.24],
    "center_position": [0.0, 0.0, 0.0]
  },
  "spatial_relation": ["on_floor"],
  "interactable": true,
  "static": false
}
```

---

## 输入格式

### 方案 A：纯照片 + COLMAP (当前支持)

```bash
python pipeline/production.py \
  --colmap-dir ./sparse/0/ \
  --reference-object door --reference-size 2.1
```

### 方案 B：ARKit/ARCore (待实现)

直接提供 `transforms.json` + 图像（米制尺度天然准确）。

---

## 材质数据库

| 材质 | 密度(kg/m³) | 静摩擦 | 动摩擦 | 弹性 | 杨氏模量 |
|------|-----------|--------|--------|------|---------|
| wood | 700 | 0.55 | 0.48 | 0.30 | 11 GPa |
| metal | 7800 | 0.40 | 0.35 | 0.15 | 200 GPa |
| ceramic | 2400 | 0.42 | 0.38 | 0.08 | 70 GPa |
| plastic | 1200 | 0.35 | 0.30 | 0.40 | 2.5 GPa |
| fabric | 300 | 0.65 | 0.60 | 0.05 | 10 MPa |
| glass | 2500 | 0.25 | 0.20 | 0.10 | 70 GPa |
| rubber | 1100 | 0.80 | 0.75 | 0.70 | 10 MPa |

---

## 安装

```bash
bash setup.sh
```

### 需要的模型权重

| 模型 | 大小 | 下载 |
|------|------|------|
| SAM ViT-H | 2.4GB | `wget` from HF mirror |
| Qwen2-VL-2B | 4GB | ModelScope |
| OWL-ViT | 600MB | HF mirror (auto) |
| CLIP | 350MB | HF mirror (auto) |

---

## 引用

```bibtex
@misc{3d-physics-pipeline,
  title  = {3D Physics Pipeline: Photo → Interactive 3D Scene},
  author = {Your Name},
  year   = {2026},
  url    = {https://github.com/YOUR_USERNAME/3d-physics-pipeline}
}
```
