# Physical Modeling Agent

目标：构建一条“图片与问题 -> 物理模型 -> 仿真 -> 检查与修正”的 MVP 链路。

## 图片到 Blender 视觉资产

当前开源视觉资产链路为：

```text
单物体图片
→ rembg 去背景
→ TripoSR 生成三维网格
→ Blender 后台标准化
→ GLB 往返验证
→ 预览图和资产清单
```

### 拖拽运行（macOS）

1. 把一张单主体图片拖入 `drop_images/`。
2. 在 Finder 中双击仓库根目录的 `run_image_to_3d.command`。
3. 等待终端显示生成成功。
4. Blender 会自动打开生成的三维模型。

脚本会为每次运行创建带时间戳的资产 ID，不覆盖已有资产。

如果 macOS 首次阻止运行，在 Finder 中右键 `run_image_to_3d.command`，选择“打开”，再确认一次。不要关闭生成过程中出现的终端窗口。

终端中也可以直接调用拖拽启动器：

```bash
./run_image_to_3d.command path/to/object.png
```

在仓库根目录运行：

```bash
.venv/bin/python scripts/run_visual_asset_pipeline.py \
  --image lounge-pug-josephine-sofa-beads-cushion-pompon-aegean-blue_LPJOSOFAPPAG_01_550x550.webp \
  --asset-id josephine_sofa_test
```

成功后结果位于：

```text
assets/josephine_sofa_test/
├── source/                 # 原图副本
├── preprocessed/           # 去背景结果和模型输入
├── generated/raw.glb       # TripoSR 原始输出
├── blender/normalized.blend
├── export/josephine_sofa_test.glb
├── preview/preview.png
├── logs/
└── asset_manifest.json
```

默认行为：

- 自动选择 CUDA、MPS 或 CPU；
- Apple MPS 负责神经网络推理，marching-cubes 自动在 CPU 执行；
- 使用 `128` 网格分辨率验证链路；
- 对 TripoSR 输出应用 `X=-90°` 的 Blender 轴修正；
- 不推测真实物理尺寸；
- 如果资产目录已经存在则停止，不会静默覆盖。

重新生成同一个资产时显式使用：

```bash
.venv/bin/python scripts/run_visual_asset_pipeline.py \
  --image path/to/object.png \
  --asset-id object_001 \
  --force
```

常用参数：

```text
--device cpu|mps|cuda|auto
--mc-resolution 128
--chunk-size 4096
--foreground-ratio 0.85
--rotate-x-degrees -90
--output-root assets
```

可以通过 `TRIPOSR_SOURCE`、`TRIPOSR_MODEL_DIR` 和 `BLENDER_BIN` 环境变量覆盖本机安装路径。输入必须是单主体图片；最终 GLB 是视觉资产，不能直接作为碰撞体或质量计算网格。

当前先完成第一步：通过 VLM API 把单物体图片和自然语言问题解析成受约束的
`Physical Model Card` JSON。

## VLM API 配置

本项目默认使用 OpenAI-compatible Chat Completions 接口：

- `VLM_API_URL`: `https://token.matpool.com/v1/chat/completions`
- `VLM_MODEL`: `Qwen3-VL-Flash`
- `VLM_API_KEY`: 你的 API key

`.env.example` 给出了变量名。真实 key 不应提交到 git。
CLI 会自动读取 `.env.local` 或 `.env` 中的这些变量。

## 运行 VLM 解析

```bash
export VLM_API_KEY="your_api_key"
export VLM_API_URL="https://token.matpool.com/v1/chat/completions"
export VLM_MODEL="Qwen3-VL-Flash"

python3 scripts/run_vlm_parse.py \
  --image examples/ball_on_slope/example.png \
  --question "球从斜面上释放后会怎样运动？" \
  --context "球的直径约为 20 cm" \
  --output outputs/physical_model_card.json
```

输出 JSON 会经过本地校验，确保模型类别、几何、参数范围等满足第一版 MVP 的约束。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover tests/unit
```
