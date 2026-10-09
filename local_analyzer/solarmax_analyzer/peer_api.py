from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import sqlite3
import threading
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlsplit
import zlib

from .alerts import AlertEngine
from .eybond import capture_pi18_telemetry, fingerprint_collector
from .history import TelemetryHistory
from .peer import (
    PRIMARY_SYSTEM,
    build_neighbor_snapshot,
    canonical_latest,
    comparison_payload,
)
from .peer_openapi import build_openapi_document
from .peer_store import PeerStateStore


class HistoryView(Protocol):
    def query(self, minutes: int = 60) -> list[dict[str, Any]]: ...
    def latest_snapshot(self) -> dict[str, Any] | None: ...
    def storage_status(self) -> dict[str, Any]: ...


class DiskTelemetryReader:
    """Live read-through view of another process's WAL-backed telemetry DB."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        # The standalone comparison service is a consumer of the SolarMax
        # journal, never a second writer.  SQLite URI read-only mode makes that
        # boundary enforceable even if future code accidentally issues SQL that
        # would mutate the primary database.
        database_uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(database_uri, timeout=5, uri=True)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA query_only=ON")
        return connection

    def query(self, minutes: int = 60) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT point_json FROM telemetry_samples WHERE timestamp_ms>=? ORDER BY timestamp_ms,id",
                (round(cutoff.timestamp() * 1000),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def latest_snapshot(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        with closing(self._connect()) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(telemetry_samples)")
            }
            receipt_order = (
                ", received_at IS NULL, received_at DESC" if "received_at" in columns else ""
            )
            row = connection.execute(
                "SELECT snapshot_zlib FROM telemetry_samples "
                "ORDER BY timestamp_ms IS NULL, timestamp_ms DESC"
                f"{receipt_order}, id ASC LIMIT 1"
            ).fetchone()
        return json.loads(zlib.decompress(row[0]).decode("utf-8")) if row else None

    def storage_status(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"persistent": True, "path": str(self.path), "saved_samples": 0, "error": None}
        try:
            with closing(self._connect()) as connection:
                count, last = connection.execute(
                    "SELECT COUNT(*),MAX(recorded_at) FROM telemetry_samples"
                ).fetchone()
            return {"persistent": True, "path": str(self.path), "saved_samples": count, "last_saved_at": last, "error": None}
        except sqlite3.Error as exc:
            return {"persistent": True, "path": str(self.path), "saved_samples": None, "error": f"{type(exc).__name__}: {exc}"}


class PeerCoordinator:
    """Owns the Knox-side state. It never calls the SolarMax profile or controls."""

    def __init__(
        self,
        primary_history: HistoryView,
        data_dir: str | Path,
        *,
        primary_status: Callable[[], dict[str, Any]] | None = None,
        automatic_collection: bool = True,
    ) -> None:
        data_path = Path(data_dir)
        self.primary_history = primary_history
        self.neighbor_history = TelemetryHistory(storage_path=data_path / "telemetry-neighbor.sqlite3")
        self.state_store = PeerStateStore(data_path / "peer-state.sqlite3")
        self.alert_engine = AlertEngine(self.state_store)
        self.primary_status = primary_status
        self._automatic_collection_enabled = bool(automatic_collection)
        self._target_lock = threading.RLock()
        self._probe_lock = threading.Lock()
        self._alert_lock = threading.Lock()
        self._alert_stop = threading.Event()
        self._alert_thread: threading.Thread | None = None
        self._last_alert_evaluation: str | None = None
        self._last_alert_error: str | None = None
        self._collector_stop = threading.Event()
        self._collector_thread: threading.Thread | None = None
        self._collector_attempts = 0
        self._collector_successes = 0
        self._collector_last_attempt: str | None = None
        self._collector_last_success: str | None = None
        self._collector_last_error: str | None = None
        self._collector_last_duration_ms: float | None = None

    def start(self) -> None:
        if not self._alert_thread or not self._alert_thread.is_alive():
            self._alert_thread = threading.Thread(
                target=self._alert_loop, name="peer-alert-engine", daemon=True
            )
            self._alert_thread.start()
        if (
            self._automatic_collection_enabled
            and (not self._collector_thread or not self._collector_thread.is_alive())
        ):
            self._collector_thread = threading.Thread(
                target=self._collector_loop, name="knox-eybond-collector", daemon=True
            )
            self._collector_thread.start()

    def stop(self) -> None:
        self._alert_stop.set()
        self._collector_stop.set()
        if self._alert_thread and self._alert_thread.is_alive():
            self._alert_thread.join(timeout=5)
        if self._collector_thread and self._collector_thread.is_alive():
            self._collector_thread.join(timeout=10)

    def _alert_loop(self) -> None:
        while not self._alert_stop.is_set():
            try:
                self.alerts()
                self._last_alert_error = None
            except Exception as exc:
                # Alert persistence can never trigger an inverter collector
                # fallback or stop either telemetry API.
                self._last_alert_error = f"{type(exc).__name__}: {exc}"
            self._alert_stop.wait(10)

    def config(self) -> dict[str, Any]:
        config = self.state_store.config()
        system = self.state_store.system_from_config(config)
        return {
            **config,
            "configured": bool(config.get("host")),
            "array": system.to_dict()["array"],
            "controls_available": False,
            "automatic_collection": bool(
                self._automatic_collection_enabled
                and config.get("host")
                and config.get("collection_mode") == "local"
                and self._collector_thread
                and self._collector_thread.is_alive()
            ),
        }

    def _collector_status(self) -> dict[str, Any]:
        config = self.state_store.config()
        scheduler_running = bool(self._collector_thread and self._collector_thread.is_alive())
        active = bool(
            self._automatic_collection_enabled
            and scheduler_running
            and config.get("host")
            and config.get("collection_mode") == "local"
        )
        return {
            "enabled": self._automatic_collection_enabled,
            "running": active,
            "scheduler_running": scheduler_running,
            "collection_mode": config.get("collection_mode", "local"),
            "transport": "eybond_transient_callback",
            "stored_cloud_endpoint_unchanged": True,
            "cloud_session_continuity": "not_verified",
            "expected_interval_seconds": config.get("expected_interval_seconds", 180),
            "attempts": self._collector_attempts,
            "successes": self._collector_successes,
            "last_attempt_at": self._collector_last_attempt,
            "last_success_at": self._collector_last_success,
            "last_duration_ms": self._collector_last_duration_ms,
            "last_error": self._collector_last_error,
            "listener_port": config.get("callback_port", 8899),
            "discovery_port": config.get("udp_port", 58899),
            "collector_pn": config.get("collector_pn"),
            "saved_cloud_endpoint": config.get("cloud_endpoint"),
        }

    def _callback_probe(self, config: dict[str, Any]) -> dict[str, Any]:
        callback = fingerprint_collector(
            str(config["host"]),
            advertised_host=config.get("callback_host"),
            callback_port=int(config.get("callback_port", 8899)),
            udp_port=int(config.get("udp_port", 58899)),
            timeout=12,
            read_inverter=True,
            inverter_protocol="pi18",
        )
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "host": config["host"],
            "port": config["port"],
            "unit_id": config["unit_id"],
            "target_generation": config["target_generation"],
            "tcp": {
                "ok": False,
                "skipped": True,
                "reason": "EyeBond logger is an outbound callback client, not a Modbus/TCP server",
            },
            "callback": callback,
            "device_identification": {
                "collector_pn": callback.get("collector_pn"),
                "firmware": callback.get("metadata", {}).get("firmware_version"),
                "hardware": callback.get("metadata", {}).get("hardware_version"),
                "protocol": callback.get("inverter", {}).get("protocol_id"),
                "inverter_serial_raw": callback.get("inverter", {}).get("inverter_serial_raw"),
            } if callback.get("ok") else None,
            "read_only": True,
            "function_attempted": "EyeBond FC1/FC2 + PI18 reads",
            "register_reads": 0,
            "write_requests": 0,
            "decoder_activated": bool(callback.get("inverter", {}).get("telemetry")),
        }

    @staticmethod
    def _telemetry_sensor(key: str, value: Any) -> dict[str, Any]:
        metadata = {
            "grid_voltage_v": ("Grid voltage", "V", "Grid"),
            "grid_frequency_hz": ("Grid frequency", "Hz", "Grid"),
            "output_voltage_v": ("AC output voltage", "V", "Output"),
            "output_frequency_hz": ("AC output frequency", "Hz", "Output"),
            "output_apparent_power_va": ("AC output apparent power", "VA", "Output"),
            "output_active_power_w": ("AC output active power", "W", "Output"),
            "load_percent": ("Output load", "%", "Output"),
            "battery_voltage_v": ("Battery voltage", "V", "Battery"),
            "battery_discharge_current_a": ("Battery discharge current", "A", "Battery"),
            "battery_charge_current_a": ("Battery charge current", "A", "Battery"),
            "battery_soc_percent": ("Battery state of charge", "%", "Battery"),
            "battery_power_w": ("Battery power balance", "W", "Battery"),
            "inverter_temperature_c": ("Inverter heat-sink temperature", "°C", "Inverter"),
            "mppt1_temperature_c": ("MPPT 1 temperature", "°C", "PV inputs"),
            "mppt2_temperature_c": ("MPPT 2 temperature", "°C", "PV inputs"),
            "pv1_power_w": ("PV 1 input power", "W", "PV inputs"),
            "pv2_power_w": ("PV 2 input power", "W", "PV inputs"),
            "pv1_voltage_v": ("PV 1 input voltage", "V", "PV inputs"),
            "pv2_voltage_v": ("PV 2 input voltage", "V", "PV inputs"),
            "pv_power_w": ("PV total input power", "W", "PV inputs"),
        }
        name, unit, category = metadata.get(
            key, (key.replace("_", " ").title(), "", "Diagnostics")
        )
        return {
            "name": name,
            "value": value,
            "unit": unit,
            "category": category,
            "quality": "measured",
            "provenance": "knox_eybond_pi18",
        }

    def _record_callback_capture(
        self,
        config: dict[str, Any],
        callback: dict[str, Any],
    ) -> None:
        inverter = callback.get("inverter") if isinstance(callback.get("inverter"), dict) else {}
        telemetry = callback.get("telemetry") or inverter.get("telemetry")
        if not callback.get("ok") or not isinstance(telemetry, dict) or not telemetry:
            raise RuntimeError(callback.get("error") or "EyeBond callback returned no PI18 telemetry")
        payload = {
            "captured_at": callback.get("captured_at") or datetime.now(timezone.utc).isoformat(),
            "driver": "knox_eybond_pi18",
            "profile_confidence": "verified",
            "provenance": "knox_eybond_pi18",
            "metrics": {
                "pv_dc_power_w": telemetry.get("pv_power_w"),
                "ac_output_power_w": telemetry.get("output_active_power_w"),
                "battery_soc_percent": telemetry.get("battery_soc_percent"),
            },
        }
        system = self.state_store.system_from_config(config)
        snapshot = build_neighbor_snapshot(payload, system)
        aliases = {
            "battery_power_w": "battery_power",
            "battery_voltage_v": "battery_voltage",
            "grid_voltage_v": "grid_voltage",
            "grid_frequency_hz": "grid_frequency",
            "output_voltage_v": "output_voltage",
            "output_frequency_hz": "output_frequency",
            "pv1_power_w": "pv1_power",
            "pv2_power_w": "pv2_power",
            "pv1_voltage_v": "pv1_voltage",
            "pv2_voltage_v": "pv2_voltage",
        }
        for key, value in telemetry.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                snapshot["sensors"][aliases.get(key, f"pi18_{key}")] = self._telemetry_sensor(key, value)
        mode_code = str(callback.get("operating_mode_code") or inverter.get("operating_mode_code") or "")
        mode_names = {"00": "Power on", "01": "Standby", "02": "Bypass", "03": "Battery", "04": "Fault", "05": "Hybrid"}
        snapshot["sensors"]["inverter_mode"] = {
            "name": "Operating mode", "value": mode_names.get(mode_code, mode_code or "Unknown"),
            "unit": "", "category": "Inverter", "quality": "measured",
            "provenance": "knox_eybond_pi18",
        }
        snapshot["sensor_count"] = len(snapshot["sensors"])
        snapshot["elapsed_ms"] = callback.get("duration_ms")
        snapshot["collector"] = {
            "pn": callback.get("collector_pn"),
            "callback_host": callback.get("callback_host"),
            "callback_port": callback.get("callback_port"),
            "stored_cloud_endpoint_unchanged": callback.get("stored_endpoint_changed") is False,
            "cloud_session_continuity": "not_verified",
        }
        snapshot["raw_protocol"] = {
            "family": "PI18",
            "responses": callback.get("raw_responses") or inverter.get("raw_responses") or {},
            "telemetry": telemetry,
        }
        snapshot["target_generation"] = config["target_generation"]
        snapshot["neighbor_target"] = self._neighbor_target(config)
        self.neighbor_history.record_once(snapshot, source="knox_eybond_pi18_callback")

    def _collector_loop(self) -> None:
        while not self._collector_stop.is_set():
            cycle_started = datetime.now(timezone.utc)
            with self._target_lock:
                config = self.config()
            interval = max(10, int(config.get("expected_interval_seconds", 180)))
            if not config.get("configured"):
                self._collector_stop.wait(2)
                continue
            if config.get("collection_mode") != "local":
                self._collector_last_error = None
                self._collector_stop.wait(2)
                continue
            if not self._probe_lock.acquire(blocking=False):
                self._collector_stop.wait(1)
                continue
            try:
                self._collector_attempts += 1
                self._collector_last_attempt = datetime.now(timezone.utc).isoformat()
                if config.get("driver") == "knox_eybond_pi18" and config.get("collector_pn"):
                    callback = capture_pi18_telemetry(
                        str(config["host"]),
                        advertised_host=config.get("callback_host"),
                        callback_port=int(config.get("callback_port", 8899)),
                        udp_port=int(config.get("udp_port", 58899)),
                        timeout=8,
                        expected_collector_pn=str(config.get("collector_pn") or ""),
                    )
                else:
                    evidence = self._callback_probe(config)
                    saved = self.state_store.save_probe(
                        evidence,
                        expected_target=self.state_store.target_tuple(config),
                        expected_generation=int(config["target_generation"]),
                    )
                    if saved is None:
                        raise RuntimeError("neighbor target changed during protocol detection")
                    callback = evidence["callback"]
                with self._target_lock:
                    current = self.config()
                    if current["target_generation"] != config["target_generation"]:
                        raise RuntimeError("neighbor target changed while telemetry was in flight")
                    self._record_callback_capture(current, callback)
                self._collector_successes += 1
                self._collector_last_success = datetime.now(timezone.utc).isoformat()
                self._collector_last_duration_ms = callback.get("duration_ms")
                self._collector_last_error = None
            except Exception as exc:
                self._collector_last_error = f"{type(exc).__name__}: {exc}"
                self.neighbor_history.record_error(
                    "knox_eybond_pi18_callback", exc,
                    {"host": config.get("host"), "target_generation": config.get("target_generation")},
                )
            finally:
                self._probe_lock.release()
            elapsed = (datetime.now(timezone.utc) - cycle_started).total_seconds()
            self._collector_stop.wait(max(0.1, interval - elapsed))

    @staticmethod
    def _neighbor_target(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "host": config.get("host"),
            "port": int(config["port"]),
            "unit_id": int(config["unit_id"]),
        }

    @classmethod
    def _matches_neighbor_target(
        cls, record: dict[str, Any] | None, config: dict[str, Any]
    ) -> bool:
        if not record or record.get("target_generation") != config.get("target_generation"):
            return False
        target = record.get("neighbor_target")
        if not isinstance(target, dict):
            return False
        try:
            return cls._neighbor_target(target) == cls._neighbor_target(config)
        except (KeyError, TypeError, ValueError):
            return False

    def _neighbor_snapshot(self, config: dict[str, Any]) -> dict[str, Any] | None:
        return self.neighbor_history.latest_snapshot(
            lambda snapshot: self._matches_neighbor_target(snapshot, config)
        )

    def _neighbor_points(self, config: dict[str, Any], minutes: int) -> list[dict[str, Any]]:
        return [
            point
            for point in self.neighbor_history.query(minutes)
            if self._matches_neighbor_target(point, config)
        ]

    def _freshness_thresholds(
        self,
        config: dict[str, Any],
        primary_state: dict[str, Any],
    ) -> dict[str, Any]:
        primary_interval = float(primary_state.get("interval_seconds", 180))
        primary_derived = 3 * primary_interval + 15
        if primary_state.get("mode") == "cooperative":
            primary_derived += 2 * float(primary_state.get("quiet_window_seconds", 45))
        neighbor_interval = float(config.get("expected_interval_seconds", 180))
        neighbor_derived = 3 * neighbor_interval + 15
        rules = self.alert_engine.rules()
        return {
            "primary_stale_after_seconds": max(
                float(rules["primary_stale"]["stale_after_seconds"]), primary_derived
            ),
            "neighbor_stale_after_seconds": max(
                float(rules["neighbor_stale"]["stale_after_seconds"]), neighbor_derived
            ),
            "primary_interval_seconds": primary_interval,
            "primary_collection_mode": primary_state.get("mode"),
            "neighbor_expected_interval_seconds": neighbor_interval,
        }

    def systems(self) -> dict[str, Any]:
        config = self.config()
        neighbor_system = self.state_store.system_from_config(config)
        return {
            "schema_version": "1.0",
            "systems": [
                {**PRIMARY_SYSTEM.to_dict(), "configured": True, "driver": "solarmax_senergy_verified", "controls_available": True},
                {**neighbor_system.to_dict(), "configured": config["configured"], "driver": config["driver"], "protocol_status": config["protocol_status"], "controls_available": False},
            ],
        }

    def latest(self, device_id: str) -> dict[str, Any]:
        if device_id == "primary":
            return canonical_latest(self.primary_history.latest_snapshot(), PRIMARY_SYSTEM)
        if device_id != "neighbor":
            raise KeyError(device_id)
        with self._target_lock:
            config = self.config()
            system = self.state_store.system_from_config(config)
            result = canonical_latest(self._neighbor_snapshot(config), system)
            result["configured"] = config["configured"]
            result["protocol_status"] = config["protocol_status"]
            result["automatic_collection"] = config["automatic_collection"]
            result["collection_mode"] = config.get("collection_mode", "local")
            result["identity"] = {
                "collector_pn": config.get("collector_pn"),
                "saved_cloud_endpoint": config.get("cloud_endpoint"),
                "transport": config.get("transport"),
            }
            snapshot = self._neighbor_snapshot(config)
            if snapshot:
                result["telemetry"] = snapshot.get("raw_protocol", {}).get("telemetry", {})
                result["sensors"] = snapshot.get("sensors", {})
                result["collector"] = snapshot.get("collector", {})
            if not result["available"]:
                result["reason"] = (
                    "neighbor_not_configured" if not config["configured"]
                    else "capture_pending" if config["protocol_status"] == "verified"
                    else "decoder_not_verified"
                )
        return result

    def history(self, device_id: str, minutes: int) -> dict[str, Any]:
        if device_id == "primary":
            history, system = self.primary_history, PRIMARY_SYSTEM
            points = history.query(minutes)
        elif device_id == "neighbor":
            with self._target_lock:
                config = self.config()
                history = self.neighbor_history
                system = self.state_store.system_from_config(config)
                points = self._neighbor_points(config, minutes)
        else:
            raise KeyError(device_id)
        return {
            "schema_version": "1.0",
            "device": system.to_dict(),
            "minutes": minutes,
            "count": len(points),
            "points": points,
            "storage": history.storage_status(),
        }

    def comparison(self, minutes: int = 60, max_skew_seconds: int = 15) -> dict[str, Any]:
        with self._target_lock:
            config = self.config()
            payload = comparison_payload(
                self.primary_history.query(minutes),
                self._neighbor_points(config, minutes),
                self.state_store.system_from_config(config),
                max_skew_seconds=max_skew_seconds,
            )
            payload["minutes"] = minutes
            payload["configured"] = config["configured"]
            if not config["configured"] and not payload["available"]:
                payload["reason"] = "neighbor_not_configured"
            elif config["protocol_status"] != "verified" and not payload["available"]:
                payload["reason"] = "decoder_not_verified"
        return payload

    def alerts(self) -> dict[str, Any]:
        with self._alert_lock, self._target_lock:
            config = self.config()
            comparison = self.comparison(60)
            primary_state = self.primary_status() if self.primary_status else {}
            primary_snapshot = self.primary_history.latest_snapshot()
            freshness = self._freshness_thresholds(config, primary_state)
            evaluated = self.alert_engine.evaluate(
                primary_snapshot,
                self._neighbor_snapshot(config),
                self.state_store.system_from_config(config),
                config,
                comparison,
                primary_monitoring=bool(primary_state.get("background_polling", primary_snapshot is not None)),
                primary_stale_after_seconds=freshness["primary_stale_after_seconds"],
                neighbor_stale_after_seconds=freshness["neighbor_stale_after_seconds"],
            )
            self._last_alert_evaluation = datetime.now(timezone.utc).isoformat()
        active_states = {"pending", "firing", "recovering"}
        return {
            "schema_version": "1.0",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "active_count": sum(item["state"] in active_states for item in evaluated),
            "firing_count": sum(item["state"] == "firing" for item in evaluated),
            "alerts": evaluated,
            "rules": self.alert_engine.rules(),
            "freshness": freshness,
            "events": self.state_store.alert_events(50),
            "scheduler": {
                "running": bool(self._alert_thread and self._alert_thread.is_alive()),
                "interval_seconds": 10,
                "last_evaluated_at": self._last_alert_evaluation,
                "last_error": self._last_alert_error,
            },
        }

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._target_lock:
            self.state_store.update_config(patch)
            return self.config()

    def update_rules(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.alert_engine.update_rules(patch)

    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._target_lock:
            config = self.config()
            system = self.state_store.system_from_config(config)
            snapshot = build_neighbor_snapshot(payload, system)
            snapshot["target_generation"] = config["target_generation"]
            snapshot["neighbor_target"] = self._neighbor_target(config)
            point, duplicate, stored_snapshot = self.neighbor_history.record_once(
                snapshot, source="neighbor_api_ingest"
            )
            return {
                "accepted": True,
                "duplicate": duplicate,
                "writes_to_inverter": False,
                "snapshot": canonical_latest(stored_snapshot, system),
                "history_point": point,
            }

    def probe(self) -> dict[str, Any]:
        with self._target_lock:
            config = self.config()
        if not config["configured"]:
            raise ValueError("save the exact neighbor IP before probing")
        if not self._probe_lock.acquire(blocking=False):
            raise RuntimeError("a neighbor identification probe is already running")
        try:
            evidence = self._callback_probe(config)
            saved = self.state_store.save_probe(
                evidence,
                expected_target=self.state_store.target_tuple(config),
                expected_generation=int(config["target_generation"]),
            )
            if saved is None:
                raise RuntimeError(
                    "neighbor target changed while the probe was running; result discarded"
                )
            if evidence.get("callback", {}).get("inverter", {}).get("telemetry"):
                with self._target_lock:
                    self._record_callback_capture(self.config(), evidence["callback"])
            return evidence
        finally:
            self._probe_lock.release()

    def status(self) -> dict[str, Any]:
        config = self.config()
        primary_state = self.primary_status() if self.primary_status else {}
        latest = self.latest("neighbor")
        return {
            "service": "knox-neighbor-api",
            "schema_version": "1.0",
            "configured": config["configured"],
            "protocol_status": config["protocol_status"],
            "driver": config["driver"],
            "automatic_collection": config["automatic_collection"],
            "reason": (
                "exact_ip_required" if not config["configured"]
                else "original_cloud_mode" if config.get("collection_mode") == "original"
                else "read_only_fingerprint_required" if config["protocol_status"] == "awaiting_read_only_fingerprint"
                else "collecting" if config["protocol_status"] == "verified"
                else "protocol_detection_pending"
            ),
            "latest": latest,
            "freshness": self._freshness_thresholds(config, primary_state),
            "storage": self.neighbor_history.storage_status(),
            "collector": self._collector_status(),
            "safety": {
                "inverter_writes": False,
                "collector_setting_writes": False,
                "stored_cloud_endpoint_unchanged": True,
                "cloud_session_continuity": "not_verified",
                "solarmax_driver_reused": False,
                "controls_exposed": False,
            },
            "alert_scheduler": {
                "running": bool(self._alert_thread and self._alert_thread.is_alive()),
                "interval_seconds": 10,
                "last_evaluated_at": self._last_alert_evaluation,
                "last_error": self._last_alert_error,
            },
        }


def openapi_document(port: int) -> dict[str, Any]:
    return build_openapi_document(port)


class PeerApiHandler(BaseHTTPRequestHandler):
    server_version = "KnoxNeighborAPI/1.0"

    @property
    def coordinator(self) -> PeerCoordinator:
        return self.server.coordinator

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[Knox API {self.log_date_time_string()}] {fmt % args}")

    def _cors_origin(self, *, admin: bool = False) -> str | None:
        origin = self.headers.get("Origin")
        allowed = self.server.admin_origins if admin else self.server.allowed_origins
        return origin if origin in allowed else None

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 100_000:
            raise ValueError("request body too large")
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _admin_allowed(self) -> bool:
        try:
            loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            loopback = False
        origin = self.headers.get("Origin")
        return (
            loopback
            and self.headers.get_content_type() == "application/json"
            and (not origin or origin in self.server.admin_origins)
        )

    @staticmethod
    def _bounded_minutes(query: dict[str, list[str]]) -> int:
        value = int(query.get("minutes", ["60"])[0])
        if not 1 <= value <= 1440:
            raise ValueError("minutes must be between 1 and 1440")
        return value

    def do_OPTIONS(self) -> None:
        origin = self._cors_origin(admin=urlsplit(self.path).path.startswith("/v1/admin/"))
        if not origin:
            self._json(403, {"error": "origin not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path, query = parsed.path.rstrip("/") or "/", parse_qs(parsed.query)
        try:
            if path == "/v1":
                self._json(200, {
                    "service": "knox-neighbor-api", "version": "1.0.0",
                    "openapi": "/openapi.json", "status": "/v1/status",
                    "independent_storage": True, "inverter_writes": False,
                })
            elif path == "/openapi.json":
                self._json(200, openapi_document(self.server.server_port))
            elif path == "/v1/status":
                self._json(200, self.coordinator.status())
            elif path == "/v1/systems":
                self._json(200, self.coordinator.systems())
            elif path in {"/v1/systems/primary/latest", "/v1/systems/neighbor/latest"}:
                self._json(200, self.coordinator.latest(path.split("/")[3]))
            elif path in {"/v1/systems/primary/history", "/v1/systems/neighbor/history"}:
                self._json(200, self.coordinator.history(path.split("/")[3], self._bounded_minutes(query)))
            elif path == "/v1/comparison":
                minutes = self._bounded_minutes(query)
                skew = int(query.get("max_skew_seconds", ["15"])[0])
                if not 1 <= skew <= 120:
                    raise ValueError("max_skew_seconds must be between 1 and 120")
                self._json(200, self.coordinator.comparison(minutes, skew))
            elif path == "/v1/alerts":
                self._json(200, self.coordinator.alerts())
            elif path == "/v1/alerts/events":
                limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
                self._json(200, {"events": self.coordinator.state_store.alert_events(limit)})
            elif path == "/v1/rules":
                self._json(200, {"rules": self.coordinator.alert_engine.rules()})
            elif path == "/v1/config":
                self._json(200, self.coordinator.config())
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "device not found"})
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:
        if not self._admin_allowed():
            self._json(403, {"error": "admin operations require a local client, approved Origin, and application/json"})
            return
        path = urlsplit(self.path).path.rstrip("/")
        try:
            data = self._body()
            if path == "/v1/admin/config":
                self._json(200, self.coordinator.update_config(data))
            elif path == "/v1/admin/probe":
                if data:
                    raise ValueError("probe uses the saved exact target and accepts no parameters")
                self._json(200, self.coordinator.probe())
            elif path == "/v1/admin/ingest":
                result = self.coordinator.ingest(data)
                self._json(200 if result["duplicate"] else 201, result)
            elif path == "/v1/admin/rules":
                self._json(200, {"rules": self.coordinator.update_rules(data.get("rules", data))})
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(409, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def create_peer_server(
    bind: str,
    port: int,
    primary_history: HistoryView,
    data_dir: str | Path,
    *,
    primary_status: Callable[[], dict[str, Any]] | None = None,
    dashboard_port: int = 8765,
    automatic_collection: bool = True,
) -> ThreadingHTTPServer:
    class ManagedPeerServer(ThreadingHTTPServer):
        def server_close(self) -> None:
            if getattr(self, "coordinator", None):
                self.coordinator.stop()
            super().server_close()

    server = ManagedPeerServer((bind, port), PeerApiHandler)
    server.coordinator = PeerCoordinator(
        primary_history,
        data_dir,
        primary_status=primary_status,
        automatic_collection=automatic_collection,
    )
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    read_hosts = set(loopback_hosts)
    if bind not in {"0.0.0.0", "::", ""}:
        read_hosts.add(bind.strip("[]"))
    else:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                candidate = info[4][0].split("%", 1)[0]
                try:
                    address = ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                if address.is_private or address.is_loopback:
                    read_hosts.add(str(address))
        except OSError:
            pass

    def origin(host: str) -> str:
        rendered = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{rendered}:{dashboard_port}"

    server.allowed_origins = {origin(host) for host in read_hosts}
    server.admin_origins = {origin(host) for host in loopback_hosts}
    server.dashboard_port = dashboard_port
    server.coordinator.start()
    return server
