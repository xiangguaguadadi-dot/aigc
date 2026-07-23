# TRELLIS.2 → 3D Physics Pipeline

**单张照片 → 3D 模型 → 语义分割 → 物理仿真 → 交互操作**

CVPR-style modular pipeline: one photo in, physics-ready interactive asset out.

---

## 快速开始

```bash
git clone https://github.com/YOUR_USERNAME/trellis2-3d-pipeline.git
cd trellis2-3d-pipeline

# 1. 安装环境 + 下载权重 (约 25GB)
bash setup.sh

# 2. 生成 3D 模型 (TRELLIS.2)
python pre-model/generate.py 你的照片.jpg -o output/model.glb

# 3. 全流程管线 (感知 → 重建 → 物理 → 仿真 → 交互)
python run_pipeline.py --image 你的照片.jpg --output ./results

# 4. Web 演示
python app.py
# 打开 http://localhost:7860
```

---

## 模块架构

```
📷 照片
  │
  ▼
┌──────────────────────────────────────────────┐
│  TRELLIS.2  (pre-model/)                     │
│  单张图片 → 带 PBR 材质的 3D .glb 网格        │
└──────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────┐
│  Module 1: Perception & Segmentation          │
│  OWL-ViT + SAM → 语义标签 + 实例掩码           │
└──────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────┐
│  Module 2: Object-Centric Reconstruction      │
│  Poisson 水密网格 → 独立物体 .glb 资产         │
└──────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────┐
│  Module 3: Physical Parameter Inference       │
│  CLIP材质 + 密度LUT + 凸包碰撞体               │
└──────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────┐
│  Module 4: Scene Assembly & Physics           │
│  PyBullet 场景组装 → 重力仿真 → 稳定状态       │
└──────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────┐
│  Module 5: Interaction Controller             │
│  射线检测 + 抓取 + 拖拽 + 投掷                 │
└──────────────────────────────────────────────┘
  │
  ▼
  🎮 物理交互资产 (.glb + .json)
```

---

## 项目结构

```
├── README.md
├── setup.sh / setup.bat        # 一键安装
├── requirements.txt
├── app.py                      # Gradio Web 界面
├── config.yaml                 # 全局配置
│
├── pre-model/                  # TRELLIS.2 推理
│   ├── generate.py             #   主推理脚本
│   ├── post_process.py         #   后处理 (色彩校准)
│   └── download_weights.py     #   权重下载
│
├── pipeline/                   # 五大模块
│   ├── module1_perception/     #   感知与分割
│   ├── module2_reconstruction/ #   单物体重建
│   ├── module3_physics/        #   物理属性
│   ├── module4_simulation/     #   场景仿真
│   └── module5_interaction/    #   交互控制
│
├── run_pipeline.py             # 全流程一键运行
└── docs/                       # 论文文档
```

---

## 硬件要求

| 组件 | 最低 | 推荐 |
|------|------|------|
| GPU | 16GB VRAM | 40GB+ (A100) |
| RAM | 32GB | 64GB |
| 磁盘 | 30GB | 50GB+ |

---

## 引用

```bibtex
@misc{trellis2-3d-pipeline,
  title  = {TRELLIS.2 → 3D Physics Pipeline},
  author = {Your Name},
  year   = {2026},
  url    = {https://github.com/YOUR_USERNAME/trellis2-3d-pipeline}
}
```

## License

MIT
