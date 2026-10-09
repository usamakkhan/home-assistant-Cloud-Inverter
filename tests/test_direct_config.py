"""Direct setup contracts, including identity compatibility with v1.3.0."""

import importlib.util
from pathlib import Path
import unittest


module_path = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "cloud_inverter" / "direct_config.py"
)
spec = importlib.util.spec_from_file_location("direct_config", module_path)
direct_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct_config)


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


if __name__ == "__main__":
    unittest.main()
