"""
输入加载模块
===========
从本地目录加载图片，从视频文件中提取帧。
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

import cv2
from PIL import Image

from config import (
    INPUT_DIR, TEMP_DIR,
    SUPPORTED_IMAGE_FORMATS, SUPPORTED_VIDEO_FORMATS,
    VIDEO_FRAME_INTERVAL,
)


def _is_image(filepath: Path) -> bool:
    """检查文件是否为支持的图片格式"""
    return filepath.suffix.lower() in SUPPORTED_IMAGE_FORMATS


def _is_video(filepath: Path) -> bool:
    """检查文件是否为支持的视频格式"""
    return filepath.suffix.lower() in SUPPORTED_VIDEO_FORMATS


def load_images(source_dir: Optional[str] = None) -> List[Path]:
    """
    扫描目录，返回所有图片文件的路径列表。

    Args:
        source_dir: 图片所在目录，默认为 config.INPUT_DIR

    Returns:
        图片文件路径列表（按文件名排序）
    """
    directory = Path(source_dir) if source_dir else INPUT_DIR

    if not directory.exists():
        raise FileNotFoundError(f"输入目录不存在: {directory}")

    image_paths = sorted(
        p for p in directory.iterdir()
        if p.is_file() and _is_image(p)
    )

    if not image_paths:
        raise FileNotFoundError(f"目录中没有找到支持的图片文件: {directory}")

    print(f"[input_loader] Found {len(image_paths)} images in {directory}")
    return image_paths


def extract_frames(
    video_path: str,
    output_dir: Optional[str] = None,
    interval: int = VIDEO_FRAME_INTERVAL,
) -> List[Path]:
    """
    从视频文件中每隔 interval 帧提取一张图片。

    Args:
        video_path: 视频文件路径
        output_dir: 帧输出目录，默认为 TEMP_DIR
        interval: 提取间隔（每隔多少帧取一张）

    Returns:
        提取的帧图片路径列表
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    if not _is_video(video):
        raise ValueError(f"不支持的视频格式: {video.suffix}")

    out_dir = Path(output_dir) if output_dir else TEMP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"[input_loader] Video: {video.name}")
    print(f"  Frames: {total_frames}, FPS: {fps:.2f}, Duration: {total_frames/fps:.1f}s")
    print(f"  Extract every {interval} frames")

    frame_paths = []
    frame_idx = 0
    saved_count = 0

    video_stem = video.stem

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % interval == 0:
            # OpenCV 读的是 BGR，转成 RGB 保存
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)

            out_name = f"{video_stem}_frame{frame_idx:06d}.png"
            out_path = out_dir / out_name
            pil_image.save(str(out_path))
            frame_paths.append(out_path)
            saved_count += 1

        frame_idx += 1

    cap.release()
    print(f"[input_loader] Extracted {saved_count} frames to {out_dir}")
    return frame_paths


def load_all_media(
    source_dir: Optional[str] = None,
    video_interval: int = VIDEO_FRAME_INTERVAL,
) -> List[Path]:
    """
    加载目录中的所有媒体文件（图片 + 视频帧）。

    - 图片文件直接添加
    - 视频文件提取帧后添加
    - 结果统一放在 TEMP_DIR 下

    Args:
        source_dir: 媒体目录，默认 INPUT_DIR
        video_interval: 视频帧提取间隔

    Returns:
        所有可用的图片路径列表
    """
    directory = Path(source_dir) if source_dir else INPUT_DIR

    if not directory.exists():
        raise FileNotFoundError(f"输入目录不存在: {directory}")

    all_images: List[Path] = []

    for filepath in sorted(directory.iterdir()):
        if not filepath.is_file():
            continue

        if _is_image(filepath):
            all_images.append(filepath)

        elif _is_video(filepath):
            frames = extract_frames(str(filepath), interval=video_interval)
            all_images.extend(frames)

    if not all_images:
        raise FileNotFoundError(f"目录中没有找到支持的媒体文件: {directory}")

    print(f"[input_loader] 总共加载 {len(all_images)} 张图片")
    return all_images


def cleanup_temp():
    """清理临时目录"""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        print("[input_loader] 临时文件已清理")


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        source = sys.argv[1]
    else:
        source = None

    try:
        images = load_all_media(source)
        print(f"\n✅ 加载成功，共 {len(images)} 张图片:")
        for img in images:
            print(f"  - {img}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("提示: 把图片/视频放到 input/ 目录，或传参指定路径")
