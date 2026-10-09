"""Small validation helpers for the local analyzer connection."""

from __future__ import annotations

from urllib.parse import urlsplit


def normalize_analyzer_url(value: str) -> str:
    """Accept only a base HTTP URL with an explicit analyzer port."""
    base_url = value.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.port is not None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Analyzer URL must be an HTTP base URL with a port")
    return base_url


def is_analyzer_config(payload: object) -> bool:
    """Reject unrelated HTTP services before a config entry is created."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("collector"), dict)
        and isinstance(payload.get("documented_sensor_count"), int)
    )
