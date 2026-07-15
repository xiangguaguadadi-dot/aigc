"""Validation for the VLM-produced Physical Model Card.

The first MVP keeps validation dependency-free so the VLM API path can run in a
fresh Python environment. The checks here are intentionally strict about model
families and geometry, and intentionally permissive about unknown fields so the
next modules can evolve without breaking older cards.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


SUPPORTED_MODEL_FAMILIES = {
    "rigid_body",
    "articulated_rigid_body",
    "elastic_rod",
}

SUPPORTED_GEOMETRIES = {
    "sphere",
    "box",
    "cylinder",
    "rod",
}

SUPPORTED_OBJECT_TYPES = SUPPORTED_GEOMETRIES | {
    "door",
    "drawer",
    "pendulum",
    "hinged_rod",
    "unknown",
}

SUPPORTED_JOINT_TYPES = {
    "none",
    "hinge",
    "slider",
    "unknown",
}

SUPPORTED_TARGET_QUANTITIES = {
    "trajectory",
    "velocity",
    "acceleration",
    "collision",
    "deformation",
    "rotation",
    "unknown",
}


class CardValidationError(ValueError):
    """Raised when a Physical Model Card is missing required information."""


def validate_physical_model_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and lightly normalize a Physical Model Card."""

    if not isinstance(card, dict):
        raise CardValidationError("card must be a JSON object")

    task = _require_object(card, "task")
    observed = _require_object(card, "observed")
    assumed = _require_object(card, "assumed")
    model = _require_object(card, "model")

    _require_string(task, "question")
    _require_enum(task, "target_quantity", SUPPORTED_TARGET_QUANTITIES)

    object_count = _require_number(observed, "object_count")
    if object_count < 1:
        raise CardValidationError("observed.object_count must be >= 1")
    _require_enum(observed, "object_type", SUPPORTED_OBJECT_TYPES)
    _require_string(observed, "support_surface")
    _require_string(observed, "approximate_color")

    _optional_string(assumed, "material_class")
    _optional_string(assumed, "scale_source")
    _optional_string(assumed, "joint_type", SUPPORTED_JOINT_TYPES)

    unknown = card.get("unknown")
    if not isinstance(unknown, list) or not all(isinstance(item, str) for item in unknown):
        raise CardValidationError("unknown must be a list of strings")

    _require_enum(model, "family", SUPPORTED_MODEL_FAMILIES)
    _require_enum(model, "geometry", SUPPORTED_GEOMETRIES)
    _validate_positive_if_present(model, "radius")
    _validate_positive_if_present(model, "length")
    _validate_positive_if_present(model, "width")
    _validate_positive_if_present(model, "height")

    hypotheses = card.get("parameter_hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise CardValidationError("parameter_hypotheses must be a non-empty list")
    for index, hypothesis in enumerate(hypotheses):
        _validate_hypothesis(hypothesis, index)

    follow_up = card.get("follow_up_question")
    if follow_up is not None and not isinstance(follow_up, str):
        raise CardValidationError("follow_up_question must be a string when present")

    return card


def _validate_hypothesis(hypothesis: Any, index: int) -> None:
    if not isinstance(hypothesis, dict):
        raise CardValidationError(f"parameter_hypotheses[{index}] must be an object")
    _require_string(hypothesis, "name")
    _validate_positive_if_present(hypothesis, "mass")
    _validate_range_if_present(hypothesis, "friction", 0, 2)
    _validate_range_if_present(hypothesis, "restitution", 0, 1)
    _validate_range_if_present(hypothesis, "confidence", 0, 1)


def _require_object(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise CardValidationError(f"{key} must be an object")
    return value


def _require_string(parent: Dict[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CardValidationError(f"{key} must be a non-empty string")
    return value


def _optional_string(
    parent: Dict[str, Any],
    key: str,
    allowed_values: Optional[Iterable[str]] = None,
) -> None:
    value = parent.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise CardValidationError(f"{key} must be a string when present")
    if allowed_values is not None and value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise CardValidationError(f"{key} must be one of: {allowed}")


def _require_enum(parent: Dict[str, Any], key: str, allowed_values: Iterable[str]) -> str:
    value = _require_string(parent, key)
    if value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise CardValidationError(f"{key} must be one of: {allowed}")
    return value


def _require_number(parent: Dict[str, Any], key: str) -> float:
    value = parent.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CardValidationError(f"{key} must be a number")
    return float(value)


def _validate_positive_if_present(parent: Dict[str, Any], key: str) -> None:
    value = parent.get(key)
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise CardValidationError(f"{key} must be > 0 when present")


def _validate_range_if_present(
    parent: Dict[str, Any],
    key: str,
    lower: float,
    upper: float,
) -> None:
    value = parent.get(key)
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CardValidationError(f"{key} must be a number when present")
    if value < lower or value > upper:
        raise CardValidationError(f"{key} must be between {lower} and {upper}")


def required_card_keys() -> List[str]:
    """Expose the top-level contract for docs and tests."""

    return [
        "task",
        "observed",
        "assumed",
        "unknown",
        "model",
        "parameter_hypotheses",
        "follow_up_question",
    ]
