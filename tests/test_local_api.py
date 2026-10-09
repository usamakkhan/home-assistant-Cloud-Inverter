"""Contract checks for choosing the local analyzer as a data source."""

import importlib.util
from pathlib import Path
import unittest


module_path = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter" / "local_api.py"
spec = importlib.util.spec_from_file_location("local_api", module_path)
local_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_api)


class LocalApiTests(unittest.TestCase):
    def test_base_url_accepts_lan_host_and_removes_trailing_slash(self):
        self.assertEqual(
            local_api.normalize_analyzer_url(" http://192.168.50.20:8765/ "),
            "http://192.168.50.20:8765",
        )

    def test_rejects_api_path_credentials_and_missing_port(self):
        for value in (
            "http://192.168.50.20:8765/api/ha",
            "http://user:secret@192.168.50.20:8765",
            "http://192.168.50.20",
            "ftp://192.168.50.20:8765",
            "http://[invalid:8765",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_api.normalize_analyzer_url(value)

    def test_host_and_port_are_separate_and_port_can_be_overridden(self):
        self.assertEqual(
            local_api.build_analyzer_url("192.168.50.20", 8765),
            "http://192.168.50.20:8765",
        )
        self.assertEqual(
            local_api.build_analyzer_url("analyzer.local", 9876),
            "http://analyzer.local:9876",
        )
        self.assertEqual(
            local_api.split_analyzer_url("https://analyzer.local:9876"),
            ("https", "analyzer.local", 9876),
        )
        for host, port in (("http://192.168.50.20", 8765), ("192.168.50.20:8765", 8765), ("192.168.50.20", 0)):
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                local_api.build_analyzer_url(host, port)

    def test_rejects_unrelated_json_service(self):
        self.assertFalse(local_api.is_analyzer_config({"collector": {}}))
        self.assertFalse(local_api.is_analyzer_config({"documented_sensor_count": 47}))
        self.assertTrue(local_api.is_analyzer_config({
            "collector": {"mode": "cooperative"},
            "documented_sensor_count": 113,
        }))


if __name__ == "__main__":
    unittest.main()
