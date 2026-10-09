from __future__ import annotations

"""Small, read-only-first EyeBond collector discovery primitives.

The Wi-Fi logger is a callback client, not a Modbus/TCP server.  A UDP
``set>server=`` message asks it to open one TCP session to this application;
it does not write the logger's durable cloud endpoint (collector parameter 21).
This module deliberately limits first contact to identity and metadata reads.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import struct
import time
from typing import Any


DEFAULT_UDP_PORT = 58899
DEFAULT_CALLBACK_PORT = 8899
HEADER_SIZE = 8
WIRE_LENGTH_OFFSET = 6

FC_HEARTBEAT = 1
FC_QUERY_COLLECTOR = 2
FC_FORWARD_TO_DEVICE = 4

READ_ONLY_PARAMETERS: tuple[tuple[int, str], ...] = (
    (2, "collector_pn"),
    (5, "firmware_version"),
    (6, "hardware_version"),
    (14, "protocol_descriptor"),
    (21, "cloud_endpoint"),
    (34, "serial_baudrate"),
)


class EybondError(RuntimeError):
    """Raised when a callback session cannot be safely identified."""


@dataclass(frozen=True, slots=True)
class EybondFrame:
    tid: int
    devcode: int
    devaddr: int
    function: int
    payload: bytes


def callback_messages(advertised_host: str, advertised_port: int) -> tuple[bytes, ...]:
    base = f"set>server={advertised_host}:{int(advertised_port)};"
    return base.encode("ascii"), f"{base}\r\n".encode("ascii"), f"{base}\n".encode("ascii")


def local_ipv4_for_target(target_host: str) -> str:
    """Return the IPv4 address selected by the OS route to one target."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((target_host, DEFAULT_UDP_PORT))
        address = str(probe.getsockname()[0])
    finally:
        probe.close()
    if not address or address == "0.0.0.0" or address.startswith("127."):
        raise EybondError("no LAN callback address is available for the neighbor route")
    return address


def _encode_frame(tid: int, devcode: int, devaddr: int, function: int, payload: bytes) -> bytes:
    total = HEADER_SIZE + len(payload)
    return struct.pack(">HHHBB", tid, devcode, total - WIRE_LENGTH_OFFSET, devaddr, function) + payload


def _heartbeat_payload(interval_seconds: int = 60) -> bytes:
    now = datetime.now(timezone.utc)
    return bytes((now.year - 2000, now.month, now.day, now.hour, now.minute, now.second)) + struct.pack(">H", interval_seconds)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise EybondError("collector closed the callback session")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_frame(connection: socket.socket) -> EybondFrame:
    header = _recv_exact(connection, HEADER_SIZE)
    tid, devcode, wire_len, devaddr, function = struct.unpack(">HHHBB", header)
    total = wire_len + WIRE_LENGTH_OFFSET
    if total < HEADER_SIZE or total > 4096:
        raise EybondError(f"invalid EyeBond frame length: {total}")
    payload = _recv_exact(connection, total - HEADER_SIZE)
    return EybondFrame(tid, devcode, devaddr, function, payload)


