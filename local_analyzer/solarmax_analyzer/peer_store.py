from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .discovery import DEFAULT_HOST
from .peer import DEFAULT_NEIGHBOR_SYSTEM, SystemSpec


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_CONFIG: dict[str, Any] = {
    "id": "neighbor",
    "name": DEFAULT_NEIGHBOR_SYSTEM.name,
    "manufacturer": DEFAULT_NEIGHBOR_SYSTEM.manufacturer,
    "model": DEFAULT_NEIGHBOR_SYSTEM.model,
    "host": None,
    "port": 502,
    "unit_id": 1,
    "transport": "eybond_callback",
    "udp_port": 58899,
    "callback_port": 8899,
    "callback_host": None,
    "collection_mode": "local",
    "collector_pn": None,
    "cloud_endpoint": None,
    "target_generation": 0,
    "driver": "unverified",
    "protocol_status": "awaiting_exact_ip_and_fingerprint",
    "panel_count": DEFAULT_NEIGHBOR_SYSTEM.panel_count,
    "panel_watts": DEFAULT_NEIGHBOR_SYSTEM.panel_watts,
    "inverter_ac_watts": DEFAULT_NEIGHBOR_SYSTEM.inverter_ac_watts,
    "expected_interval_seconds": 180,
    "last_probe": None,
    "updated_at": None,
}


