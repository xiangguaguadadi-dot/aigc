"""
3D Pipeline 主编排器
==================
串联完整的 3D 管线流程:

  图片/视频 → Tripo API(图片→GLB) → Blender(刚体物理仿真) → 渲染结果

用法:
  python pipeline.py                          # 使用默认配置
  python pipeline.py --input ./my_photos      # 指定输入目录
  python pipeline.py --skip-tripo              # 跳过 Tripo 转换（已有 GLB）
  python pipeline.py --skip-sim                # 跳过仿真（只做转换）
"""

import asyncio
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Fix Windows GBK encoding for emoji output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 添加项目目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    INPUT_DIR, OUTPUT_DIR, MODELS_DIR, RENDERS_DIR, BLEND_DIR, TEMP_DIR,
    BLENDER_EXECUTABLE,
)
from input_loader import load_all_media, cleanup_temp


# ============================================================
# 辅助函数
# ============================================================

def find_blender() -> str:
    """查找 Blender 可执行文件"""
    if BLENDER_EXECUTABLE:
        blender = Path(BLENDER_EXECUTABLE)
        if blender.exists():
            return str(blender)

    # 尝试常见路径
    candidates = []

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Blender.app/Contents/MacOS/Blender",
        ]
    else:
        candidates = [
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/opt/blender/blender",
        ]

    for c in candidates:
        if Path(c).exists():
            return c

    # 最后尝试 PATH 中的 blender
    if shutil.which("blender"):
        return "blender"

    raise FileNotFoundError(
        "找不到 Blender！请:\n"
        "  1. 安装 Blender: https://www.blender.org/download/\n"
        "  2. 在 config.py 中设置 BLENDER_EXECUTABLE 为完整路径"
    )


def find_blender_script() -> Path:
    """查找 blender_sim.py 的路径"""
    script = Path(__file__).parent / "blender_sim.py"
    if not script.exists():
        raise FileNotFoundError(f"找不到仿真脚本: {script}")
    return script


