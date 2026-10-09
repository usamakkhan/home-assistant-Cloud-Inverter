from __future__ import annotations

from dataclasses import asdict, dataclass
import socket
import struct
import threading
from typing import Any


EXCEPTIONS = {
    1: "illegal_function",
    2: "illegal_data_address",
    3: "illegal_data_value",
    4: "server_device_failure",
    5: "acknowledge",
    6: "server_device_busy",
    10: "gateway_path_unavailable",
    11: "gateway_target_failed_to_respond",
}


class ModbusError(Exception):
    """Base class for a local Modbus investigation error."""


class ModbusProtocolError(ModbusError):
    """The peer returned an invalid Modbus/TCP frame."""


@dataclass(slots=True)
class ReadResult:
    ok: bool
    host: str
    port: int
    unit_id: int
    function: int
    address: int
    count: int
    transaction_id: int
    request_hex: str
    response_hex: str = ""
    registers: list[int] | None = None
    exception_code: int | None = None
    exception_name: str | None = None
    error: str | None = None
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["interpretation"] = interpret_registers(self.registers or [])
        return data


class ModbusClient:
    """Small Modbus/TCP client. Physical writes require the guarded service."""

    def __init__(self, host: str, port: int = 502, timeout: float = 1.5):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._transaction = 0
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None

    def __enter__(self) -> "ModbusClient":
        self._socket = socket.create_connection((self.host, self.port), self.timeout)
        self._socket.settimeout(self.timeout)
        return self

    def __exit__(self, *_args) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _next_transaction(self) -> int:
        with self._lock:
            self._transaction = (self._transaction + 1) & 0xFFFF
            return self._transaction

    @staticmethod
    def _receive_exact(sock: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ModbusProtocolError("connection closed before frame completed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_holding_registers(
        self, address: int, count: int = 1, unit_id: int = 1
    ) -> ReadResult:
        # Telemetry always uses FC03. FC06 is isolated from the generic read API.
        if not 0 <= address <= 0xFFFF:
            raise ValueError("address must be between 0 and 65535")
        if not 1 <= count <= 125:
            raise ValueError("count must be between 1 and 125")
        if address + count > 0x10000:
            raise ValueError("register range exceeds address space")
        if not 0 <= unit_id <= 255:
            raise ValueError("unit_id must be between 0 and 255")

        import time

        transaction = self._next_transaction()
        pdu = struct.pack(">BHH", 3, address, count)
        request = struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit_id) + pdu
        started = time.perf_counter()
        result = ReadResult(
            ok=False,
            host=self.host,
            port=self.port,
            unit_id=unit_id,
            function=3,
            address=address,
            count=count,
            transaction_id=transaction,
            request_hex=request.hex(" "),
        )

        def exchange(sock: socket.socket) -> None:
            sock.sendall(request)
            header = self._receive_exact(sock, 7)
            rx_transaction, protocol, length, rx_unit = struct.unpack(">HHHB", header)
            if protocol != 0:
                raise ModbusProtocolError(f"unexpected protocol id {protocol}")
            if rx_transaction != transaction:
                raise ModbusProtocolError(
                    f"transaction mismatch: expected {transaction}, got {rx_transaction}"
                )
            if rx_unit != unit_id:
                raise ModbusProtocolError(
                    f"unit mismatch: expected {unit_id}, got {rx_unit}"
                )
            if not 2 <= length <= 254:
                raise ModbusProtocolError(f"invalid MBAP length {length}")
            body = self._receive_exact(sock, length - 1)
            response = header + body
            result.response_hex = response.hex(" ")

            function = body[0]
            if function == 0x83:
                if len(body) != 2:
                    raise ModbusProtocolError("invalid exception response length")
                result.exception_code = body[1]
                result.exception_name = EXCEPTIONS.get(body[1], "unknown_exception")
            elif function == 3:
                if len(body) < 2 or body[1] != count * 2:
                    raise ModbusProtocolError("unexpected register byte count")
                if len(body) != 2 + body[1]:
                    raise ModbusProtocolError("truncated or oversized register response")
                result.registers = list(struct.unpack(f">{count}H", body[2:]))
                result.ok = True
            else:
                raise ModbusProtocolError(f"unexpected function 0x{function:02x}")

        try:
            if self._socket is not None:
                exchange(self._socket)
            else:
                with socket.create_connection((self.host, self.port), self.timeout) as sock:
                    sock.settimeout(self.timeout)
                    exchange(sock)
        except (OSError, ModbusError) as exc:
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

        return result

    def read_device_identification(self, unit_id: int = 1) -> dict[str, Any]:
        """Issue only FC43/MEI 0x0E basic device identification.

        This is a read-only fingerprint.  It deliberately does not fall back to
        register scans when a logger rejects or ignores the request.
        """
        if not 0 <= unit_id <= 255:
            raise ValueError("unit_id must be between 0 and 255")
        import time

        transaction = self._next_transaction()
        pdu = bytes((0x2B, 0x0E, 0x01, 0x00))
        request = struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit_id) + pdu
        started = time.perf_counter()
        result: dict[str, Any] = {
            "ok": False,
            "host": self.host,
            "port": self.port,
            "unit_id": unit_id,
            "function": 43,
            "mei_type": 14,
            "read_device_id_code": 1,
            "transaction_id": transaction,
            "request_hex": request.hex(" "),
            "response_hex": "",
            "objects": {},
            "exception_code": None,
            "exception_name": None,
            "error": None,
            "elapsed_ms": None,
        }

        def exchange(sock: socket.socket) -> None:
            sock.sendall(request)
            header = self._receive_exact(sock, 7)
            rx_transaction, protocol, length, rx_unit = struct.unpack(">HHHB", header)
            if protocol != 0 or rx_transaction != transaction or rx_unit != unit_id:
                raise ModbusProtocolError("invalid FC43 response header")
            if not 2 <= length <= 254:
                raise ModbusProtocolError(f"invalid MBAP length {length}")
            body = self._receive_exact(sock, length - 1)
            result["response_hex"] = (header + body).hex(" ")
            if body[0] == 0xAB:
                if len(body) != 2:
                    raise ModbusProtocolError("invalid FC43 exception response")
                result["exception_code"] = body[1]
                result["exception_name"] = EXCEPTIONS.get(body[1], "unknown_exception")
                return
            if len(body) < 7 or body[0] != 0x2B or body[1] != 0x0E:
                raise ModbusProtocolError("unexpected FC43/MEI response")
            object_count = body[6]
            cursor = 7
            objects: dict[str, dict[str, str]] = {}
            for _ in range(object_count):
                if cursor + 2 > len(body):
                    raise ModbusProtocolError("truncated device-identification object")
                object_id, size = body[cursor], body[cursor + 1]
                cursor += 2
                if cursor + size > len(body):
                    raise ModbusProtocolError("truncated device-identification value")
                raw = body[cursor:cursor + size]
                cursor += size
                objects[str(object_id)] = {
                    "text": raw.decode("utf-8", errors="replace"),
                    "hex": raw.hex(" "),
                }
            if cursor != len(body):
                raise ModbusProtocolError("unexpected trailing device-identification bytes")
            result["conformity_level"] = body[3]
            result["more_follows"] = bool(body[4])
            result["next_object_id"] = body[5]
            result["objects"] = objects
            result["ok"] = True

        try:
            if self._socket is not None:
                exchange(self._socket)
            else:
                with socket.create_connection((self.host, self.port), self.timeout) as sock:
                    sock.settimeout(self.timeout)
                    exchange(sock)
        except (OSError, ModbusError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    def write_single_register(self, address: int, value: int, unit_id: int = 1) -> None:
        """One FC06 attempt, strict echo verification, no retries or reconnects.

        Only work mode and grid-charge switch are implemented. A timeout is an
        UNKNOWN outcome, not evidence that the setting stayed unchanged.
        """
        allowed = {0x2100: {0, 1, 3}, 0x2115: {0, 1}}
        if type(address) is not int or address not in allowed or type(value) is not int or value not in allowed[address]:
            raise ValueError("Write outside the implemented control allowlist")
        if type(unit_id) is not int or not 1 <= unit_id <= 247:
            raise ValueError("Physical writes require a unicast unit 1..247")
        if self._socket is None:
            raise ModbusError("Writes require an existing identity-checked connection")
        transaction = self._next_transaction()
        pdu = struct.pack(">BHH", 6, address, value)
        request = struct.pack(">HHHB",transaction,0,len(pdu)+1,unit_id)+pdu
        self._socket.sendall(request)
        header = self._receive_exact(self._socket,7)
        rx_transaction,protocol,length,rx_unit = struct.unpack(">HHHB",header)
        if (rx_transaction,protocol,rx_unit) != (transaction,0,unit_id) or length not in (3,6):
            raise ModbusProtocolError("Invalid FC06 response header; outcome unknown")
        body = self._receive_exact(self._socket,length-1)
        if body[0] == 0x86 and len(body) == 2:
            raise ModbusProtocolError(f"FC06 rejected: {EXCEPTIONS.get(body[1], body[1])}")
        if body != pdu:
            raise ModbusProtocolError("FC06 response did not echo the exact request; outcome unknown")


def interpret_registers(registers: list[int]) -> dict[str, Any]:
    signed16 = [value if value < 0x8000 else value - 0x10000 for value in registers]
    raw = b"".join(struct.pack(">H", value) for value in registers)
    ascii_text = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
    uint32_be = [
        (registers[index] << 16) | registers[index + 1]
        for index in range(0, len(registers) - 1, 2)
    ]
    uint32_word_swapped = [
        (registers[index + 1] << 16) | registers[index]
        for index in range(0, len(registers) - 1, 2)
    ]
    return {
        "unsigned16": registers,
        "signed16": signed16,
        "hex16": [f"0x{value:04X}" for value in registers],
        "ascii": ascii_text,
        "uint32_big_endian": uint32_be,
        "uint32_word_swapped": uint32_word_swapped,
    }
