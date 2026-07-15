#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
PIPELINE_SCRIPT="$SCRIPT_DIR/scripts/run_visual_asset_pipeline.py"
DROP_DIR="$SCRIPT_DIR/drop_images"
BLENDER_APP="$HOME/Applications/Blender.app"
OUTPUT_ROOT="$SCRIPT_DIR/assets"
DRY_RUN=0

pause_if_interactive() {
  if [[ -t 0 ]]; then
    printf '\n按回车键关闭此窗口...'
    read -r
  fi
}

fail() {
  printf '\n错误：%s\n' "$1" >&2
  pause_if_interactive
  exit 1
}

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

[[ -x "$PYTHON_BIN" ]] || fail "找不到项目 Python 环境：$PYTHON_BIN"
[[ -f "$PIPELINE_SCRIPT" ]] || fail "找不到流程脚本：$PIPELINE_SCRIPT"
[[ -d "$BLENDER_APP" ]] || fail "找不到 Blender：$BLENDER_APP"

mkdir -p "$DROP_DIR"

if (( $# > 0 )); then
  IMAGE_PATH="${1:A}"
else
  IMAGE_PATH="$($PYTHON_BIN - "$DROP_DIR" <<'PY'
from pathlib import Path
import sys

folder = Path(sys.argv[1])
extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
images = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in extensions]
if images:
    print(max(images, key=lambda path: path.stat().st_mtime).resolve())
PY
)"
fi

[[ -n "$IMAGE_PATH" ]] || fail "没有找到图片。请把图片放进 $DROP_DIR 后再双击脚本。"
[[ -f "$IMAGE_PATH" ]] || fail "图片不存在：$IMAGE_PATH"

case "${IMAGE_PATH:e:l}" in
  png|jpg|jpeg|webp|bmp|tif|tiff) ;;
  *) fail "不支持的图片格式：${IMAGE_PATH:e}" ;;
esac

STEM="${IMAGE_PATH:t:r:l}"
SAFE_STEM="$(printf '%s' "$STEM" | sed -E 's/[^a-z0-9_-]+/_/g; s/^[_-]+//; s/[_-]+$//')"
[[ -n "$SAFE_STEM" ]] || SAFE_STEM="asset"
SAFE_STEM="$(printf '%s' "$SAFE_STEM" | cut -c1-64)"
ASSET_ID="${SAFE_STEM}_$(date '+%Y%m%d_%H%M%S')"
ASSET_DIR="$OUTPUT_ROOT/$ASSET_ID"
BLEND_FILE="$ASSET_DIR/blender/normalized.blend"

printf '\n图片：%s\n' "$IMAGE_PATH"
printf '资产 ID：%s\n' "$ASSET_ID"
printf '输出目录：%s\n\n' "$ASSET_DIR"

if (( DRY_RUN )); then
  printf 'DRY RUN：环境与输入检查通过，未执行生成。\n'
  exit 0
fi

cd "$SCRIPT_DIR"
"$PYTHON_BIN" "$PIPELINE_SCRIPT" \
  --image "$IMAGE_PATH" \
  --asset-id "$ASSET_ID" \
  --output-root "$OUTPUT_ROOT"

[[ -f "$BLEND_FILE" ]] || fail "流程结束但没有生成 Blender 文件：$BLEND_FILE"

printf '\n生成成功，正在用 Blender 打开三维模型...\n'
open -a "$BLENDER_APP" "$BLEND_FILE"

printf '三维模型：%s\n' "$BLEND_FILE"
printf '渲染预览：%s\n' "$ASSET_DIR/preview/preview.png"
printf '资产清单：%s\n' "$ASSET_DIR/asset_manifest.json"

pause_if_interactive