class _FramedSession:
    def __init__(self, connection: socket.socket, timeout: float) -> None:
        self.connection = connection
        self.connection.settimeout(timeout)
        self.tid = 0
        self.observed: list[dict[str, Any]] = []

    def request(self, function: int, payload: bytes, *, devcode: int = 1, devaddr: int = 1) -> EybondFrame:
        self.tid = (self.tid + 1) & 0xFFFF
        expected_tid = self.tid
        self.connection.sendall(_encode_frame(expected_tid, devcode, devaddr, function, payload))
        for _ in range(16):
            frame = _read_frame(self.connection)
            self.observed.append({
                "tid": frame.tid,
                "devcode": frame.devcode,
                "device_address": frame.devaddr,
                "function": frame.function,
                "payload_bytes": len(frame.payload),
            })
            if frame.tid == expected_tid and frame.function == function:
                return frame
        raise EybondError("no response matching the EyeBond transaction")

    def fingerprint(self) -> dict[str, Any]:
        identity = self.request(FC_HEARTBEAT, _heartbeat_payload())
        route = {"devcode": identity.devcode, "collector_address": identity.devaddr}
        pn = identity.payload.rstrip(b"\x00").decode("ascii", errors="ignore").strip()
        metadata: dict[str, str] = {}
        query_errors: dict[str, str] = {}
        for parameter, key in READ_ONLY_PARAMETERS:
            try:
                response = self.request(FC_QUERY_COLLECTOR, bytes((parameter,)))
                if len(response.payload) < 2 or response.payload[1] != parameter:
                    raise EybondError("unexpected collector query response")
                if response.payload[0] != 0:
                    raise EybondError(f"collector returned code {response.payload[0]}")
                metadata[key] = response.payload[2:].rstrip(b"\x00").decode(
                    "ascii", errors="ignore"
                ).strip()
            except (OSError, EybondError) as exc:
                query_errors[key] = f"{type(exc).__name__}: {exc}"
        if metadata.get("collector_pn"):
            pn = metadata["collector_pn"]
        return {
            "session_protocol": "eybond_framed",
            "collector_pn": pn,
            "route": route,
            "metadata": metadata,
            "metadata_errors": query_errors,
            "observed_frames": self.observed,
        }

    def read_pi30(self, command: str, *, devcode: int, devaddr: int) -> str:
        response = self.request(
            FC_FORWARD_TO_DEVICE,
            _build_pi30_request(command),
            devcode=devcode,
            devaddr=devaddr,
        )
        return _parse_pi30_response(response.payload)

    def read_pi18(self, command: str, *, devcode: int, devaddr: int) -> str:
        response = self.request(
            FC_FORWARD_TO_DEVICE,
            _build_pi18_request(command),
            devcode=devcode,
            devaddr=devaddr,
        )
        return _parse_pi18_response(response.payload)


def _crc16_xmodem(payload: bytes) -> int:
    crc = 0
    for byte in payload:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _escape_pi30_crc_byte(value: int) -> int:
    return value + 1 if value in {0x28, 0x0D, 0x0A} else value


def _build_pi30_request(command: str) -> bytes:
    if not command or not command.isascii():
        raise EybondError("invalid PI30 command")
    body = command.encode("ascii")
    crc = _crc16_xmodem(body)
    return body + bytes((_escape_pi30_crc_byte(crc >> 8), _escape_pi30_crc_byte(crc & 0xFF))) + b"\r"


def _parse_pi30_response(frame: bytes) -> str:
    if len(frame) < 4 or not frame.endswith(b"\r"):
        raise EybondError("invalid PI30 response framing")
    body = frame[:-3]
    crc = _crc16_xmodem(body)
    expected = bytes((_escape_pi30_crc_byte(crc >> 8), _escape_pi30_crc_byte(crc & 0xFF)))
    if frame[-3:-1] != expected:
        raise EybondError("PI30 response CRC mismatch")
    if not body.startswith(b"("):
        raise EybondError("PI30 response has no payload prefix")
    payload = body[1:].decode("ascii", errors="strict")
    if payload in {"NAK", "NOA", "ERCRC"}:
        raise EybondError(f"PI30 command rejected: {payload}")
    return payload


def _build_pi18_request(command: str) -> bytes:
    if not command or not command.isascii():
        raise EybondError("invalid PI18 command")
    body = command.encode("ascii")
    crc = _crc16_xmodem(body)
    return body + bytes((crc >> 8, crc & 0xFF)) + b"\r"


def _parse_pi18_response(frame: bytes) -> str:
    if len(frame) < 8 or not frame.endswith(b"\r"):
        raise EybondError("invalid PI18 response framing")
    body = frame[:-3]
    crc = _crc16_xmodem(body)
    if frame[-3:-1] != bytes((crc >> 8, crc & 0xFF)):
        raise EybondError("PI18 response CRC mismatch")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise EybondError("PI18 response is not ASCII") from exc
    if not text.startswith("^D") or len(text) < 5 or not text[2:5].isdigit():
        raise EybondError(f"unexpected PI18 response: {text[:40]}")
    payload = text[5:]
    if payload in {"NAK", "NOA", "ERCRC"}:
        raise EybondError(f"PI18 command rejected: {payload}")
    return payload


