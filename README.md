# Physical Modeling Agent

目标：构建一条“图片与问题 -> 物理模型 -> 仿真 -> 检查与修正”的 MVP 链路。

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
