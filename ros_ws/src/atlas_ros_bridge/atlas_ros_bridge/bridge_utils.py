from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from typing import Any


def now_unix_ms() -> int:
    return int(time.time() * 1000)


def safe_json_dumps(payload: Any) -> str:
    """Serialize payload to JSON without throwing.

    Intended for bridge/demo topics where we prefer best-effort visibility over strict typing.
    """

    def _default(obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        return str(obj)

    try:
        if is_dataclass(payload):
            payload = asdict(payload)
        return json.dumps(payload, default=_default, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "error": "json_serialize_failed",
                "detail": str(exc),
                "payload_repr": repr(payload),
            },
            ensure_ascii=False,
        )


def safe_json_loads(text: str, logger: Any) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        logger.error(f"Failed to parse JSON payload: {exc}; payload={text!r}")
        return None

    if isinstance(parsed, dict):
        return parsed

    return {"value": parsed}


def parse_polygon_param(value: Any, logger: Any) -> list[tuple[int, int]]:
    """Parse a polygon parameter into list[(x,y)].

    Accepts either Python list-of-lists (typical launch param) or JSON string.
    Returns [] if invalid.
    """
    try:
        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, list):
            raise TypeError("polygon must be a list")

        points: list[tuple[int, int]] = []
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"invalid point: {item!r}")
            x, y = item
            points.append((int(x), int(y)))
        return points
    except Exception as exc:
        logger.warning(f"Invalid restricted_zone_polygon parameter: {exc}; value={value!r}")
        return []


def make_status_payload(
    node_name: str,
    available_features: list[str],
    ok: bool = True,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "bridge_status": "OK" if ok else "ERROR",
        "timestamp_ms": now_unix_ms(),
        "node_name": node_name,
        "available_features": list(available_features),
    }
    if error:
        payload["error"] = error
    if extra:
        payload.update(extra)
    return payload