_PI18_GS_FIELDS: tuple[tuple[str, int | float], ...] = (
    ("grid_voltage_v", 0.1),
    ("grid_frequency_hz", 0.1),
    ("output_voltage_v", 0.1),
    ("output_frequency_hz", 0.1),
    ("output_apparent_power_va", 1),
    ("output_active_power_w", 1),
    ("load_percent", 1),
    ("battery_voltage_v", 0.1),
    ("battery_scc_voltage_v", 0.1),
    ("battery_scc2_voltage_v", 0.1),
    ("battery_discharge_current_a", 1),
    ("battery_charge_current_a", 1),
    ("battery_soc_percent", 1),
    ("inverter_temperature_c", 1),
    ("mppt1_temperature_c", 1),
    ("mppt2_temperature_c", 1),
    ("pv1_power_w", 1),
    ("pv2_power_w", 1),
    ("pv1_voltage_v", 0.1),
    ("pv2_voltage_v", 0.1),
    ("configuration_state_code", 1),
    ("mppt1_status_code", 1),
    ("mppt2_status_code", 1),
    ("load_connection_code", 1),
    ("battery_power_direction_code", 1),
    ("dc_ac_power_direction_code", 1),
    ("line_power_direction_code", 1),
    ("parallel_id", 1),
)


def _parse_pi18_gs(payload: str) -> dict[str, Any]:
    fields = [item.strip() for item in payload.strip().split(",")]
    if len(fields) < 28:
        raise EybondError(f"PI18 GS returned only {len(fields)} fields")
    values: dict[str, Any] = {}
    for raw, (key, scale) in zip(fields, _PI18_GS_FIELDS):
        number = int(raw)
        values[key] = number if scale == 1 else round(number * float(scale), 1)
    values["field_count"] = len(fields)
    values["pv_power_w"] = values["pv1_power_w"] + values["pv2_power_w"]
    battery_voltage = values["battery_voltage_v"]
    values["battery_power_w"] = round(
        battery_voltage
        * (values["battery_charge_current_a"] - values["battery_discharge_current_a"]),
        1,
    )
    return values


def _read_pi18_inventory(session: _FramedSession, route: dict[str, int]) -> dict[str, Any]:
    commands = ("^P005PI", "^P005GS", "^P006MOD", "^P007PIRI", "^P005ID", "^P006VFW")
    responses: dict[str, str] = {}
    errors: dict[str, str] = {}
    for command in commands:
        try:
            responses[command] = session.read_pi18(
                command,
                devcode=int(route["devcode"]),
                devaddr=int(route["collector_address"]),
            )
        except (OSError, EybondError, UnicodeDecodeError) as exc:
            errors[command] = f"{type(exc).__name__}: {exc}"
    telemetry: dict[str, Any] = {}
    if "^P005GS" in responses:
        try:
            telemetry = _parse_pi18_gs(responses["^P005GS"])
        except (EybondError, ValueError) as exc:
            errors["GS_decode"] = f"{type(exc).__name__}: {exc}"
    protocol_raw = responses.get("^P005PI", "")
    protocol_id = f"PI{protocol_raw}" if protocol_raw.isdigit() else protocol_raw
    return {
        "protocol_id": protocol_id,
        "operating_mode_code": responses.get("^P006MOD", ""),
        "inverter_serial_raw": responses.get("^P005ID", ""),
        "firmware_raw": responses.get("^P006VFW", ""),
        "ratings_raw": responses.get("^P007PIRI", ""),
        "telemetry": telemetry,
        "raw_responses": responses,
        "command_errors": errors,
        "inverter_reads": len(responses),
    }


