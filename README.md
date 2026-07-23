# AIGC - AI 3D Content Generation

基于 TRELLIS2 的 AI 3D 内容生成项目，涵盖从单张图片到 3D 模型生成、物理仿真与交互的完整流程。

## 项目结构

```
uestc-2025/
├── 01_TRELLIS2_core/       # TRELLIS2 核心流水线
│   ├── modules/            # 五大模块
│   │   ├── module1_perception/      # 模块1: 感知 (检测/分割/深度估计)
│   │   ├── module2_reconstruction/  # 模块2: 重建 (网格/分离/导出)
│   │   ├── module3_physics/         # 模块3: 物理 (材质/物理属性)
│   │   ├── module4_simulation/      # 模块4: 仿真 (场景/模拟器)
│   │   └── module5_interaction/     # 模块5: 交互 (控制器/交互逻辑)
│   ├── pre_model/          # 预训练模型下载与推理
│   ├── release/            # 发布版本
│   ├── inputs/             # 输入图片
│   ├── outputs/            # 输出 3D 模型 (.glb)
│   ├── docs/               # 文档
│   └── app.py              # 主入口
├── 02_ComfyUI_current/     # ComfyUI 工作流集成
│   └── workflows/trellis2-advanced/  # TRELLIS2 高级工作流
├── 03_3Dchannel/           # 3D 通道工具
│   ├── tripo_client.py     # Tripo API 客户端
│   ├── blender_sim.py      # Blender 仿真
│   └── pipeline.py         # 处理流水线
└── 04_tool/                # 应用工具
    ├── app_img23d.py       # 图片转 3D 应用
    └── app_demo.py         # Demo 应用
```

## 快速开始

### 01_TRELLIS2_core

```bash
cd 01_TRELLIS2_core
pip install -r requirements.txt
python app.py
```

### 03_3Dchannel

```bash
cd 03_3Dchannel
pip install -r requirements.txt
python pipeline.py
```

### 04_tool

```bash
cd 04_tool
bash start_img23d.sh
```

## 环境要求

- Python 3.10+
- CUDA 12.1+ (推荐，用于 GPU 加速)
- 详见各模块的 `requirements.txt`

## 相关链接

- [TRELLIS2](https://github.com/microsoft/TRELLIS) - Microsoft 3D 生成模型
