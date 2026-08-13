from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import Idea54Error


def load_config(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Idea54Error("INVALID_CONFIG", "top-level YAML value must be an object")
    optimization = payload.get("optimization")
    if not isinstance(optimization, dict):
        raise Idea54Error("INVALID_CONFIG", "optimization must be an object")
    for name in ("steps", "learning_rate", "log_every"):
        if name not in optimization:
            raise Idea54Error("INVALID_CONFIG", f"missing optimization.{name}")
    if int(optimization["steps"]) < 1 or float(optimization["learning_rate"]) <= 0:
        raise Idea54Error("INVALID_CONFIG", "steps and learning_rate must be positive")
    return payload
