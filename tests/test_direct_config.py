"""Direct setup contracts, including identity compatibility with v1.3.0."""

import importlib
from pathlib import Path
import socket
import struct
import sys
import threading
import types
import unittest
from unittest.mock import patch


component = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter"
package = types.ModuleType("cloud_inverter")
package.__path__ = [str(component)]
sys.modules.setdefault("cloud_inverter", package)
direct_config = importlib.import_module("cloud_inverter.direct_config")


class FakeResult:
    def __init__(self, ok=True):
        self.ok = ok
        self.registers = [0] if ok else None


class FakeModbusClient:
    calls = []
    success = True

    def __init__(self, host, port, timeout):
        self.calls.append(("connect", host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read_holding_registers(self, address, count, unit_id):
        self.calls.append(("read", address, count, unit_id))
        return FakeResult(self.success)


class DirectConfigTests(unittest.TestCase):
    def test_normalizes_endpoint_and_keeps_default_unit_identity(self):
        self.assertEqual(
            direct_config.parse_direct_settings(" 192.168.50.10 ", "502", "1"),
            ("192.168.50.10", 502, 1),
        )
        self.assertEqual(
            direct_config.direct_unique_id("192.168.50.10", 502, 1),
            "direct:192.168.50.10:502",
        )
        self.assertEqual(
            direct_config.direct_unique_id("192.168.50.10", 502, 2),
            "direct:192.168.50.10:502:2",
        )

    def test_rejects_invalid_ip_port_and_unit(self):
        for host, port, unit in (
            ("http://192.168.50.10", 502, 1),
            ("192.168.50.10", 0, 1),
            ("192.168.50.10", 502, 256),
        ):
            with self.subTest(host=host, port=port, unit=unit), self.assertRaises(ValueError):
                direct_config.parse_direct_settings(host, port, unit)

    def test_probe_checks_actual_modbus_register_and_unit(self):
        FakeModbusClient.calls.clear()
        FakeModbusClient.success = True
        with patch.object(direct_config, "ModbusClient", FakeModbusClient):
            self.assertEqual(
                direct_config.probe_direct_inverter("192.168.50.10", 1502, 2), 0
            )
        self.assertEqual(FakeModbusClient.calls, [
            ("connect", "192.168.50.10", 1502, 4),
            ("read", 0x1001, 1, 2),
        ])

    def test_probe_rejects_a_tcp_listener_without_modbus_data(self):
        FakeModbusClient.success = False
        with patch.object(direct_config, "ModbusClient", FakeModbusClient):
            with self.assertRaises(ConnectionError):
                direct_config.probe_direct_inverter("192.168.50.10", 502, 1)

    def test_probe_accepts_a_real_modbus_tcp_frame(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(2)
            port = server.getsockname()[1]

            def answer_once():
                try:
                    with server.accept()[0] as connection:
                        request = connection.recv(12)
                        transaction = int.from_bytes(request[:2], "big")
                        unit = request[6]
                        response = struct.pack(">HHHB", transaction, 0, 5, unit)
                        connection.sendall(response + b"\x03\x02\x00\x7b")
                except OSError:
                    pass

            worker = threading.Thread(target=answer_once)
            worker.start()
            try:
                try:
                    value = direct_config.probe_direct_inverter("127.0.0.1", port, 1)
                except PermissionError:
                    self.skipTest("This environment blocks loopback connections")
                self.assertEqual(value, 123)
            finally:
                server.close()
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
