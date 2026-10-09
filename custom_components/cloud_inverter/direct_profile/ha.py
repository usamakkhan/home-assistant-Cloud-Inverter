"""Pure helpers for PV9000 captures inside Home Assistant."""

_CLOUD_CYCLE_SECONDS = 300
_QUIET_WINDOW_SECONDS = 45
_CAPTURE_BUDGET_SECONDS = 30


def seconds_until_safe_window(now: float) -> float:
    """Avoid starting a capture close to the vendor's five-minute upload window."""
    phase = now % _CLOUD_CYCLE_SECONDS
    if phase < _QUIET_WINDOW_SECONDS:
        return _QUIET_WINDOW_SECONDS - phase + 1
    latest_start = _CLOUD_CYCLE_SECONDS - _QUIET_WINDOW_SECONDS - _CAPTURE_BUDGET_SECONDS
    if phase >= latest_start:
        return _CLOUD_CYCLE_SECONDS - phase + _QUIET_WINDOW_SECONDS + 1
    return 0


def snapshot_payload(snapshot: dict) -> dict:
    """Shape a direct capture like the analyzer's Home Assistant cache API."""
    sensors = snapshot.get("sensors", {})
    if not sensors:
        raise ValueError("Inverter returned no readable telemetry")
    return {
        "available": bool(snapshot.get("ok")),
        "captured_at": snapshot.get("captured_at"),
        "age_seconds": 0,
        "model": snapshot.get("model"),
        "phase_count": snapshot.get("phase_count"),
        "mppt_count": snapshot.get("mppt_count"),
        "sensors": sensors,
    }
