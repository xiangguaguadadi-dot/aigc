#!/usr/bin/env python3
"""CLI wrapper for the VLM Physical Model Card parser."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from physical_agent.intelligence.perception.vlm_client import main


if __name__ == "__main__":
    raise SystemExit(main())
