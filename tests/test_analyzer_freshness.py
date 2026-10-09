"""Check cached telemetry availability across a cooperative quiet window."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local_analyzer"))
from solarmax_analyzer.history import TelemetryHistory  # noqa: E402


class AnalyzerFreshnessTests(unittest.TestCase):
    def test_cache_age_uses_collector_specific_limit(self):
        history = TelemetryHistory()
        history._latest = {
            "ok": True,
            "captured_at": (datetime.now(timezone.utc) - timedelta(seconds=240)).isoformat(),
            "sensors": {"pv_power": {"value": 100}},
        }
        self.assertFalse(history.home_assistant_payload()["available"])
        self.assertTrue(history.home_assistant_payload(max_age_seconds=450)["available"])

    def test_missing_capture_time_is_not_fresh(self):
        history = TelemetryHistory()
        history._latest = {
            "ok": True,
            "sensors": {"pv_power": {"value": 100}},
        }
        self.assertFalse(history.home_assistant_payload(max_age_seconds=450)["available"])


if __name__ == "__main__":
    unittest.main()