def run_blender_simulation(glb_path: str, output_dir: str, config_path: Optional[str] = None) -> bool:
    """
    调用 Blender 后台运行物理仿真。

    Args:
        glb_path: GLB 模型路径
        output_dir: 输出目录
        config_path: 可选 JSON 配置文件

    Returns:
        是否成功
    """
    blender = find_blender()
    script = find_blender_script()

    # 为每个模型创建独立输出子目录
    model_name = Path(glb_path).stem
    sim_output = Path(output_dir) / model_name
    sim_output.mkdir(parents=True, exist_ok=True)

    cmd = [
        blender,
        "--background",
        "--python", str(script),
        "--",
        str(glb_path),
        str(sim_output),
    ]

    if config_path:
        cmd.extend(["--config", config_path])

    print(f"\n[pipeline] 🔧 启动 Blender 仿真...")
    print(f"  命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # 实时输出
            text=True,
            timeout=600,  # 10分钟超时
        )

        if result.returncode == 0:
            print(f"[pipeline] ✅ 仿真完成: {sim_output}")
            return True
        else:
            print(f"[pipeline] ❌ Blender 退出码: {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print("[pipeline] ⏰ Blender 仿真超时（10分钟）")
        return False
    except FileNotFoundError:
        print("[pipeline] ❌ 找不到 Blender，请确认已安装")
        return False


def generate_config_json(output_path: str):
    """将 config.py 的参数导出为 JSON 配置文件，供 Blender 脚本使用"""
    from config import (
        SIM_START_FRAME, SIM_END_FRAME, SIM_FPS, SIM_SUBSTEPS, SIM_SOLVER_ITERS,
        GRAVITY_X, GRAVITY_Y, GRAVITY_Z,
        GROUND_SIZE, GROUND_HEIGHT,
        OBJECT_MASS, OBJECT_FRICTION, OBJECT_RESTITUTION, OBJECT_COLLISION_SHAPE,
        OBJECT_LINEAR_DAMPING, OBJECT_ANGULAR_DAMPING,
        OBJECT_START_Z, OBJECT_RANDOM_ROTATION,
        RENDER_ENGINE, RENDER_RESOLUTION_X, RENDER_RESOLUTION_Y,
        RENDER_SAMPLES, RENDER_OUTPUT_FORMAT, RENDER_FRAME_STEP,
    )

    config = {
        "sim_start_frame": SIM_START_FRAME,
        "sim_end_frame": SIM_END_FRAME,
        "sim_substeps": SIM_SUBSTEPS,
        "sim_solver_iters": SIM_SOLVER_ITERS,
        "gravity": [GRAVITY_X, GRAVITY_Y, GRAVITY_Z],
        "ground_size": GROUND_SIZE,
        "ground_height": GROUND_HEIGHT,
        "object_mass": OBJECT_MASS,
        "object_friction": OBJECT_FRICTION,
        "object_restitution": OBJECT_RESTITUTION,
        "object_collision_shape": OBJECT_COLLISION_SHAPE,
        "object_linear_damping": OBJECT_LINEAR_DAMPING,
        "object_angular_damping": OBJECT_ANGULAR_DAMPING,
        "object_start_z": OBJECT_START_Z,
        "object_random_rotation": OBJECT_RANDOM_ROTATION,
        "render_engine": RENDER_ENGINE,
        "render_resolution_x": RENDER_RESOLUTION_X,
        "render_resolution_y": RENDER_RESOLUTION_Y,
        "render_samples": RENDER_SAMPLES,
        "render_output_format": RENDER_OUTPUT_FORMAT,
        "render_frame_step": RENDER_FRAME_STEP,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return output_path


def summarize_results(models: List[Path], renders_dir: Path):
    """打印管线执行结果汇总"""
    print("\n" + "=" * 60)
    print("  📊 管线执行完成")
    print("=" * 60)

    print(f"\n  3D 模型 ({len(models)} 个):")
    for m in models:
        if m.exists():
            size_mb = m.stat().st_size / (1024 * 1024)
            print(f"    📦 {m.name} ({size_mb:.1f} MB)")

    print(f"\n  渲染结果:")
    if renders_dir.exists():
        for subdir in renders_dir.iterdir():
            if subdir.is_dir():
                frames = list(subdir.glob("frame_*"))
                if frames:
                    print(f"    🎬 {subdir.name}/ ({len(frames)} 帧)")

    print(f"\n  输出目录: {OUTPUT_DIR}")
    print("=" * 60)


# ============================================================
# 主流程
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="3D Pipeline: 图片 → Tripo API → 3D 模型 → Blender 物理仿真",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pipeline.py                          使用默认配置
  python pipeline.py --input ./photos         指定输入目录
  python pipeline.py --skip-tripo             已有 GLB，只做仿真
  python pipeline.py --skip-sim               只做 3D 转换，不做仿真
  python pipeline.py --model-version v2.0     指定 Tripo 模型版本
        """,
    )

    parser.add_argument("--input", default=None, help=f"输入目录（默认: {INPUT_DIR}）")
    parser.add_argument("--output", default=None, help=f"输出目录（默认: {OUTPUT_DIR}")

    # 流程控制
    parser.add_argument("--skip-tripo", action="store_true", help="跳过 Tripo 3D 转换（使用已有 GLB）")
    parser.add_argument("--skip-sim", action="store_true", help="跳过 Blender 仿真")
    parser.add_argument("--cleanup", action="store_true", help="完成后清理临时文件")

    # Tripo 参数
    parser.add_argument("--model-version", default="v2.5", help="Tripo 模型版本")
    parser.add_argument("--concurrency", type=int, default=3, help="Tripo API 最大并发数")
    parser.add_argument("--face-limit", type=int, default=50000, help="模型面数上限")

    # Blender 参数
    parser.add_argument("--blender", default=None, help="Blender 可执行文件路径")
    parser.add_argument("--sim-duration", type=float, default=5.0, help="仿真时长（秒）")
    parser.add_argument("--start-z", type=float, default=5.0, help="物体初始掉落高度（米）")

    return parser.parse_args()


async def main():
    args = parse_args()

    # 更新 Blender 路径
    if args.blender:
        import config
        config.BLENDER_EXECUTABLE = args.blender

    start_time = datetime.now()
    print("=" * 60)
    print("  3D Pipeline: Image → Tripo → Blender Simulation")
    print(f"  启动时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ================================================================
    # Step 1: 加载输入
    # ================================================================
    print("\n" + "-" * 40)
    print("  Step 1/3: 加载输入媒体")
    print("-" * 40)

    images = load_all_media(args.input)
    print(f"  ✅ 加载了 {len(images)} 张图片")

    # ================================================================
    # Step 2: Tripo API → 3D 模型
    # ================================================================
    print("\n" + "-" * 40)
    print("  Step 2/3: Tripo API 图片→3D 模型")
    print("-" * 40)

    if args.skip_tripo:
        # 跳过转换，直接使用已有 GLB 文件
        glb_files = list(MODELS_DIR.glob("*.glb"))
        if not glb_files:
            print("  ❌ --skip-tripo 模式下没有找到已有 GLB 文件")
            print(f"     请将 GLB 文件放到: {MODELS_DIR}")
            return
        print(f"  ⏩ 跳过转换，使用已有 {len(glb_files)} 个 GLB 文件")
    else:
        from tripo_client import TripoConverter

        async with TripoConverter() as converter:
            glb_files = await converter.convert_batch(
                [str(img) for img in images],
                output_dir=str(MODELS_DIR),
                concurrency=args.concurrency,
                model_version=args.model_version,
                face_limit=args.face_limit,
            )

        if not glb_files:
            print("  ❌ 所有 Tripo 转换都失败了")
            print("  请检查: 1) API Key 是否正确  2) 网络是否正常  3) 图片是否有效")
            return

    # ================================================================
    # Step 3: Blender 物理仿真
    # ================================================================
    print("\n" + "-" * 40)
    print("  Step 3/3: Blender 刚体物理仿真")
    print("-" * 40)

    if args.skip_sim:
        print("  ⏩ 跳过仿真")
    else:
        # 生成配置文件供 Blender 脚本读取
        config_json = str(OUTPUT_DIR / "sim_config.json")

        # 用命令行参数覆盖默认配置
        import config as cfg
        if args.sim_duration != 5.0:
            cfg.SIM_END_FRAME = int(args.sim_duration * 30)
        if args.start_z != 5.0:
            cfg.OBJECT_START_Z = args.start_z

        config_json = generate_config_json(config_json)

        # 验证 Blender 可用
        try:
            find_blender()
        except FileNotFoundError as e:
            print(f"  ❌ {e}")
            return

        # 逐个模型运行仿真
        for i, glb in enumerate(glb_files, 1):
            print(f"\n  [{i}/{len(glb_files)}] 仿真: {glb.name}")
            success = run_blender_simulation(
                str(glb),
                str(RENDERS_DIR),
                config_json,
            )
            if not success:
                print(f"  ⚠️ {glb.name} 仿真失败，继续下一个...")

    # ================================================================
    # 完成
    # ================================================================
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n  ⏱️ 总耗时: {elapsed:.1f} 秒")

    summarize_results(glb_files, RENDERS_DIR)

    # 清理
    if args.cleanup:
        cleanup_temp()


if __name__ == "__main__":
    asyncio.run(main())
