"""Verify multi-inverter IDs and preservation of existing entity IDs."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter" / "cloud_identity.py"
spec = importlib.util.spec_from_file_location("cloud_inverter_identity", MODULE)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class FakeRegistry:
    def __init__(self):
        self.updates = []

    def async_update_entity(self, entity_id, *, new_unique_id):
        self.updates.append((entity_id, new_unique_id))


class CloudIdentityTests(unittest.TestCase):
    def test_different_inverters_have_different_sensor_ids(self):
        self.assertNotEqual(
            identity.cloud_sensor_unique_id("entry_a", "ETotal"),
            identity.cloud_sensor_unique_id("entry_b", "ETotal"),
        )

    def test_legacy_entry_keeps_existing_entity_id(self):
        registry = FakeRegistry()
        entries = [
            SimpleNamespace(domain="sensor", platform="cloud_inverter", unique_id="cloud_inverter_ETotal", entity_id="sensor.my_solar"),
            SimpleNamespace(domain="sensor", platform="other", unique_id="cloud_inverter_ETotal", entity_id="sensor.other"),
        ]
        identity.migrate_legacy_sensor_ids(registry, entries, "entry_a", "cloud_inverter")
        self.assertEqual(registry.updates, [("sensor.my_solar", "entry_a_ETotal")])
