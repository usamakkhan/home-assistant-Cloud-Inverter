"""Keep cloud measurements valid for Home Assistant statistics."""

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter" / "numeric.py"
spec = importlib.util.spec_from_file_location("cloud_inverter_numeric", MODULE)
numeric = importlib.util.module_from_spec(spec)
spec.loader.exec_module(numeric)


class NumericStateTests(unittest.TestCase):
    def test_numeric_portal_values(self):
        self.assertEqual(numeric.numeric_state("1,234.50"), 1234.5)
        self.assertEqual(numeric.numeric_state("0.00"), 0.0)

    def test_invalid_values_do_not_corrupt_statistics(self):
        for value in (None, "", "-", "offline", "NaN", "Infinity", True):
            with self.subTest(value=value):
                self.assertIsNone(numeric.numeric_state(value))

    def test_signed_grid_power_splits_into_import_and_export(self):
        for reading, expected in (
            ("2,040", (2040.0, 0.0)),
            (-750, (0.0, 750.0)),
            (0, (0.0, 0.0)),
            ("-", (None, None)),
        ):
            with self.subTest(reading=reading):
                self.assertEqual(numeric.split_grid_power(reading), expected)
