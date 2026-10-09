from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from solarmax_analyzer.history import TelemetryHistory
from solarmax_analyzer.peer_api import DiskTelemetryReader, PeerCoordinator, create_peer_server


def snapshot(power: float) -> dict:
    return {
        "ok": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "model": "SM-ONYX-UL-6KW",
        "sensors": {
            "pv_power": {"name": "PV", "value": power, "unit": "W"},
            "today_energy": {"name": "Today", "value": 2500, "unit": "Wh"},
            "error_1": {"name": "Fault", "value": 0, "unit": ""},
        },
    }


def failed_callback(host: str = "192.168.50.30") -> dict:
    return {
        "ok": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_host": host,
        "callback_host": "192.168.50.20",
        "callback_port": 8899,
        "udp_port": 58899,
        "callback_is_transient": True,
        "stored_endpoint_changed": False,
        "collector_setting_writes": 0,
        "inverter_reads": 0,
        "inverter_writes": 0,
        "error": "EybondError: callback timed out",
    }


def successful_callback(host: str = "192.168.50.30", pv_power: float = 1750.25) -> dict:
    telemetry = {
        "grid_voltage_v": 229.4,
        "grid_frequency_hz": 49.9,
        "output_active_power_w": 1209,
        "battery_voltage_v": 57.8,
        "battery_charge_current_a": 8,
        "battery_discharge_current_a": 0,
        "battery_soc_percent": 95,
        "battery_power_w": 462.4,
        "inverter_temperature_c": 58,
        "pv1_power_w": pv_power,
        "pv2_power_w": 0,
        "pv_power_w": pv_power,
    }
    return {
        "ok": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 1189.5,
        "target_host": host,
        "callback_host": "192.168.50.20",
        "callback_port": 8899,
        "udp_port": 58899,
        "callback_peer": f"{host}:49152",
        "callback_is_transient": True,
        "stored_endpoint_changed": False,
        "collector_setting_writes": 0,
        "inverter_reads": 6,
        "inverter_writes": 0,
        "collector_pn": "ABCDE123456789",
        "metadata": {
            "firmware_version": "3.5.1.3",
            "hardware_version": "3.0.0.0",
            "cloud_endpoint": "ess.eybond.com",
        },
        "inverter": {
            "protocol_id": "PI18",
            "operating_mode_code": "05",
            "inverter_serial_raw": "0000000000000000000000",
            "telemetry": telemetry,
            "raw_responses": {"^P005GS": "live", "^P006MOD": "05"},
        },
    }


class PeerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.primary = TelemetryHistory()
        self.primary.record(snapshot(1200), source="test")
        self.server = create_peer_server(
            "127.0.0.1",
            0,
            self.primary,
            Path(self.temp.name),
            automatic_collection=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        payload = json.dumps(body) if body is not None else None
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    def test_separate_api_starts_unconfigured_without_fake_data(self) -> None:
        status, _, data = self.request("GET", "/v1/status")
        self.assertEqual(status, 200)
        self.assertFalse(data["configured"])
        self.assertFalse(data["latest"]["available"])
        self.assertEqual(data["latest"]["metrics"], {})
        self.assertFalse(data["safety"]["inverter_writes"])
        status, _, comparison = self.request("GET", "/v1/comparison?minutes=60")
        self.assertEqual(status, 200)
        self.assertFalse(comparison["available"])
        self.assertEqual(comparison["reason"], "neighbor_not_configured")

    def test_config_is_private_isolated_and_cannot_select_primary(self) -> None:
        self.assertEqual(
            self.request("POST", "/v1/admin/config", {"host": "192.168.50.10"})[0], 400
        )
        status, _, config = self.request(
            "POST", "/v1/admin/config", {"host": "192.168.50.30", "panel_count": 10, "panel_watts": 585}
        )
        self.assertEqual(status, 200)
        self.assertTrue(config["configured"])
        self.assertEqual(config["driver"], "unverified")
        self.assertEqual(config["array"]["dc_nameplate_watts"], 5850)

    def test_ingest_preserves_precision_and_enables_comparison(self) -> None:
        captured = self.primary.latest_snapshot()["captured_at"]
        status, _, data = self.request(
            "POST",
            "/v1/admin/ingest",
            {"captured_at": captured, "metrics": {"pv_dc_power_w": 1000.123, "energy_today_kwh": 2.25}},
        )
        self.assertEqual(status, 201)
        self.assertEqual(data["snapshot"]["metrics"]["pv_power_w"], 1000.123)
        comparison = self.request("GET", "/v1/comparison?minutes=60")[2]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["alignment"]["pair_count"], 1)
        self.assertEqual(comparison["alignment"]["comparable_pair_count"], 1)
        self.assertEqual(comparison["latest"], comparison["latest_aligned"])
        self.assertEqual(comparison["latest"], comparison["latest_comparable"])
        self.assertEqual(comparison["latest"]["neighbor"]["pv_power_w"], 1000.123)

    def test_same_capture_retry_is_idempotent_and_keeps_first_receipt(self) -> None:
        captured = self.primary.latest_snapshot()["captured_at"]
        body = {"captured_at": captured, "metrics": {"pv_dc_power_w": 999.125}}
        first_status, _, first = self.request("POST", "/v1/admin/ingest", body)
        second_status, _, second = self.request("POST", "/v1/admin/ingest", body)
        self.assertEqual(first_status, 201)
        self.assertFalse(first["duplicate"])
        self.assertEqual(second_status, 200)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["snapshot"]["received_at"], first["snapshot"]["received_at"])
        self.assertEqual(second["snapshot"]["age_basis"], "received_at")
        self.assertEqual(self.server.coordinator.neighbor_history.storage_status()["saved_samples"], 1)

    def test_ingest_latest_uses_capture_time_not_arrival_order(self) -> None:
        captured = datetime.now(timezone.utc)
        self.request(
            "POST", "/v1/admin/ingest",
            {"captured_at": captured.isoformat(), "metrics": {"pv_dc_power_w": 2000}},
        )
        self.request(
            "POST", "/v1/admin/ingest",
            {
                "captured_at": (captured - timedelta(seconds=10)).isoformat(),
                "metrics": {"pv_dc_power_w": 1000},
            },
        )
        latest = self.request("GET", "/v1/systems/neighbor/latest")[2]
        self.assertEqual(latest["metrics"]["pv_power_w"], 2000)

    def test_status_exposes_cadence_derived_freshness_thresholds(self) -> None:
        primary_state = {
            "mode": "local",
            "background_polling": True,
            "interval_seconds": 60,
            "quiet_window_seconds": 45,
        }
        coordinator = PeerCoordinator(
            self.primary,
            Path(self.temp.name) / "freshness-thresholds",
            primary_status=lambda: dict(primary_state),
        )
        coordinator.update_config({"expected_interval_seconds": 40})
        freshness = coordinator.status()["freshness"]
        self.assertEqual(freshness["primary_stale_after_seconds"], 195)
        self.assertEqual(freshness["neighbor_stale_after_seconds"], 135)

        primary_state.update({"mode": "cooperative", "interval_seconds": 20})
        freshness = coordinator.status()["freshness"]
        self.assertEqual(freshness["primary_stale_after_seconds"], 165)

    def test_port_only_target_change_advances_generation_and_invalidates_probe(self) -> None:
        coordinator = self.server.coordinator
        first = coordinator.update_config({"host": "192.168.50.30"})
        with patch(
            "solarmax_analyzer.peer_api.fingerprint_collector",
            return_value=failed_callback(first["host"]),
        ):
            coordinator.probe()
        probed = coordinator.config()
        self.assertIsNotNone(probed["last_probe"])
        self.assertEqual(probed["protocol_status"], "transport_not_reached")

        changed = coordinator.update_config({"port": 1502})
        self.assertEqual(changed["target_generation"], first["target_generation"] + 1)
        self.assertIsNone(changed["last_probe"])
        self.assertEqual(changed["protocol_status"], "awaiting_read_only_fingerprint")

        unchanged = coordinator.update_config({"port": 1502, "name": "Next door"})
        self.assertEqual(unchanged["target_generation"], changed["target_generation"])

    def test_config_change_during_probe_discards_stale_evidence(self) -> None:
        coordinator = self.server.coordinator
        initial = coordinator.update_config({"host": "192.168.50.30"})
        probe_started = threading.Event()
        finish_probe = threading.Event()
        outcome: list[object] = []

        def delayed_fingerprint(host: str, **_: object) -> dict:
            probe_started.set()
            finish_probe.wait(3)
            return failed_callback(host)

        def run_probe() -> None:
            try:
                outcome.append(coordinator.probe())
            except Exception as exc:
                outcome.append(exc)

        with patch(
            "solarmax_analyzer.peer_api.fingerprint_collector",
            side_effect=delayed_fingerprint,
        ):
            probe_thread = threading.Thread(target=run_probe)
            probe_thread.start()
            self.assertTrue(probe_started.wait(1), "probe did not reach the delayed TCP check")
            coordinator.update_config({"port": 1502})
            changed = coordinator.update_config({"port": initial["port"]})
            finish_probe.set()
            probe_thread.join(3)

        self.assertFalse(probe_thread.is_alive())
        self.assertEqual(changed["target_generation"], initial["target_generation"] + 2)
        self.assertEqual(coordinator.state_store.target_tuple(changed), coordinator.state_store.target_tuple(initial))
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], RuntimeError)
        self.assertIn("result discarded", str(outcome[0]))
        current = coordinator.config()
        self.assertIsNone(current["last_probe"])
        self.assertEqual(current["protocol_status"], "awaiting_read_only_fingerprint")

    def test_pi18_callback_probe_verifies_and_records_precise_telemetry(self) -> None:
        coordinator = self.server.coordinator
        coordinator.update_config({"host": "192.168.50.30"})
        callback = successful_callback(pv_power=1750.25)
        with patch(
            "solarmax_analyzer.peer_api.fingerprint_collector",
            return_value=callback,
        ):
            evidence = coordinator.probe()

        self.assertTrue(evidence["callback"]["ok"])
        config = coordinator.config()
        self.assertEqual(config["driver"], "knox_eybond_pi18")
        self.assertEqual(config["protocol_status"], "verified")
        self.assertEqual(config["collector_pn"], "ABCDE123456789")
        self.assertEqual(config["cloud_endpoint"], "ess.eybond.com")
        latest = coordinator.latest("neighbor")
        self.assertTrue(latest["available"])
        self.assertEqual(latest["metrics"]["pv_power_w"], 1750.25)
        self.assertEqual(latest["telemetry"]["grid_voltage_v"], 229.4)
        self.assertEqual(latest["sensors"]["battery_power"]["value"], 462.4)
        self.assertEqual(latest["sensors"]["inverter_mode"]["value"], "Hybrid")
        self.assertFalse(latest["automatic_collection"])

    def test_original_mode_stops_local_callback_collection(self) -> None:
        coordinator = self.server.coordinator
        config = coordinator.update_config(
            {"host": "192.168.50.30", "collection_mode": "original"}
        )
        self.assertEqual(config["collection_mode"], "original")
        self.assertFalse(config["automatic_collection"])
        status = coordinator.status()
        self.assertEqual(status["reason"], "original_cloud_mode")
        self.assertFalse(status["collector"]["running"])
        self.assertTrue(status["safety"]["stored_cloud_endpoint_unchanged"])

    def test_old_telemetry_is_hidden_after_target_change_and_restart(self) -> None:
        first = self.server.coordinator.update_config({"host": "192.168.50.30"})
        captured = self.primary.latest_snapshot()["captured_at"]
        old = self.server.coordinator.ingest(
            {"captured_at": captured, "metrics": {"pv_dc_power_w": 1000.0}}
        )
        self.assertEqual(old["history_point"]["target_generation"], first["target_generation"])

        changed = self.server.coordinator.update_config({"port": 1502})
        self.assertFalse(self.server.coordinator.latest("neighbor")["available"])
        self.assertEqual(self.server.coordinator.history("neighbor", 60)["points"], [])
        self.assertFalse(self.server.coordinator.comparison(60)["available"])

        reopened = PeerCoordinator(self.primary, Path(self.temp.name))
        self.assertFalse(reopened.latest("neighbor")["available"])
        self.assertEqual(reopened.history("neighbor", 60)["points"], [])

        older_capture = (datetime.fromisoformat(captured) - timedelta(seconds=1)).isoformat()
        self.server.coordinator.ingest(
            {"captured_at": older_capture, "metrics": {"pv_dc_power_w": 2000.0}}
        )
        points = self.server.coordinator.history("neighbor", 60)["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["pv_power"], 2000.0)
        self.assertEqual(points[0]["target_generation"], changed["target_generation"])
        self.assertEqual(points[0]["neighbor_target"]["port"], 1502)
        self.assertEqual(
            self.server.coordinator.latest("neighbor")["metrics"]["pv_power_w"], 2000.0
        )

        reopened_with_current_sample = PeerCoordinator(self.primary, Path(self.temp.name))
        self.assertEqual(
            reopened_with_current_sample.latest("neighbor")["metrics"]["pv_power_w"],
            2000.0,
        )

    def test_admin_browser_origin_is_restricted(self) -> None:
        status, _, _ = self.request(
            "POST", "/v1/admin/config", {"host": "192.168.50.30"},
            {"Origin": "https://attacker.example", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)

    def test_openapi_and_cors_are_explicit(self) -> None:
        self.assertEqual(self.request("GET", "/openapi.json")[2]["openapi"], "3.1.0")
        origin = "http://127.0.0.1:8765"
        status, headers, _ = self.request("GET", "/v1", headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)


class DiskTelemetryReaderTests(unittest.TestCase):
    def test_primary_journal_connection_is_enforced_read_only(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "primary.sqlite3"
            history = TelemetryHistory(storage_path=path)
            history.record(snapshot(987.654), source="test")
            reader = DiskTelemetryReader(path)

            self.assertEqual(reader.latest_snapshot()["sensors"]["pv_power"]["value"], 987.654)
            with closing(reader._connect()) as connection:
                self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden_write (id INTEGER)")


if __name__ == "__main__":
    unittest.main()
