"""Small newline-delimited JSON protocol used by PyBullet and Blender."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024


class ProtocolError(ValueError):
    """Raised when a live interaction message is malformed."""


def encode_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"Message exceeds {MAX_MESSAGE_BYTES} bytes")
    return payload + b"\n"


def decode_message(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"Message exceeds {MAX_MESSAGE_BYTES} bytes")
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("Message must be a JSON object")
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("Message requires a non-empty string 'type'")
    return message


def command_id(value: Any = None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    return f"cmd-{uuid.uuid4().hex[:12]}"


def vector3(value: Any, field: str = "target") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ProtocolError(f"'{field}' must contain exactly three numbers")
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"'{field}' must contain exactly three numbers") from exc
    if any(not math.isfinite(component) or abs(component) > 10000 for component in result):
        raise ProtocolError(f"'{field}' is outside the supported coordinate range")
    return result


def quaternion(value: Any, field: str = "orientation") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ProtocolError(f"'{field}' must contain exactly four numbers")
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"'{field}' must contain exactly four numbers") from exc
    length = sum(component * component for component in result) ** 0.5
    if not math.isfinite(length) or length < 1e-8:
        raise ProtocolError(f"'{field}' must be a non-zero quaternion")
    return [component / length for component in result]
