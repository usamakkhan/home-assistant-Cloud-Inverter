"""Verify repeated readings do not masquerade as new telemetry."""

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter" / "health.py"
spec = importlib.util.spec_from_file_location("cloud_inverter_health", MODULE)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class TelemetryHealthTests(unittest.TestCase):
    def test_repeated_snapshot_keeps_last_change_time(self):
        tracker = health.TelemetryHealth()
        first_change = tracker.observe({"power": 100})
        first_poll = tracker.last_successful_poll
        self.assertEqual(tracker.observe({"power": 100}), first_change)
        self.assertEqual(tracker.repeated_snapshots, 1)
        self.assertEqual(tracker.successful_polls, 2)
        self.assertGreaterEqual(tracker.last_successful_poll, first_poll)

        next_change = tracker.observe({"power": 0})
        self.assertGreaterEqual(next_change, first_change)
        self.assertEqual(tracker.repeated_snapshots, 0)

    def test_diagnostics_include_only_operational_fields(self):
        tracker = health.TelemetryHealth()
        tracker.observe({"serial": "ABCDE123456789", "password": "private"})
        report = health.diagnostic_summary(
            "cloud", 300, True, tracker, 2, None
        )
        self.assertEqual(report["configured_interval_seconds"], 300)
        self.assertEqual(report["field_count"], 2)
        self.assertNotIn("ABCDE123456789", repr(report))
        self.assertNotIn("private", repr(report))
