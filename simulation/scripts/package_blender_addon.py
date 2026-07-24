"""Create an installable ZIP for the Robot Interaction Blender add-on."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the Blender live interaction add-on")
    parser.add_argument("--output", default="outputs/blender_addons/robot_interaction.zip")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    source = project_root / "simulation" / "blender_addon" / "robot_interaction"
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, Path("robot_interaction") / path.relative_to(source))
    temporary.replace(output)
    print(f"Blender add-on package: {output}")


if __name__ == "__main__":
    main()