class PeerStateStore:
    """Durable configuration and alert journal, isolated from both telemetry DBs."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS peer_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_states (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    pending_since REAL,
                    recovering_since REAL,
                    opened_at TEXT,
                    resolved_at TEXT,
                    updated_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS alert_events_time ON alert_events(occurred_at DESC)"
            )
            connection.execute("PRAGMA optimize")

    @staticmethod
    def _config_from_connection(connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute("SELECT payload_json FROM peer_config WHERE id=1").fetchone()
        saved = json.loads(row[0]) if row else {}
        return {**DEFAULT_CONFIG, **saved}

    @staticmethod
    def target_tuple(config: dict[str, Any]) -> tuple[str | None, int, int]:
        return (
            config.get("host"),
            int(config.get("port", DEFAULT_CONFIG["port"])),
            int(config.get("unit_id", DEFAULT_CONFIG["unit_id"])),
        )

    @classmethod
    def target(cls, config: dict[str, Any]) -> dict[str, Any]:
        host, port, unit_id = cls.target_tuple(config)
        return {"host": host, "port": port, "unit_id": unit_id}

    def config(self) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            return self._config_from_connection(connection)

    @staticmethod
    def _validated_config(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("configuration must be a JSON object")
        allowed = {
            "name", "model", "host", "port", "unit_id", "panel_count",
            "panel_watts", "inverter_ac_watts", "expected_interval_seconds",
            "udp_port", "callback_port", "callback_host",
            "collection_mode",
        }
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"unsupported configuration field(s): {', '.join(sorted(unknown))}")
        result = {**current}
        if "name" in patch:
            name = str(patch["name"]).strip()
            if not 1 <= len(name) <= 80:
                raise ValueError("name must contain 1-80 characters")
            result["name"] = name
        if "model" in patch:
            model = str(patch["model"]).strip()
            if not 1 <= len(model) <= 120:
                raise ValueError("model must contain 1-120 characters")
            result["model"] = model
        if "host" in patch:
            raw_host = patch["host"]
            if raw_host is None or not str(raw_host).strip():
                result["host"] = None
            else:
                address = ipaddress.ip_address(str(raw_host).strip())
                if (
                    address.version != 4
                    or not address.is_private
                    or address.is_loopback
                    or address.is_multicast
                    or address.is_unspecified
                    or address.is_reserved
                ):
                    raise ValueError("neighbor host must be a private, unicast IPv4 address")
                if str(address) == DEFAULT_HOST:
                    raise ValueError("neighbor host must not be the SolarMax host")
                result["host"] = str(address)
        if "callback_host" in patch:
            raw_callback_host = patch["callback_host"]
            if raw_callback_host is None or not str(raw_callback_host).strip():
                result["callback_host"] = None
            else:
                callback_address = ipaddress.ip_address(str(raw_callback_host).strip())
                if (
                    callback_address.version != 4
                    or not callback_address.is_private
                    or callback_address.is_loopback
                    or callback_address.is_multicast
                    or callback_address.is_unspecified
                    or callback_address.is_reserved
                ):
                    raise ValueError("callback_host must be a private, unicast LAN IPv4 address")
                result["callback_host"] = str(callback_address)
        if "collection_mode" in patch:
            collection_mode = str(patch["collection_mode"]).strip().lower()
            if collection_mode not in {"local", "original"}:
                raise ValueError("collection_mode must be local or original")
            result["collection_mode"] = collection_mode
        integer_ranges = {
            "port": (1, 65535),
            "unit_id": (1, 247),
            "panel_count": (1, 100),
            "expected_interval_seconds": (10, 900),
            "udp_port": (1, 65535),
            "callback_port": (1, 65535),
        }
        for key, (minimum, maximum) in integer_ranges.items():
            if key in patch:
                value = patch[key]
                if isinstance(value, bool) or int(value) != float(value):
                    raise ValueError(f"{key} must be an integer")
                value = int(value)
                if not minimum <= value <= maximum:
                    raise ValueError(f"{key} must be between {minimum} and {maximum}")
                result[key] = value
        for key, bounds in {"panel_watts": (50, 1000), "inverter_ac_watts": (100, 100000)}.items():
            if key in patch:
                if isinstance(patch[key], bool):
                    raise ValueError(f"{key} must be numeric")
                value = float(patch[key])
                if not bounds[0] <= value <= bounds[1]:
                    raise ValueError(f"{key} must be between {bounds[0]} and {bounds[1]}")
                result[key] = value
        result["updated_at"] = utc_now()
        # Saving an endpoint is not protocol proof. Every target identity change
        # advances the durable generation and invalidates all prior evidence.
        if PeerStateStore.target_tuple(result) != PeerStateStore.target_tuple(current):
            result["target_generation"] = int(current.get("target_generation", 0)) + 1
            result["driver"] = "unverified"
            result["protocol_status"] = "awaiting_read_only_fingerprint"
            result["last_probe"] = None
        return result

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._config_from_connection(connection)
                result = self._validated_config(current, patch)
                connection.execute(
                    "INSERT OR REPLACE INTO peer_config(id,payload_json,updated_at) VALUES(1,?,?)",
                    (self._json(result), result["updated_at"]),
                )
                if self.target_tuple(result) != self.target_tuple(current):
                    self._reset_neighbor_alert_states(connection, current, result)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def _reset_neighbor_alert_states(
        self,
        connection: sqlite3.Connection,
        previous_config: dict[str, Any],
        current_config: dict[str, Any],
    ) -> None:
        """End every neighbor alert lifecycle at the target-generation boundary."""
        rows = connection.execute(
            "SELECT id,state,opened_at FROM alert_states WHERE device_id='neighbor'"
        ).fetchall()
        for row in rows:
            details = {
                "reason": "neighbor_target_changed",
                "previous_state": row["state"],
                "previous_opened_at": row["opened_at"],
                "previous_target": self.target(previous_config),
                "previous_target_generation": int(
                    previous_config.get("target_generation", 0)
                ),
                "current_target": self.target(current_config),
                "current_target_generation": int(current_config["target_generation"]),
            }
            connection.execute(
                """
                INSERT INTO alert_events(
                    alert_id,state,occurred_at,message,severity,device_id,details_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    row["id"], "target_changed", current_config["updated_at"],
                    "Neighbor target changed; the prior alert lifecycle was reset.",
                    "info", "neighbor", self._json(details),
                ),
            )
        connection.execute("DELETE FROM alert_states WHERE device_id='neighbor'")

    def save_probe(
        self,
        evidence: dict[str, Any],
        *,
        expected_target: tuple[str | None, int, int],
        expected_generation: int,
    ) -> dict[str, Any] | None:
        """Save probe evidence only while its complete target identity is current."""
        evidence_target = (
            evidence.get("host"),
            int(evidence.get("port", DEFAULT_CONFIG["port"])),
            int(evidence.get("unit_id", DEFAULT_CONFIG["unit_id"])),
        )
        if (
            evidence_target != expected_target
            or int(evidence.get("target_generation", -1)) != expected_generation
        ):
            raise ValueError("probe evidence does not match its expected target generation")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                config = self._config_from_connection(connection)
                if (
                    self.target_tuple(config) != expected_target
                    or int(config.get("target_generation", 0)) != expected_generation
                ):
                    connection.rollback()
                    return None
                config["last_probe"] = evidence
                callback = evidence.get("callback")
                callback_ok = isinstance(callback, dict) and bool(callback.get("ok"))
                protocol_id = str(
                    callback.get("inverter", {}).get("protocol_id", "")
                    if callback_ok else ""
                ).upper()
                if callback_ok:
                    config["collector_pn"] = callback.get("collector_pn") or None
                    metadata = callback.get("metadata")
                    if isinstance(metadata, dict):
                        config["cloud_endpoint"] = metadata.get("cloud_endpoint") or None
                    if protocol_id == "PI18" and callback.get("inverter", {}).get("telemetry"):
                        config["protocol_status"] = "verified"
                        config["driver"] = "knox_eybond_pi18"
                    else:
                        config["protocol_status"] = "eybond_callback_seen_decoder_unverified"
                else:
                    config["protocol_status"] = (
                        "modbus_transport_seen_decoder_unverified"
                        if evidence.get("tcp", {}).get("ok")
                        else "transport_not_reached"
                    )
                config["updated_at"] = utc_now()
                connection.execute(
                    "INSERT OR REPLACE INTO peer_config(id,payload_json,updated_at) VALUES(1,?,?)",
                    (self._json(config), config["updated_at"]),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return config

    @staticmethod
    def system_from_config(config: dict[str, Any]) -> SystemSpec:
        return SystemSpec(
            id="neighbor",
            name=str(config["name"]),
            manufacturer="Knox",
            model=str(config["model"]),
            panel_count=int(config["panel_count"]),
            panel_watts=float(config["panel_watts"]),
            inverter_ac_watts=float(config["inverter_ac_watts"]),
        )

    def rule(self, rule_id: str, default: dict[str, Any]) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM alert_rules WHERE id=?", (rule_id,)
            ).fetchone()
        return {**default, **(json.loads(row[0]) if row else {})}

    def save_rule(self, rule_id: str, payload: dict[str, Any]) -> None:
        self.save_rules({rule_id: payload})

    def save_rules(self, rules: dict[str, dict[str, Any]]) -> None:
        """Persist one validated rule patch as an all-or-nothing transaction."""
        if not rules:
            return
        updated_at = utc_now()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT OR REPLACE INTO alert_rules(id,payload_json,updated_at) VALUES(?,?,?)",
                (
                    (rule_id, self._json(payload), updated_at)
                    for rule_id, payload in rules.items()
                ),
            )

    def state(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM alert_states WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json"))
        return result

    def save_alert_state(self, state: dict[str, Any], *, emit_event: bool) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO alert_states(
                    id,state,pending_since,recovering_since,opened_at,resolved_at,
                    updated_at,message,severity,device_id,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    state["id"], state["state"], state.get("pending_since"),
                    state.get("recovering_since"), state.get("opened_at"),
                    state.get("resolved_at"), state["updated_at"], state["message"],
                    state["severity"], state["device_id"], self._json(state.get("details", {})),
                ),
            )
            if emit_event:
                connection.execute(
                    """
                    INSERT INTO alert_events(
                        alert_id,state,occurred_at,message,severity,device_id,details_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        state["id"], state["state"], state["updated_at"], state["message"],
                        state["severity"], state["device_id"], self._json(state.get("details", {})),
                    ),
                )

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM alert_states ORDER BY CASE state WHEN 'firing' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, updated_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

    def alert_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM alert_events ORDER BY sequence DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result