_QPIGS_FIELDS: tuple[tuple[str, type], ...] = (
    ("grid_voltage_v", float),
    ("grid_frequency_hz", float),
    ("output_voltage_v", float),
    ("output_frequency_hz", float),
    ("output_apparent_power_va", int),
    ("output_active_power_w", int),
    ("load_percent", int),
    ("bus_voltage_v", int),
    ("battery_voltage_v", float),
    ("battery_charge_current_a", int),
    ("battery_soc_percent", int),
    ("inverter_temperature_c", int),
    ("pv_current_a", float),
    ("pv_voltage_v", float),
    ("battery_scc_voltage_v", float),
    ("battery_discharge_current_a", int),
    ("status_bits", str),
    ("battery_voltage_offset_fans_on", int),
    ("eeprom_version", int),
    ("pv_charging_power_w", int),
    ("device_status_bits", str),
    ("solar_feed_to_grid_status", int),
    ("country_code", int),
    ("solar_feed_to_grid_power_w", int),
)


def _parse_qpigs(payload: str) -> dict[str, Any]:
    fields = [item for item in payload.strip().split(" ") if item]
    if len(fields) < 17:
        raise EybondError(f"QPIGS returned only {len(fields)} fields")
    values: dict[str, Any] = {}
    for raw, (key, value_type) in zip(fields, _QPIGS_FIELDS):
        try:
            values[key] = value_type(raw)
        except ValueError:
            values[key] = raw
    values["field_count"] = len(fields)
    voltage = values.get("pv_voltage_v")
    current = values.get("pv_current_a")
    if isinstance(voltage, (int, float)) and isinstance(current, (int, float)):
        values["pv_calculated_power_w"] = voltage * current
    if isinstance(values.get("pv_charging_power_w"), (int, float)):
        values["pv_power_w"] = values["pv_charging_power_w"]
    elif "pv_calculated_power_w" in values:
        values["pv_power_w"] = values["pv_calculated_power_w"]
    battery_voltage = values.get("battery_voltage_v")
    charge_current = values.get("battery_charge_current_a")
    discharge_current = values.get("battery_discharge_current_a")
    if all(isinstance(item, (int, float)) for item in (battery_voltage, charge_current, discharge_current)):
        values["battery_power_w"] = battery_voltage * (charge_current - discharge_current)
    return values


def _read_pi30_inventory(session: _FramedSession, route: dict[str, int]) -> dict[str, Any]:
    commands = ("QPI", "QMOD", "QPIGS", "QPIRI", "QID", "QVFW", "QVFW2")
    responses: dict[str, str] = {}
    errors: dict[str, str] = {}
    for command in commands:
        try:
            responses[command] = session.read_pi30(
                command,
                devcode=int(route["devcode"]),
                devaddr=int(route["collector_address"]),
            )
        except (OSError, EybondError, UnicodeDecodeError) as exc:
            errors[command] = f"{type(exc).__name__}: {exc}"
    telemetry: dict[str, Any] = {}
    if "QPIGS" in responses:
        try:
            telemetry = _parse_qpigs(responses["QPIGS"])
        except EybondError as exc:
            errors["QPIGS_decode"] = str(exc)
    return {
        "protocol_id": responses.get("QPI", ""),
        "operating_mode_code": responses.get("QMOD", ""),
        "inverter_serial": responses.get("QID", ""),
        "main_firmware": responses.get("QVFW", ""),
        "secondary_firmware": responses.get("QVFW2", ""),
        "ratings_raw": responses.get("QPIRI", ""),
        "telemetry": telemetry,
        "raw_responses": responses,
        "command_errors": errors,
        "inverter_reads": len(responses),
    }


def _read_at_line(connection: socket.socket, limit: int = 2048) -> bytes:
    result = bytearray()
    while len(result) < limit:
        byte = connection.recv(1)
        if not byte:
            break
        result.extend(byte)
        if byte == b"\n":
            break
    if not result:
        raise EybondError("collector returned no AT response")
    return bytes(result)


