"""VLM API client for the first physical-modeling pipeline step."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from physical_agent.domain.task.physical_model_card import (
    CardValidationError,
    validate_physical_model_card,
)


DEFAULT_API_URL = "https://token.matpool.com/v1/chat/completions"
DEFAULT_MODEL = "Qwen3-VL-Flash"
DEFAULT_ENV_FILES = (".env.local", ".env")
MAX_ERROR_BODY_CHARS = 1000


SYSTEM_PROMPT = """你是一个物理建模解析器。你的任务是把图片和用户问题解析为 Physical Model Card。

只能选择以下 model.family:
- rigid_body
- articulated_rigid_body
- elastic_rod

只能选择以下 model.geometry:
- sphere
- box
- cylinder
- rod

必须遵守：
1. 无法从图片确认的信息必须放入 unknown。
2. 禁止把推测信息写入 observed。
3. 禁止编造精确物理参数；参数只能作为候选假设。
4. 第一版只支持单物体；若看到多物体，object_count 写真实数量，并在 unknown 中说明需要用户裁剪。
5. 只输出一个合法 JSON 对象，不要 Markdown，不要解释文字。

JSON 格式：
{
  "task": {
    "question": "用户问题原文",
    "target_quantity": "trajectory|velocity|acceleration|collision|deformation|rotation|unknown"
  },
  "observed": {
    "object_count": 1,
    "object_type": "sphere|box|cylinder|rod|door|drawer|pendulum|hinged_rod|unknown",
    "support_surface": "ground|inclined_plane|table|wall|hanging|unknown",
    "approximate_color": "颜色或 unknown"
  },
  "assumed": {
    "material_class": "rubber|plastic|wood|metal|glass|unknown",
    "scale_source": "user_input|visual_guess|normalized|unknown",
    "joint_type": "none|hinge|slider|unknown"
  },
  "unknown": ["mass", "friction", "restitution"],
  "model": {
    "family": "rigid_body",
    "geometry": "sphere",
    "radius": 0.1
  },
  "parameter_hypotheses": [
    {
      "name": "hypothesis_name",
      "mass": 0.3,
      "friction": 0.6,
      "restitution": 0.5,
      "confidence": 0.5
    }
  ],
  "follow_up_question": "最有价值的一个补充问题"
}
"""


def image_to_data_url(image_path: Path) -> str:
    """Read an image file and convert it to a data URL for chat APIs."""

    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type is None or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_messages(question: str, image_data_url: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
    """Build OpenAI-compatible chat messages with text and image content."""

    user_text = question.strip()
    if context:
        user_text += f"\n\n补充信息：{context.strip()}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def call_vlm_api(
    messages: List[Dict[str, Any]],
    api_key: str,
    api_url: str = DEFAULT_API_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    request = urllib.request.Request(
        normalize_chat_completions_url(api_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        if len(error_body) > MAX_ERROR_BODY_CHARS:
            error_body = error_body[:MAX_ERROR_BODY_CHARS] + "...<truncated>"
        raise RuntimeError(f"VLM API returned HTTP {error.code}: {error_body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"VLM API request failed: {error.reason}") from error

    data = json.loads(body)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unexpected VLM API response shape: {body}") from error


def normalize_chat_completions_url(api_url: str) -> str:
    """Accept either a full chat completions URL or an OpenAI-compatible base URL."""

    stripped = api_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        return stripped
    if stripped.endswith("/v1") or stripped.endswith("/compatible-mode/v1"):
        return f"{stripped}/chat/completions"
    return stripped


def parse_json_response(text: str) -> Dict[str, Any]:
    """Parse a VLM response that should contain exactly one JSON object."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("VLM response JSON must be an object")
    return parsed


def analyze_image(
    image_path: Path,
    question: str,
    context: Optional[str],
    api_key: str,
    api_url: str,
    model: str,
) -> Dict[str, Any]:
    """Run image/question analysis and return a validated Physical Model Card."""

    messages = build_messages(question, image_to_data_url(image_path), context)
    raw_response = call_vlm_api(messages, api_key=api_key, api_url=api_url, model=model)
    card = parse_json_response(raw_response)
    return validate_physical_model_card(card)


def load_api_key() -> str:
    """Load VLM API key from the environment."""

    api_key = os.getenv("VLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set VLM_API_KEY before calling the VLM API.")
    return api_key


def load_env_files(root: Path) -> None:
    """Load simple KEY=VALUE pairs from local env files without extra deps."""

    for name in DEFAULT_ENV_FILES:
        path = root / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def main(argv: Optional[List[str]] = None) -> int:
    load_env_files(Path.cwd())

    parser = argparse.ArgumentParser(description="Run VLM parsing for one object image.")
    parser.add_argument("--image", required=True, type=Path, help="Path to a cropped single-object image.")
    parser.add_argument("--question", required=True, help="Natural-language physics question.")
    parser.add_argument("--context", default=None, help="Optional size, mass, material, or force information.")
    parser.add_argument("--api-url", default=os.getenv("VLM_API_URL", DEFAULT_API_URL))
    parser.add_argument("--model", default=os.getenv("VLM_MODEL", DEFAULT_MODEL))
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args(argv)

    try:
        card = analyze_image(
            image_path=args.image,
            question=args.question,
            context=args.context,
            api_key=load_api_key(),
            api_url=args.api_url,
            model=args.model,
        )
    except (OSError, RuntimeError, ValueError, CardValidationError) as error:
        print(f"vlm parse failed: {error}", file=sys.stderr)
        return 1

    output = json.dumps(card, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
