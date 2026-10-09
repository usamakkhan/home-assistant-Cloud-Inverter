from __future__ import annotations

import unittest

from solarmax_analyzer.comparison import compare_snapshot, partition_single_phase_sensors
from solarmax_analyzer.features import feature_inventory


class ComparisonTests(unittest.TestCase):
    def test_cloud_comparison_normalizes_energy_and_battery_direction(self) -> None:
        snapshot = {
            "captured_at": "2026-09-01T12:00:30+00:00",
            "sensors": {
                "today_energy": {"value": 38000},
                "battery_power": {"value": -128},
                "battery_voltage": {"value": 54.1},
            },
        }
        result = compare_snapshot(
            snapshot,
            {
                "today_energy": 38,
                "battery_charging_power": 128,
                "battery_discharging_power": 0,
                "battery_voltage": 54.1,
            },
            "2026-09-01T12:00:00+00:00",
        )
        self.assertEqual(result["compared_count"], 4)
        self.assertEqual(result["accuracy_percent"], 100.0)
        self.assertFalse(result["reference_stale"])

    def test_stale_cloud_reference_is_flagged(self) -> None:
        result = compare_snapshot(
            {"captured_at": "2026-09-01T12:05:00+00:00", "sensors": {}},
            {},
            "2026-09-01T12:00:00+00:00",
        )
        self.assertTrue(result["reference_stale"])
        self.assertEqual(result["reference_age_seconds"], 300.0)

    def test_single_phase_zero_channels_move_to_reference_rail(self) -> None:
        sensors = {
            "grid_power": {"name": "Grid L1", "value": 900, "unit": "W"},
            "grid_l2_power": {"name": "Grid L2", "value": 0, "unit": "W"},
            "grid_l3_power": {"name": "Grid L3", "value": 12, "unit": "W"},
            "ac_frequency": {"name": "L1 frequency", "value": 50.1, "unit": "Hz"},
            "ac_l2_frequency": {"name": "L2 frequency", "value": 50.1, "unit": "Hz"},
        }
        result = partition_single_phase_sensors(sensors, phase_count=1, mppt_count=2)
        self.assertIn("grid_power", result["visible_sensors"])
        self.assertNotIn("grid_l2_power", result["visible_sensors"])
        self.assertIn("grid_l3_power", result["visible_sensors"])
        self.assertEqual(len(result["zero_anomalies"]), 1)
        self.assertNotIn("ac_l2_frequency", result["visible_sensors"])
        mirrored = next(item for item in result["zero_reference_sensors"] if item["key"] == "ac_l2_frequency")
        self.assertEqual(mirrored["state"], "mirrored_common_frequency")
        virtual = {item["key"] for item in result["zero_reference_sensors"]}
        self.assertIn("pv3_power", virtual)
        self.assertIn("pv9_voltage", virtual)

    def test_feature_inventory_is_read_only(self) -> None:
        features = feature_inventory({"grid_charge_enabled": True})
        self.assertGreater(len(features), 10)
        self.assertTrue(any(item["current_value"] is True for item in features))
        self.assertTrue(all(not item["write_supported"] for item in features))


if __name__ == "__main__":
    unittest.main()