def _at_fingerprint(connection: socket.socket, timeout: float) -> dict[str, Any]:
    connection.settimeout(timeout)
    commands = {
        "DTUPN": "collector_pn",
        "ATVER": "collector_protocol_version",
        "DTUTYPE": "collector_type",
        "FWVER": "firmware_version",
        "UART": "serial_baudrate",
        "CLDSRVHOST1": "cloud_endpoint",
    }
    metadata: dict[str, str] = {}
    errors: dict[str, str] = {}
    for command, key in commands.items():
        try:
            connection.sendall(f"AT+{command}?\r\n".encode("ascii"))
            line = _read_at_line(connection).decode("ascii", errors="ignore").strip()
            prefix = f"AT+{command}:"
            if not line.startswith(prefix):
                raise EybondError(f"unexpected AT response: {line[:80]}")
            metadata[key] = line[len(prefix):].strip()
        except (OSError, EybondError) as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"
    return {
        "session_protocol": "at_text",
        "collector_pn": metadata.get("collector_pn", ""),
        "metadata": metadata,
        "metadata_errors": errors,
        "observed_frames": [],
    }


def _accept_exact_target(
    listener: socket.socket,
    target_host: str,
    udp_socket: socket.socket,
    advertised_host: str,
    callback_port: int,
    udp_port: int,
    timeout: float,
) -> tuple[socket.socket, tuple[str, int], str]:
    deadline = time.monotonic() + timeout
    last_message = ""
    for message in callback_messages(advertised_host, callback_port):
        udp_socket.sendto(message, (target_host, udp_port))
        last_message = message.decode("ascii", errors="replace").strip()
        while time.monotonic() < deadline:
            listener.settimeout(min(1.0, max(0.05, deadline - time.monotonic())))
            try:
                connection, address = listener.accept()
            except socket.timeout:
                break
            if address[0] == target_host:
                return connection, (str(address[0]), int(address[1])), last_message
            connection.close()
    raise EybondError(f"collector {target_host} did not call back to {advertised_host}:{callback_port}")


