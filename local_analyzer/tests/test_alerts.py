from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest

from solarmax_analyzer.alerts import AlertEngine
from solarmax_analyzer.peer_store import PeerStateStore


def comparison(
    primary: float,
    neighbor: float,
    pairs: int = 6,
    *,
    captured_at: str | None = None,
) -> dict:
    captured = captured_at or datetime.now(timezone.utc).isoformat()
    point = {
        "comparable": True,
        "skew_ms": 1000,
        "primary_captured_at": captured,
        "neighbor_captured_at": captured,
        "primary": {"specific_power_w_kwp": primary},
        "neighbor": {"specific_power_w_kwp": neighbor},
    }
    return {
        "alignment": {"pair_count": pairs, "comparable_pair_count": pairs},
        "latest": point,
        "points": [dict(point) for _ in range(pairs)],
    }


class AlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.now = datetime.now(timezone.utc).timestamp()
        self.store = PeerStateStore(Path(self.temp.name) / "alerts.sqlite3")
        self.engine = AlertEngine(self.store, clock=lambda: self.now)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_underperformance_needs_explicit_enable_and_sustained_duration(self) -> None:
        disabled = self.engine._performance_alert(comparison(500, 250), self.engine.rules()["peer_underperformance"])
        self.assertEqual(disabled["state"], "calibration_required")
        rules = self.engine.update_rules({
            "peer_underperformance": {
                "enabled": True,
                "trigger_for_seconds": 20,
                "clear_for_seconds": 10,
            }
        })
        first = self.engine._performance_alert(comparison(500, 250), rules["peer_underperformance"])
        self.assertEqual(first["state"], "pending")
        self.now += 21
        firing = self.engine._performance_alert(comparison(500, 250), rules["peer_underperformance"])
        self.assertEqual(firing["state"], "firing")
        self.now += 1
        recovering = self.engine._performance_alert(comparison(500, 480), rules["peer_underperformance"])
        self.assertEqual(recovering["state"], "recovering")
        self.now += 11
        healthy = self.engine._performance_alert(comparison(500, 480), rules["peer_underperformance"])
        self.assertEqual(healthy["state"], "healthy")

    def test_low_light_is_suppressed_and_cannot_clear_open_alert(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {"enabled": True, "trigger_for_seconds": 0}
        })
        self.assertEqual(self.engine._performance_alert(comparison(500, 200), rules["peer_underperformance"])["state"], "firing")
        held = self.engine._performance_alert(comparison(10, 0), rules["peer_underperformance"])
        self.assertEqual(held["state"], "firing")
        self.assertEqual(held["details"]["evaluation"], "suppressed")

    def test_alert_transitions_survive_reopen_and_are_deduplicated(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {"enabled": True, "trigger_for_seconds": 0}
        })
        self.engine._performance_alert(comparison(500, 200), rules["peer_underperformance"])
        self.engine._performance_alert(comparison(500, 200), rules["peer_underperformance"])
        events = self.store.alert_events()
        self.assertEqual(sum(event["alert_id"] == "peer_underperformance" for event in events), 1)
        reopened = PeerStateStore(Path(self.temp.name) / "alerts.sqlite3")
        self.assertEqual(reopened.state("peer_underperformance")["state"], "firing")

    def test_neighbor_target_change_resets_durable_alert_lifecycles(self) -> None:
        initial = self.store.update_config({"host": "192.168.50.30"})
        updated_at = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
        for alert_id, state, pending_since, recovering_since in (
            ("neighbor_stale", "firing", None, None),
            ("peer_underperformance", "recovering", self.now - 60, self.now - 5),
        ):
            self.store.save_alert_state(
                {
                    "id": alert_id,
                    "state": state,
                    "pending_since": pending_since,
                    "recovering_since": recovering_since,
                    "opened_at": updated_at,
                    "resolved_at": None,
                    "updated_at": updated_at,
                    "message": "old target state",
                    "severity": "warning",
                    "device_id": "neighbor",
                    "details": {},
                },
                emit_event=False,
            )
        self.store.save_alert_state(
            {
                "id": "primary_fault_words",
                "state": "healthy",
                "pending_since": None,
                "recovering_since": None,
                "opened_at": None,
                "resolved_at": None,
                "updated_at": updated_at,
                "message": "primary state",
                "severity": "info",
                "device_id": "primary",
                "details": {},
            },
            emit_event=False,
        )

        self.store.update_config({"name": "Same target"})
        self.assertEqual(self.store.state("peer_underperformance")["state"], "recovering")
        changed = self.store.update_config({"port": 1502})

        self.assertEqual(changed["target_generation"], initial["target_generation"] + 1)
        self.assertIsNone(self.store.state("neighbor_stale"))
        self.assertIsNone(self.store.state("peer_underperformance"))
        self.assertEqual(self.store.state("primary_fault_words")["state"], "healthy")
        resets = [event for event in self.store.alert_events() if event["state"] == "target_changed"]
        self.assertEqual({event["alert_id"] for event in resets}, {"neighbor_stale", "peer_underperformance"})
        for event in resets:
            self.assertEqual(event["details"]["previous_target_generation"], initial["target_generation"])
            self.assertEqual(event["details"]["current_target_generation"], changed["target_generation"])
            self.assertEqual(event["details"]["current_target"]["port"], 1502)

        reopened = PeerStateStore(Path(self.temp.name) / "alerts.sqlite3")
        self.assertIsNone(reopened.state("neighbor_stale"))
        self.assertIsNone(reopened.state("peer_underperformance"))

    def test_concurrent_target_patches_serialize_generation_updates(self) -> None:
        initial = self.store.update_config({"host": "192.168.50.30"})
        other_store = PeerStateStore(Path(self.temp.name) / "alerts.sqlite3")
        start = threading.Barrier(3)
        results: list[dict] = []
        errors: list[Exception] = []

        def update(store: PeerStateStore, patch: dict) -> None:
            start.wait()
            try:
                results.append(store.update_config(patch))
            except Exception as exc:
                errors.append(exc)

        port_thread = threading.Thread(target=update, args=(self.store, {"port": 1502}))
        unit_thread = threading.Thread(target=update, args=(other_store, {"unit_id": 2}))
        port_thread.start()
        unit_thread.start()
        start.wait()
        port_thread.join(3)
        unit_thread.join(3)

        self.assertFalse(port_thread.is_alive())
        self.assertFalse(unit_thread.is_alive())
        self.assertEqual(errors, [])
        current = self.store.config()
        self.assertEqual((current["port"], current["unit_id"]), (1502, 2))
        self.assertEqual(current["target_generation"], initial["target_generation"] + 2)
        self.assertEqual(
            sorted(result["target_generation"] for result in results),
            [initial["target_generation"] + 1, initial["target_generation"] + 2],
        )

    def test_monitoring_off_and_partial_capture_are_not_healthy(self) -> None:
        rule = self.engine.rules()["primary_stale"]
        restored = {"ok": True, "captured_at": datetime.fromtimestamp(self.now - 500, timezone.utc).isoformat()}
        self.assertEqual(
            self.engine._stale_alert("primary_stale", "primary", restored, rule, monitoring_enabled=False)["state"],
            "monitoring_disabled",
        )
        partial = {"ok": False, "captured_at": datetime.fromtimestamp(self.now, timezone.utc).isoformat()}
        self.assertEqual(
            self.engine._stale_alert("primary_stale", "primary", partial, rule, monitoring_enabled=True)["state"],
            "firing",
        )

    def test_missing_fault_word_cannot_clear_prior_fault(self) -> None:
        rule = self.engine.rules()["primary_fault_words"]
        fault = {"sensors": {key: {"value": 1 if key == "error_1" else 0} for key in ("error_1", "error_2", "error_3", "error_4")}}
        self.assertEqual(self.engine._fault_alert(fault, rule)["state"], "firing")
        partial = {"sensors": {"error_1": {"value": 0}}}
        self.assertEqual(self.engine._fault_alert(partial, rule)["state"], "firing")

    def test_missing_data_resets_pending_duration(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {"enabled": True, "trigger_for_seconds": 20}
        })
        self.assertEqual(self.engine._performance_alert(comparison(500, 250), rules["peer_underperformance"])["state"], "pending")
        self.now += 10
        self.assertEqual(self.engine._performance_alert({"alignment": {"pair_count": 0}, "latest": None}, rules["peer_underperformance"])["state"], "calibrating")
        self.now += 15
        self.assertEqual(self.engine._performance_alert(comparison(500, 250), rules["peer_underperformance"])["state"], "pending")

    def test_old_comparable_pairs_do_not_satisfy_minimum_pair_gate(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {"enabled": True, "minimum_pairs": 6}
        })
        old = comparison(
            500,
            250,
            captured_at=datetime.fromtimestamp(self.now - 120, timezone.utc).isoformat(),
        )
        fresh = comparison(
            500,
            250,
            pairs=1,
            captured_at=datetime.fromtimestamp(self.now, timezone.utc).isoformat(),
        )
        payload = {
            "alignment": {"pair_count": 7, "comparable_pair_count": 7},
            "latest": fresh["latest"],
            "points": old["points"] + fresh["points"],
        }

        result = self.engine._performance_alert(payload, rules["peer_underperformance"])

        self.assertEqual(result["state"], "calibrating")
        self.assertEqual(result["details"]["comparable_pair_count"], 7)
        self.assertEqual(result["details"]["recent_comparable_pair_count"], 1)

    def test_non_comparable_aligned_pairs_do_not_satisfy_minimum_pair_gate(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {"enabled": True, "minimum_pairs": 6}
        })
        payload = comparison(500, 250, pairs=5)
        captured = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
        payload["points"].extend(
            {
                "comparable": False,
                "skew_ms": 0,
                "primary_captured_at": captured,
                "neighbor_captured_at": captured,
                "primary": {"specific_power_w_kwp": 500},
                "neighbor": {"specific_power_w_kwp": None},
            }
            for _ in range(20)
        )
        payload["alignment"] = {"pair_count": 25, "comparable_pair_count": 5}

        result = self.engine._performance_alert(payload, rules["peer_underperformance"])

        self.assertEqual(result["state"], "calibrating")
        self.assertEqual(result["details"]["aligned_pair_count"], 25)
        self.assertEqual(result["details"]["recent_comparable_pair_count"], 5)

    def test_later_non_comparable_pair_does_not_hide_recent_comparable_pair(self) -> None:
        rules = self.engine.update_rules({
            "peer_underperformance": {
                "enabled": True,
                "minimum_pairs": 2,
                "trigger_for_seconds": 0,
            }
        })
        payload = comparison(500, 200, pairs=2)
        captured = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
        latest_aligned = {
            "comparable": False,
            "skew_ms": 0,
            "primary_captured_at": captured,
            "neighbor_captured_at": captured,
            "primary": {"specific_power_w_kwp": 500},
            "neighbor": {"specific_power_w_kwp": None},
        }
        payload["points"].append(latest_aligned)
        payload["alignment"] = {"pair_count": 3, "comparable_pair_count": 2}
        payload["latest"] = latest_aligned

        result = self.engine._performance_alert(payload, rules["peer_underperformance"])

        self.assertEqual(result["state"], "firing")
        self.assertEqual(result["details"]["recent_comparable_pair_count"], 2)
        self.assertEqual(result["details"]["neighbor_w_per_kwp"], 200)

    def test_rule_batch_validates_every_rule_before_persisting(self) -> None:
        before = self.engine.rules()
        with self.assertRaises(ValueError):
            self.engine.update_rules({
                "primary_stale": {"stale_after_seconds": 120},
                "peer_underperformance": {
                    "deficit_percent": 10,
                    "clear_deficit_percent": 20,
                },
            })
        self.assertEqual(self.engine.rules(), before)

    def test_rule_batch_rolls_back_when_a_database_write_fails(self) -> None:
        with closing(self.store._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TRIGGER reject_neighbor_rule
                BEFORE INSERT ON alert_rules
                WHEN NEW.id = 'neighbor_stale'
                BEGIN
                    SELECT RAISE(ABORT, 'injected rule write failure');
                END
                """
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.engine.update_rules({
                "primary_stale": {"stale_after_seconds": 120},
                "neighbor_stale": {"stale_after_seconds": 180},
            })
        self.assertEqual(self.engine.rules()["primary_stale"]["stale_after_seconds"], 45)
        self.assertEqual(self.engine.rules()["neighbor_stale"]["stale_after_seconds"], 45)

    def test_server_received_time_is_used_for_ingest_freshness(self) -> None:
        rule = self.engine.rules()["neighbor_stale"]
        snapshot = {
            "ok": True,
            "captured_at": datetime.fromtimestamp(self.now + 240, timezone.utc).isoformat(),
            "received_at": datetime.fromtimestamp(self.now - 60, timezone.utc).isoformat(),
        }
        alert = self.engine._stale_alert(
            "neighbor_stale", "neighbor", snapshot, rule, monitoring_enabled=True
        )
        self.assertEqual(alert["state"], "firing")
        self.assertEqual(alert["details"]["age_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
