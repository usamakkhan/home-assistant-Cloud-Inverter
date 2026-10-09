from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import time
from typing import Callable

from .modbus import ModbusClient


DEFAULT_HOST = "192.168.50.10"
MAX_SCAN_ADDRESSES = 600
MIN_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ScanPreset:
    label: str
    addresses: tuple[int, ...]


PRESETS = {
    "low": ScanPreset("Low registers 0-199", tuple(range(0, 200))),
    "hundreds": ScanPreset(
        "Common hundreds blocks",
        tuple(range(900, 1101)) + tuple(range(2900, 3101)),
    ),
    "vendor": ScanPreset(
        "Common inverter map anchors",
        (
            0, 1, 2, 3, 10, 20, 50, 100, 200, 300, 500, 1000,
            3000, 3001, 30000, 32000, 33000, 34000, 35000, 37000,
            40000, 43000, 49999, 50000, 60000,
        ),
    ),
}


def validate_host(host: str) -> str:
    """Allow IP literals only; this avoids turning the app into a DNS/SSRF tool."""
    return str(ipaddress.ip_address(host.strip()))


def check_tcp(host: str, port: int = 502, timeout: float = 1.5) -> dict:
    host = validate_host(host)
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout):
            return {
                "ok": True,
                "host": host,
                "port": port,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
    except OSError as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def scan_addresses(
    host: str,
    addresses: list[int] | tuple[int, ...],
    unit_id: int = 1,
    timeout: float = 0.8,
    interval: float = 1.0,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    host = validate_host(host)
    unique = list(dict.fromkeys(addresses))
    if not unique or len(unique) > MAX_SCAN_ADDRESSES:
        raise ValueError(f"scan must contain 1-{MAX_SCAN_ADDRESSES} addresses")
    if any(not 0 <= address <= 65535 for address in unique):
        raise ValueError("all addresses must be between 0 and 65535")
    interval = max(interval, MIN_INTERVAL_SECONDS)
    client = ModbusClient(host, timeout=timeout)
    observations = []
    started = time.perf_counter()

    for index, address in enumerate(unique, 1):
        observation = client.read_holding_registers(address, 1, unit_id).to_dict()
        observations.append(observation)
        if progress:
            progress(index, len(unique))
        if index != len(unique):
            time.sleep(interval)

    valid = [item for item in observations if item["ok"]]
    exceptions = [item for item in observations if item["exception_code"] is not None]
    errors = [
        item for item in observations
        if not item["ok"] and item["exception_code"] is None
    ]
    return {
        "host": host,
        "unit_id": unit_id,
        "function": 3,
        "address_count": len(unique),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "valid_count": len(valid),
        "exception_count": len(exceptions),
        "error_count": len(errors),
        "valid": valid,
        "observations": observations,
    }
