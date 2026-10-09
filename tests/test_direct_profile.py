"""Check that Home Assistant's bundled profile can capture directly."""

import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter"
package = types.ModuleType("cloud_inverter")
package.__path__ = [str(COMPONENT)]
sys.modules.setdefault("cloud_inverter", package)
profile = importlib.import_module("cloud_inverter.direct_profile.profile")
ha_helpers = importlib.import_module("cloud_inverter.direct_profile.ha")


class FakeResult:
    def __init__(self, count, ok=True):
        self.ok = ok
        self.registers = [0] * count if ok else None

    def to_dict(self):
        return {"ok": self.ok, "interpretation": {"ascii": "PV9000"}}


class FakeModbusClient:
    created = []

    def __init__(self, host, port=502, timeout=1.5):
        self.created.append((host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read_holding_registers(self, address, count, unit_id):
        return FakeResult(count)


class PartialModbusClient(FakeModbusClient):
    def read_holding_registers(self, address, count, unit_id):
        return FakeResult(count, ok=address != 0x1300)


class DirectProfileTests(unittest.TestCase):
    def test_capture_uses_configured_port_and_decodes(self):
        FakeModbusClient.created.clear()
        with patch.object(profile, "ModbusClient", FakeModbusClient), patch.object(
            profile.time, "sleep"
        ):
            snapshot = profile.read_profile_snapshot("192.168.50.10", port=1502)
        self.assertTrue(snapshot["ok"])
        self.assertIn("pv_power", snapshot["sensors"])
        self.assertEqual(FakeModbusClient.created, [("192.168.50.10", 1502, 4)])

    def test_host_must_be_an_ip_literal(self):
        with self.assertRaises(ValueError):
            profile.read_profile_snapshot("http://192.168.50.10")

    def test_one_missing_block_does_not_hide_all_other_sensors(self):
        with patch.object(profile, "ModbusClient", PartialModbusClient), patch.object(
            profile.time, "sleep"
        ):
            snapshot = profile.read_profile_snapshot("192.168.50.10")
        self.assertTrue(snapshot["ok"])
        self.assertFalse(snapshot["complete"])
        self.assertIn("pv_power", snapshot["sensors"])

    def test_cloud_quiet_window_delays_boundary_captures(self):
        self.assertEqual(ha_helpers.seconds_until_safe_window(10), 36)
        self.assertEqual(ha_helpers.seconds_until_safe_window(100), 0)
        self.assertEqual(ha_helpers.seconds_until_safe_window(240), 106)

    def test_direct_payload_requires_real_telemetry(self):
        with self.assertRaises(ValueError):
            ha_helpers.snapshot_payload({"ok": False, "sensors": {}})
        payload = ha_helpers.snapshot_payload({
            "ok": True,
            "captured_at": "2026-10-09T00:00:00+00:00",
            "sensors": {"pv_power": {"value": 100}},
        })
        self.assertTrue(payload["available"])
        self.assertEqual(payload["sensors"]["pv_power"]["value"], 100)


if __name__ == "__main__":
    unittest.main()
