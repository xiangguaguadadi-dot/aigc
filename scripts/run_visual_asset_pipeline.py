#!/usr/bin/env python3
"""Run the image-to-TripoSR-to-Blender visual asset pipeline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("visual_asset_pipeline")
ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DEFAULT_CACHE_ROOT = Path.home() / "Library/Caches/physical-modeling-agent"
DEFAULT_TRIPOSR_SOURCE = DEFAULT_CACHE_ROOT / "TripoSR"
DEFAULT_MODEL_DIR = DEFAULT_CACHE_ROOT / "models/TripoSR-5b521936"
DEFAULT_BLENDER = Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"


class PipelineError(RuntimeError):
    """Raised when a pipeline precondition or verification fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and verify a Blender-ready visual asset from one image."
    )
    parser.add_argument("--image", type=Path, required=True, help="Single-object input image")
    parser.add_argument("--asset-id", required=True, help="Stable ASCII asset identifier")
    parser.add_argument("--output-root", type=Path, default=Path("assets"))
    parser.add_argument(
        "--triposr-source",
        type=Path,
        default=Path(os.environ.get("TRIPOSR_SOURCE", DEFAULT_TRIPOSR_SOURCE)),
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(os.environ.get("TRIPOSR_MODEL_DIR", DEFAULT_MODEL_DIR)),
    )
    parser.add_argument(
        "--blender-bin",
        type=Path,
        default=Path(os.environ.get("BLENDER_BIN", DEFAULT_BLENDER)),
    )
    parser.add_argument("--device", choices=("auto", "mps", "cuda", "cpu"), default="auto")
    parser.add_argument("--mc-resolution", type=int, default=128)
    parser.add_argument("--chunk-size", type=int, default=4096)
    parser.add_argument("--foreground-ratio", type=float, default=0.85)
    parser.add_argument("--rotate-x-degrees", type=float, default=-90.0)
    parser.add_argument("--force", action="store_true", help="Replace an existing asset directory")
    return parser.parse_args()