def fingerprint_collector(
    target_host: str,
    *,
    advertised_host: str | None = None,
    callback_port: int = DEFAULT_CALLBACK_PORT,
    udp_port: int = DEFAULT_UDP_PORT,
    timeout: float = 8.0,
    protocol_hint: str = "eybond_framed",
    read_inverter: bool = False,
    inverter_protocol: str = "pi30",
) -> dict[str, Any]:
    """Request one transient callback and fingerprint the logger.

    Collector settings are read but never written.  When ``read_inverter`` is
    true, the selected read-only inverter inventory is also requested.  The
    current cloud endpoint is retained as evidence; this function never sends
    FC=3 (the durable logger-setting function) or any inverter write command.
    """

    callback_host = advertised_host or local_ipv4_for_target(target_host)
    captured_at = datetime.now(timezone.utc).isoformat()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    connection: socket.socket | None = None
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", int(callback_port)))
        listener.listen(4)
        udp_socket.bind((callback_host, 0))
        connection, peer, message = _accept_exact_target(
            listener,
            target_host,
            udp_socket,
            callback_host,
            int(callback_port),
            int(udp_port),
            float(timeout),
        )
        if protocol_hint == "at_text":
            detail = _at_fingerprint(connection, min(timeout, 3.0))
        else:
            session = _FramedSession(connection, min(timeout, 3.0))
            detail = session.fingerprint()
            if read_inverter:
                if inverter_protocol == "pi18":
                    detail["inverter"] = _read_pi18_inventory(session, detail["route"])
                else:
                    detail["inverter"] = _read_pi30_inventory(session, detail["route"])
        return {
            "ok": True,
            "captured_at": captured_at,
            "target_host": target_host,
            "callback_host": callback_host,
            "callback_port": int(callback_port),
            "udp_port": int(udp_port),
            "callback_peer": f"{peer[0]}:{peer[1]}",
            "callback_request": message,
            "callback_is_transient": True,
            "stored_endpoint_changed": False,
            "collector_setting_writes": 0,
            "inverter_reads": int(detail.get("inverter", {}).get("inverter_reads", 0)),
            "inverter_writes": 0,
            **detail,
        }
    except (OSError, EybondError) as exc:
        return {
            "ok": False,
            "captured_at": captured_at,
            "target_host": target_host,
            "callback_host": callback_host,
            "callback_port": int(callback_port),
            "udp_port": int(udp_port),
            "callback_is_transient": True,
            "stored_endpoint_changed": False,
            "collector_setting_writes": 0,
            "inverter_reads": 0,
            "inverter_writes": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if connection is not None:
            connection.close()
        udp_socket.close()
        listener.close()


def capture_pi18_telemetry(
    target_host: str,
    *,
    advertised_host: str | None = None,
    callback_port: int = DEFAULT_CALLBACK_PORT,
    udp_port: int = DEFAULT_UDP_PORT,
    timeout: float = 8.0,
    expected_collector_pn: str = "",
) -> dict[str, Any]:
    """Capture one lean PI18 sample through a transient EyeBond callback."""

    callback_host = advertised_host or local_ipv4_for_target(target_host)
    started = time.monotonic()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    connection: socket.socket | None = None
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", int(callback_port)))
        listener.listen(4)
        udp_socket.bind((callback_host, 0))
        connection, peer, message = _accept_exact_target(
            listener,
            target_host,
            udp_socket,
            callback_host,
            int(callback_port),
            int(udp_port),
            float(timeout),
        )
        session = _FramedSession(connection, min(timeout, 3.0))
        identity = session.request(FC_HEARTBEAT, _heartbeat_payload())
        collector_pn = identity.payload.rstrip(b"\x00").decode("ascii", errors="ignore").strip()
        if expected_collector_pn and collector_pn != expected_collector_pn:
            raise EybondError(
                f"collector identity mismatch: expected {expected_collector_pn}, received {collector_pn or 'empty'}"
            )
        route = {"devcode": identity.devcode, "collector_address": identity.devaddr}
        inventory = _read_pi18_inventory_fast(session, route)
        return {
            "ok": True,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "target_host": target_host,
            "callback_host": callback_host,
            "callback_port": int(callback_port),
            "udp_port": int(udp_port),
            "callback_peer": f"{peer[0]}:{peer[1]}",
            "callback_request": message,
            "callback_is_transient": True,
            "stored_endpoint_changed": False,
            "collector_pn": collector_pn,
            "route": route,
            "session_protocol": "eybond_framed",
            "inverter_protocol": "PI18",
            "telemetry": inventory["telemetry"],
            "operating_mode_code": inventory["operating_mode_code"],
            "raw_responses": inventory["raw_responses"],
            "command_errors": inventory["command_errors"],
            "collector_setting_writes": 0,
            "inverter_reads": inventory["inverter_reads"],
            "inverter_writes": 0,
        }
    except (OSError, EybondError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "target_host": target_host,
            "callback_host": callback_host,
            "callback_port": int(callback_port),
            "udp_port": int(udp_port),
            "callback_is_transient": True,
            "stored_endpoint_changed": False,
            "collector_setting_writes": 0,
            "inverter_reads": 0,
            "inverter_writes": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if connection is not None:
            connection.close()
        udp_socket.close()
        listener.close()


def _read_pi18_inventory_fast(session: _FramedSession, route: dict[str, int]) -> dict[str, Any]:
    responses: dict[str, str] = {}
    errors: dict[str, str] = {}
    for command in ("^P005GS", "^P006MOD"):
        try:
            responses[command] = session.read_pi18(
                command,
                devcode=int(route["devcode"]),
                devaddr=int(route["collector_address"]),
            )
        except (OSError, EybondError, UnicodeDecodeError) as exc:
            errors[command] = f"{type(exc).__name__}: {exc}"
    telemetry: dict[str, Any] = {}
    if "^P005GS" in responses:
        telemetry = _parse_pi18_gs(responses["^P005GS"])
    if not telemetry:
        raise EybondError(errors.get("^P005GS", "PI18 GS returned no telemetry"))
    return {
        "telemetry": telemetry,
        "operating_mode_code": responses.get("^P006MOD", ""),
        "raw_responses": responses,
        "command_errors": errors,
        "inverter_reads": len(responses),
    }
