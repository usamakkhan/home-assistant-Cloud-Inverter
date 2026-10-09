"""Validation and connection checks for direct PV9000 setup."""

from __future__ import annotations

import ipaddress

from .direct_profile.modbus import ModbusClient


def parse_direct_settings(host: str, port: int, unit_id: int) -> tuple[str, int, int]:
    """Normalize the inverter endpoint and reject invalid Modbus parameters."""
    normalized_host = str(ipaddress.ip_address(str(host).strip()))
    normalized_port = int(port)
    normalized_unit = int(unit_id)
    if not 1 <= normalized_port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not 0 <= normalized_unit <= 255:
        raise ValueError("Modbus unit ID must be between 0 and 255")
    return normalized_host, normalized_port, normalized_unit


def direct_unique_id(host: str, port: int, unit_id: int) -> str:
    """Keep the 1.3.0 identity for the default Modbus unit."""
    identity = f"direct:{host}:{port}"
    return identity if unit_id == 1 else f"{identity}:{unit_id}"


def probe_direct_inverter(host: str, port: int, unit_id: int) -> int:
    """Verify one read-only PV9000 register through the selected Modbus unit."""
    with ModbusClient(host, port=port, timeout=4) as client:
        result = client.read_holding_registers(0x1001, 1, unit_id)
    if not result.ok or not result.registers:
        raise ConnectionError("Inverter did not return PV9000 register 0x1001")
    return result.registers[0]
