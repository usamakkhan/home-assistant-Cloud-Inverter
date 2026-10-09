from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from solarmax_analyzer.history import TelemetryHistory, snapshot_point


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {
            "ok": True,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "model": "SM-ONYX-UL-6KW",
            "phase_count": 1,
            "mppt_count": 2,
            "sensors": {
                "pv_power": {"name": "PV", "value": 1234.5, "unit": "W", "category": "PV inputs"},
                "grid_power": {"name": "Grid", "value": -100, "unit": "W", "category": "Grid"},
                "battery_soc": {"name": "SOC", "value": 88, "unit": "%", "category": "Battery"},
            },
        }

    def test_snapshot_point_contains_chart_series(self) -> None:
        point = snapshot_point(self.snapshot)
        self.assertEqual(point["pv_power"], 1234.5)
        self.assertEqual(point["grid_power"], -100)
        self.assertEqual(point["battery_soc"], 88)
        self.assertIsInstance(point["timestamp_ms"], int)

    def test_record_preserves_each_acquisition_and_builds_ha_payload(self) -> None:
        history = TelemetryHistory()
        history.record(self.snapshot, source="background")
        history.record(self.snapshot, source="manual_snapshot")
        self.assertEqual(len(history.query(60)), 2)
        payload = history.home_assistant_payload()
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(payload["available"])
        self.assertEqual(payload["sensors"]["pv_power"]["value"], 1234.5)

        activity = history.activity()
        self.assertEqual(len(activity), 2)
        self.assertEqual(activity[0]["source"], "manual_snapshot")
        self.assertEqual(activity[0]["values"]["pv_power"], 1234.5)
        self.assertEqual(activity[0]["status"], "success")

    def test_sqlite_journal_restores_every_exact_sample_and_latest_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            path=Path(directory)/"telemetry.sqlite3"
            first=TelemetryHistory(storage_path=path)
            first.record(self.snapshot,source="local")
            second_snapshot={
                **self.snapshot,
                "captured_at":datetime.now(timezone.utc).isoformat(),
                "sensors":{
                    **self.snapshot["sensors"],
                    "pv_power":{**self.snapshot["sensors"]["pv_power"],"value":0},
                    "grid_power":{**self.snapshot["sensors"]["grid_power"],"value":-12.3456},
                    "battery_power":{"name":"Battery","value":None,"unit":"W","category":"Battery"},
                },
            }
            first.record(second_snapshot,source="local")
            self.assertEqual(first.storage_status()["saved_samples"],2)

            restored=TelemetryHistory(storage_path=path)
            points=restored.query(60)
            self.assertEqual(len(points),2)
            self.assertEqual(points[-1]["pv_power"],0)
            self.assertEqual(points[-1]["grid_power"],-12.3456)
            self.assertIsNone(points[-1]["battery_power"])
            self.assertEqual(restored.latest_snapshot()["sensors"]["grid_power"]["value"],-12.3456)
            self.assertEqual(restored.home_assistant_payload()["sensors"]["pv_power"]["value"],0)
            self.assertEqual(len(restored.activity()),2)

    def test_default_cache_holds_a_full_day_of_ten_second_samples(self) -> None:
        history=TelemetryHistory()
        base=datetime.now(timezone.utc)-timedelta(seconds=8639*10)
        for index in range(8640):
            history.record({
                **self.snapshot,
                "captured_at":(base+timedelta(seconds=index*10)).isoformat(),
            },source="local")
        self.assertEqual(len(history.query(1440)),8640)

    def test_activity_includes_errors_newest_first(self) -> None:
        history = TelemetryHistory()
        history.record(self.snapshot, source="background")
        history.record_error("background", TimeoutError("device did not respond"), {"host": "192.168.50.10"})
        activity = history.activity(limit=1)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["status"], "error")
        self.assertIn("device did not respond", activity[0]["message"])
        self.assertEqual(activity[0]["details"]["host"], "192.168.50.10")

    def test_latest_is_capture_timestamp_aware_and_survives_reopen(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ordered.sqlite3"
            history = TelemetryHistory(storage_path=path)
            captured = datetime.now(timezone.utc)
            newer = {
                **self.snapshot,
                "captured_at": captured.isoformat(),
                "received_at": (captured + timedelta(seconds=2)).isoformat(),
                "sensors": {
                    **self.snapshot["sensors"],
                    "pv_power": {**self.snapshot["sensors"]["pv_power"], "value": 2000},
                },
            }
            out_of_order = {
                **self.snapshot,
                "captured_at": (captured - timedelta(seconds=10)).isoformat(),
                "received_at": (captured + timedelta(seconds=3)).isoformat(),
                "sensors": {
                    **self.snapshot["sensors"],
                    "pv_power": {**self.snapshot["sensors"]["pv_power"], "value": 1000},
                },
            }
            history.record(newer, source="ingest")
            history.record(out_of_order, source="ingest")
            self.assertEqual(history.latest_snapshot()["sensors"]["pv_power"]["value"], 2000)
            restored = TelemetryHistory(storage_path=path)
            self.assertEqual(restored.latest_snapshot()["sensors"]["pv_power"]["value"], 2000)

    def test_equal_capture_timestamp_uses_received_at_as_tiebreaker(self) -> None:
        captured = datetime.now(timezone.utc)
        history = TelemetryHistory()
        later_receipt = {
            **self.snapshot,
            "captured_at": captured.isoformat(),
            "received_at": (captured + timedelta(seconds=2)).isoformat(),
        }
        earlier_receipt = {
            **self.snapshot,
            "captured_at": captured.isoformat(),
            "received_at": (captured + timedelta(seconds=1)).isoformat(),
        }
        history.record(later_receipt, source="ingest")
        history.record(earlier_receipt, source="ingest")
        self.assertEqual(history.latest_snapshot()["received_at"], later_receipt["received_at"])


if __name__ == "__main__":
    unittest.main()
