#!/usr/bin/env python3
import argparse
import hashlib
import importlib.metadata
import json
import sys
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("distributions", nargs="+")
    args = parser.parse_args()

    records = []
    for requested_name in args.distributions:
        distribution = importlib.metadata.distribution(requested_name)
        files = []
        for relative_path in sorted(distribution.files or [], key=str):
            path = Path(distribution.locate_file(relative_path)).resolve()
            if path.is_file():
                files.append(
                    {
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                )
        records.append(
            {
                "requested_name": requested_name,
                "canonical_name": distribution.metadata["Name"],
                "version": distribution.version,
                "file_count": len(files),
                "files": files,
            }
        )

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "distributions": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(f"distribution_audit={args.output}")
    print(f"distribution_count={len(records)}")
    print(f"audit_sha256={sha256(args.output)}")
    for record in records:
        print(
            f"distribution={record['canonical_name']} version={record['version']} "
            f"file_count={record['file_count']}"
        )


if __name__ == "__main__":
    main()