def validate_asset_id(value: str) -> str:
    if not ASSET_ID_PATTERN.fullmatch(value):
        raise PipelineError(
            "asset-id must start with an ASCII letter or digit and contain only letters, "
            "digits, underscores, or hyphens"
        )
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def git_revision(repository: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def configure_logging(log_path: Path) -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(console)
    LOGGER.addHandler(file_handler)


def ensure_environment(args: argparse.Namespace, blender_script: Path) -> None:
    missing: list[str] = []
    if not args.image.is_file():
        missing.append(f"input image: {args.image}")
    if not (args.triposr_source / "tsr/system.py").is_file():
        missing.append(f"TripoSR source: {args.triposr_source}")
    if not (args.model_dir / "model.ckpt").is_file():
        missing.append(f"TripoSR model: {args.model_dir / 'model.ckpt'}")
    if not (args.model_dir / "config.yaml").is_file():
        missing.append(f"TripoSR config: {args.model_dir / 'config.yaml'}")
    if not args.blender_bin.is_file() or not os.access(args.blender_bin, os.X_OK):
        missing.append(f"Blender executable: {args.blender_bin}")
    if not blender_script.is_file():
        missing.append(f"Blender automation script: {blender_script}")
    if missing:
        raise PipelineError("Missing required files:\n- " + "\n- ".join(missing))
    if not 32 <= args.mc_resolution <= 512:
        raise PipelineError("mc-resolution must be between 32 and 512")
    if args.chunk_size <= 0:
        raise PipelineError("chunk-size must be positive")
    if not 0.5 <= args.foreground_ratio <= 1.0:
        raise PipelineError("foreground-ratio must be between 0.5 and 1.0")


def select_device(requested: str, torch: Any) -> str:
    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise PipelineError("CUDA was requested but is unavailable")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise PipelineError("MPS was requested but is unavailable")
    return requested


def prepare_asset_directory(args: argparse.Namespace) -> dict[str, Path]:
    asset_dir = args.output_root.resolve() / args.asset_id
    input_path = args.image.resolve()
    if asset_dir.exists():
        if not args.force:
            raise PipelineError(f"Asset directory already exists: {asset_dir}; pass --force to replace it")
        try:
            input_path.relative_to(asset_dir)
        except ValueError:
            pass
        else:
            raise PipelineError("Cannot use --force when the input image is inside the asset directory")
        shutil.rmtree(asset_dir)

    paths = {
        "asset_dir": asset_dir,
        "source_dir": asset_dir / "source",
        "preprocessed_dir": asset_dir / "preprocessed",
        "generated_dir": asset_dir / "generated",
        "blender_dir": asset_dir / "blender",
        "export_dir": asset_dir / "export",
        "preview_dir": asset_dir / "preview",
        "logs_dir": asset_dir / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def generate_raw_asset(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    import numpy as np
    import rembg
    import torch
    import trimesh
    from PIL import Image
    from torchmcubes import marching_cubes

    sys.path.insert(0, str(args.triposr_source.resolve()))
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground

    source_path = paths["source_dir"] / f"reference{args.image.suffix.lower()}"
    shutil.copy2(args.image.resolve(), source_path)

    with Image.open(source_path) as source_image:
        width_px, height_px = source_image.size
        source_format = source_image.format
        has_alpha = "A" in source_image.getbands()

    started = time.perf_counter()
    session = rembg.new_session()
    image_rgba = resize_foreground(remove_background(Image.open(source_path), session), args.foreground_ratio)
    foreground_path = paths["preprocessed_dir"] / "foreground.png"
    model_input_path = paths["preprocessed_dir"] / "triposr_input.png"
    image_rgba.save(foreground_path)
    array = np.asarray(image_rgba).astype(np.float32) / 255.0
    rgb = array[:, :, :3] * array[:, :, 3:4] + (1.0 - array[:, :, 3:4]) * 0.5
    model_input = Image.fromarray((rgb * 255.0).astype(np.uint8))
    model_input.save(model_input_path)
    preprocess_seconds = time.perf_counter() - started
    LOGGER.info("Preprocessing completed in %.3fs", preprocess_seconds)

    load_started = time.perf_counter()
    model = TSR.from_pretrained(
        str(args.model_dir.resolve()), config_name="config.yaml", weight_name="model.ckpt"
    )
    model.renderer.set_chunk_size(args.chunk_size)
    device = select_device(args.device, torch)
    model.to(device)
    load_seconds = time.perf_counter() - load_started
    LOGGER.info("Model loaded on %s in %.3fs", device, load_seconds)

    inference_started = time.perf_counter()
    with torch.no_grad():
        scene_codes = model([model_input], device=device)
    inference_seconds = time.perf_counter() - inference_started
    LOGGER.info("Inference completed in %.3fs", inference_seconds)

    marching_cubes_device = device
    if device == "mps":
        model.set_marching_cubes_resolution(args.mc_resolution)
        model.isosurface_helper.mc_func = lambda level, threshold: marching_cubes(
            level.detach().cpu().contiguous(), threshold
        )
        marching_cubes_device = "cpu"

    mesh_started = time.perf_counter()
    meshes = model.extract_mesh(scene_codes, True, resolution=args.mc_resolution)
    if len(meshes) != 1:
        raise PipelineError(f"Expected one generated mesh, got {len(meshes)}")
    raw_mesh = meshes[0]
    if len(raw_mesh.vertices) == 0 or len(raw_mesh.faces) == 0:
        raise PipelineError("TripoSR generated an empty mesh")
    if not np.isfinite(raw_mesh.vertices).all():
        raise PipelineError("TripoSR generated non-finite vertex coordinates")
    raw_path = paths["generated_dir"] / "raw.glb"
    raw_mesh.export(raw_path)
    mesh_seconds = time.perf_counter() - mesh_started
    LOGGER.info(
        "Mesh extraction completed in %.3fs: %d vertices, %d faces",
        mesh_seconds,
        len(raw_mesh.vertices),
        len(raw_mesh.faces),
    )

    return {
        "source_path": source_path,
        "source_width_px": width_px,
        "source_height_px": height_px,
        "source_format": source_format,
        "source_has_alpha": has_alpha,
        "foreground_path": foreground_path,
        "model_input_path": model_input_path,
        "raw_path": raw_path,
        "raw_vertices": len(raw_mesh.vertices),
        "raw_faces": len(raw_mesh.faces),
        "raw_watertight": bool(raw_mesh.is_watertight),
        "raw_visual_kind": raw_mesh.visual.kind,
        "device": device,
        "marching_cubes_device": marching_cubes_device,
        "preprocess_seconds": preprocess_seconds,
        "model_load_seconds": load_seconds,
        "inference_seconds": inference_seconds,
        "mesh_seconds": mesh_seconds,
        "generation_seconds": time.perf_counter() - started,
        "trimesh_version": trimesh.__version__,
        "torch_version": torch.__version__,
    }


def run_blender(
    args: argparse.Namespace,
    paths: dict[str, Path],
    raw_path: Path,
    blender_script: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    output_paths = {
        "final_glb": paths["export_dir"] / f"{args.asset_id}.glb",
        "blend": paths["blender_dir"] / "normalized.blend",
        "preview": paths["preview_dir"] / "preview.png",
        "report": paths["blender_dir"] / "normalization_report.json",
    }
    command = [
        str(args.blender_bin.resolve()),
        "--background",
        "--factory-startup",
        "--python",
        str(blender_script.resolve()),
        "--",
        "--input",
        str(raw_path.resolve()),
        "--asset-id",
        args.asset_id,
        f"--rotate-x-degrees={args.rotate_x_degrees}",
        "--output",
        str(output_paths["final_glb"]),
        "--blend-output",
        str(output_paths["blend"]),
        "--preview",
        str(output_paths["preview"]),
        "--report",
        str(output_paths["report"]),
    ]
    log_path = paths["logs_dir"] / "blender.log"
    LOGGER.info("Running Blender normalization")
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log_file.write(line)
            sys.stdout.write(line)
        return_code = process.wait()
    if return_code != 0:
        raise PipelineError(f"Blender failed with exit code {return_code}; see {log_path}")
    report = json.loads(output_paths["report"].read_text(encoding="utf-8"))
    if not report.get("roundtrip", {}).get("passed"):
        raise PipelineError("Blender round-trip verification did not pass")
    return report, output_paths


def verify_outputs(output_paths: dict[str, Path]) -> dict[str, Any]:
    import numpy as np
    import trimesh
    from PIL import Image

    for name, path in output_paths.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise PipelineError(f"Missing or empty output {name}: {path}")

    final_scene = trimesh.load(output_paths["final_glb"], force="scene")
    if not final_scene.geometry:
        raise PipelineError("Final GLB contains no geometry")
    finite = all(np.isfinite(mesh.vertices).all() for mesh in final_scene.geometry.values())
    if not finite:
        raise PipelineError("Final GLB contains non-finite vertices")

    preview = np.asarray(Image.open(output_paths["preview"]).convert("RGB"))
    if preview.size == 0 or float(preview.std()) < 1.0:
        raise PipelineError("Preview is blank or nearly uniform")

    return {
        "geometry_count": len(final_scene.geometry),
        "vertices": sum(len(mesh.vertices) for mesh in final_scene.geometry.values()),
        "faces": sum(len(mesh.faces) for mesh in final_scene.geometry.values()),
        "finite_vertices": finite,
        "preview_shape": list(preview.shape),
        "preview_std": float(preview.std()),
    }


def build_manifest(
    args: argparse.Namespace,
    paths: dict[str, Path],
    generation: dict[str, Any],
    blender_report: dict[str, Any],
    outputs: dict[str, Path],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "asset_id": args.asset_id,
        "status": "visual_asset_pipeline_complete",
        "source": {
            "file": str(generation["source_path"].relative_to(paths["asset_dir"])),
            "original_filename": args.image.name,
            "sha256": sha256_file(generation["source_path"]),
            "width_px": generation["source_width_px"],
            "height_px": generation["source_height_px"],
            "format": generation["source_format"],
            "alpha": generation["source_has_alpha"],
            "measured_dimensions_m": None,
        },
        "generation": {
            "project": "VAST-AI-Research/TripoSR",
            "source_commit": git_revision(args.triposr_source),
            "source_license": "MIT",
            "model": "stabilityai/TripoSR",
            "model_sha256": sha256_file(args.model_dir / "model.ckpt"),
            "model_license": "MIT",
            "torch_version": generation["torch_version"],
            "trimesh_version": generation["trimesh_version"],
            "rembg_version": package_version("rembg"),
            "inference_device": generation["device"],
            "marching_cubes_device": generation["marching_cubes_device"],
            "foreground_ratio": args.foreground_ratio,
            "chunk_size": args.chunk_size,
            "marching_cubes_resolution": args.mc_resolution,
            "preprocess_seconds": generation["preprocess_seconds"],
            "model_load_seconds": generation["model_load_seconds"],
            "inference_seconds": generation["inference_seconds"],
            "mesh_seconds": generation["mesh_seconds"],
            "total_seconds": generation["generation_seconds"],
        },
        "raw_mesh": {
            "file": str(generation["raw_path"].relative_to(paths["asset_dir"])),
            "sha256": sha256_file(generation["raw_path"]),
            "vertices": generation["raw_vertices"],
            "triangles": generation["raw_faces"],
            "watertight": generation["raw_watertight"],
            "finite_vertices": True,
            "visual_kind": generation["raw_visual_kind"],
        },
        "blender": blender_report,
        "final_asset": {
            "file": str(outputs["final_glb"].relative_to(paths["asset_dir"])),
            "sha256": sha256_file(outputs["final_glb"]),
            "blend_file": str(outputs["blend"].relative_to(paths["asset_dir"])),
            "preview": str(outputs["preview"].relative_to(paths["asset_dir"])),
            "verification": verification,
        },
        "warnings": [
            "Depth and rear geometry are inferred from a single image.",
            "No measured dimension was supplied; physical scale is unknown.",
            "The visual mesh must not be used directly as collision or volume geometry.",
            "The default 128 marching-cubes resolution is intended for pipeline validation.",
        ],
    }


def main() -> int:
    args = parse_args()
    try:
        args.asset_id = validate_asset_id(args.asset_id)
        blender_script = Path(__file__).resolve().parent / "blender/normalize_asset.py"
        ensure_environment(args, blender_script)
        paths = prepare_asset_directory(args)
        configure_logging(paths["logs_dir"] / "pipeline.log")
        LOGGER.info("Starting visual asset pipeline for %s", args.asset_id)
        generation = generate_raw_asset(args, paths)
        blender_report, output_paths = run_blender(
            args, paths, generation["raw_path"], blender_script
        )
        verification = verify_outputs(output_paths)
        manifest = build_manifest(
            args, paths, generation, blender_report, output_paths, verification
        )
        manifest_path = paths["asset_dir"] / "asset_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        LOGGER.info("Pipeline completed successfully")
        print(
            json.dumps(
                {
                    "status": "success",
                    "asset_dir": str(paths["asset_dir"]),
                    "final_glb": str(output_paths["final_glb"]),
                    "blend": str(output_paths["blend"]),
                    "preview": str(output_paths["preview"]),
                    "manifest": str(manifest_path),
                },
                indent=2,
            )
        )
        return 0
    except PipelineError as exc:
        LOGGER.error("Pipeline failed: %s", exc)
        return 1
    except Exception as exc:
        LOGGER.exception("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
