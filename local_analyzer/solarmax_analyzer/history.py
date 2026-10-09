from __future__ import annotations

from collections import deque
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable
import zlib


SERIES = {
    "pv_power": {"label": "Solar / PV", "unit": "W", "color": "#59e39f"},
    "grid_power": {"label": "Grid", "unit": "W", "color": "#71b7ff"},
    "battery_power": {"label": "Battery", "unit": "W", "color": "#d698ff"},
    "backup_power": {"label": "Backup Load", "unit": "W", "color": "#ffcc66"},
    "gen_port_power": {"label": "GEN smart load", "unit": "W", "color": "#ff8a65"},
    "load_power": {"label": "Normal Load", "unit": "W", "color": "#9aa9a3"},
    "battery_soc": {"label": "Battery SOC", "unit": "%", "color": "#f5f25d"},
}


HA_SENSOR_KEYS = (
    "pv_power", "pv1_voltage", "pv1_current", "pv1_power",
    "pv2_voltage", "pv2_current", "pv2_power", "pv_peak_today",
    "today_energy", "total_energy", "generation_hours", "temperature",
    "inverter_mode", "grid_voltage", "grid_current", "grid_power",
    "grid_frequency", "grid_import_today", "grid_import_total",
    "grid_export_today", "grid_export_total", "load_voltage", "load_current",
    "load_power", "load_energy_today", "load_energy_total", "backup_voltage",
    "backup_current", "backup_power", "backup_frequency", "backup_energy_today",
    "backup_energy_total", "gen_port_voltage", "gen_port_current",
    "gen_port_power", "gen_port_frequency", "gen_port_energy_today",
    "gen_port_energy_total", "battery_voltage", "battery_current",
    "battery_power", "battery_soc", "battery_temperature",
    "battery_charge_today", "battery_charge_total", "battery_discharge_today",
    "battery_discharge_total",
)


def snapshot_point(snapshot: dict[str, Any]) -> dict[str, Any]:
    values = {
        key: snapshot.get("sensors", {}).get(key, {}).get("value")
        for key in SERIES
    }
    # Comparison-only values live beside the chart series.  Keeping them out of
    # SERIES prevents unlike W and Wh values from sharing the dashboard axis.
    values["today_energy"] = snapshot.get("sensors", {}).get("today_energy", {}).get("value")
    captured_at = snapshot.get("captured_at")
    timestamp_ms = None
    if captured_at:
        try:
            timestamp_ms = round(
                datetime.fromisoformat(captured_at.replace("Z", "+00:00")).timestamp() * 1000
            )
        except (TypeError, ValueError):
            pass
    return {
        "captured_at": captured_at,
        "received_at": snapshot.get("received_at"),
        "timestamp_ms": timestamp_ms,
        "device_id": snapshot.get("device_id"),
        "target_generation": snapshot.get("target_generation"),
        "neighbor_target": snapshot.get("neighbor_target"),
        "array": snapshot.get("array"),
        **values,
    }


def _parsed_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_order_key(snapshot: dict[str, Any]) -> tuple[datetime, datetime]:
    """Order samples by observation time, then trusted receipt time."""
    missing = datetime.min.replace(tzinfo=timezone.utc)
    return (
        _parsed_timestamp(snapshot.get("captured_at")) or missing,
        _parsed_timestamp(snapshot.get("received_at")) or missing,
    )


class TelemetryHistory:
    """Thread-safe cache with an optional durable SQLite telemetry journal."""

    def __init__(
        self,
        max_points: int = 9000,
        max_events: int = 10000,
        storage_path: str | Path | None = None,
    ):
        self._points: deque[dict[str, Any]] = deque(maxlen=max_points)
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._latest: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._storage_error: str | None = None
        self._saved_count = 0
        self._last_saved_at: str | None = None
        if self._storage_path is not None:
            self._initialize_storage(max_points=max_points, max_events=max_events)

    def _connect(self) -> sqlite3.Connection:
        assert self._storage_path is not None
        connection = sqlite3.connect(self._storage_path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _pack_snapshot(cls, snapshot: dict[str, Any]) -> bytes:
        return zlib.compress(cls._json(snapshot).encode("utf-8"), level=6)

    @staticmethod
    def _unpack_snapshot(payload: bytes) -> dict[str, Any]:
        return json.loads(zlib.decompress(payload).decode("utf-8"))

    def _initialize_storage(self, *, max_points: int, max_events: int) -> None:
        assert self._storage_path is not None
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at TEXT NOT NULL,
                        captured_at TEXT,
                        received_at TEXT,
                        timestamp_ms INTEGER,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        elapsed_ms REAL,
                        sensor_count INTEGER,
                        model TEXT,
                        point_json TEXT NOT NULL,
                        snapshot_zlib BLOB NOT NULL
                    )
                    """
                )
                sample_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(telemetry_samples)")
                }
                if "received_at" not in sample_columns:
                    connection.execute("ALTER TABLE telemetry_samples ADD COLUMN received_at TEXT")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS telemetry_samples_timestamp ON telemetry_samples(timestamp_ms)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS telemetry_samples_capture_source ON telemetry_samples(captured_at,source)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at TEXT NOT NULL,
                        captured_at TEXT,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        elapsed_ms REAL,
                        sensor_count INTEGER,
                        model TEXT,
                        values_json TEXT NOT NULL,
                        message TEXT,
                        details_json TEXT
                    )
                    """
                )
                self._saved_count = int(
                    connection.execute("SELECT COUNT(*) FROM telemetry_samples").fetchone()[0]
                )
                point_rows = connection.execute(
                    "SELECT point_json FROM telemetry_samples ORDER BY id DESC LIMIT ?",
                    (max_points,),
                ).fetchall()
                latest_row = connection.execute(
                    """
                    SELECT snapshot_zlib, recorded_at
                    FROM telemetry_samples
                    ORDER BY timestamp_ms IS NULL, timestamp_ms DESC,
                             received_at IS NULL, received_at DESC, id ASC
                    LIMIT 1
                    """
                ).fetchone()
                event_rows = connection.execute(
                    """
                    SELECT recorded_at,captured_at,source,status,elapsed_ms,sensor_count,
                           model,values_json,message,details_json
                    FROM telemetry_events ORDER BY id DESC LIMIT ?
                    """,
                    (max_events,),
                ).fetchall()
            self._points.extend(
                json.loads(row[0]) for row in reversed(point_rows)
            )
            if latest_row:
                self._latest = self._unpack_snapshot(latest_row[0])
                self._last_saved_at = latest_row[1]
            for row in reversed(event_rows):
                event = {
                    "recorded_at": row[0],
                    "captured_at": row[1],
                    "source": row[2],
                    "status": row[3],
                    "elapsed_ms": row[4],
                    "sensor_count": row[5],
                    "model": row[6],
                    "values": json.loads(row[7]),
                }
                if row[8] is not None:
                    event["message"] = row[8]
                if row[9] is not None:
                    event["details"] = json.loads(row[9])
                self._events.append(event)
        except (OSError, sqlite3.Error, ValueError, zlib.error) as exc:
            self._storage_error = f"{type(exc).__name__}: {exc}"

    def _persist_sample(
        self,
        snapshot: dict[str, Any],
        point: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        if self._storage_path is None:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO telemetry_samples (
                        recorded_at,captured_at,received_at,timestamp_ms,source,status,elapsed_ms,
                        sensor_count,model,point_json,snapshot_zlib
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event["recorded_at"],
                        event["captured_at"],
                        snapshot.get("received_at"),
                        point.get("timestamp_ms"),
                        event["source"],
                        event["status"],
                        event["elapsed_ms"],
                        event["sensor_count"],
                        event["model"],
                        self._json(point),
                        sqlite3.Binary(self._pack_snapshot(snapshot)),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO telemetry_events (
                        recorded_at,captured_at,source,status,elapsed_ms,sensor_count,
                        model,values_json,message,details_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event["recorded_at"], event["captured_at"], event["source"],
                        event["status"], event["elapsed_ms"], event["sensor_count"],
                        event["model"], self._json(event["values"]), None, None,
                    ),
                )
            self._saved_count += 1
            self._last_saved_at = event["recorded_at"]
            self._storage_error = None
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self._storage_error = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(f"telemetry storage failed: {exc}") from exc

    @staticmethod
    def _point_identity(point: dict[str, Any]) -> tuple[Any, ...]:
        target = point.get("neighbor_target")
        target_identity = (
            (target.get("host"), target.get("port"), target.get("unit_id"))
            if isinstance(target, dict)
            else None
        )
        return (
            point.get("captured_at"),
            point.get("device_id"),
            point.get("target_generation"),
            target_identity,
        )

    def _stored_duplicate(
        self,
        point: dict[str, Any],
        source: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        identity = self._point_identity(point)
        if self._storage_path is not None:
            try:
                with closing(self._connect()) as connection:
                    rows = connection.execute(
                        """
                        SELECT point_json,snapshot_zlib
                        FROM telemetry_samples
                        WHERE captured_at=? AND source=?
                        ORDER BY id
                        """,
                        (point.get("captured_at"), source),
                    ).fetchall()
                for row in rows:
                    stored_point = json.loads(row[0])
                    if self._point_identity(stored_point) == identity:
                        return stored_point, self._unpack_snapshot(row[1])
            except (sqlite3.Error, ValueError, zlib.error) as exc:
                self._storage_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(f"telemetry duplicate check failed: {exc}") from exc
        for stored_point in reversed(self._points):
            if self._point_identity(stored_point) == identity:
                original = (
                    self._latest
                    if self._latest is not None
                    and self._point_identity(snapshot_point(self._latest)) == identity
                    else None
                )
                return dict(stored_point), original or {}
        return None

    def _persist_event(self, event: dict[str, Any]) -> None:
        if self._storage_path is None:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO telemetry_events (
                        recorded_at,captured_at,source,status,elapsed_ms,sensor_count,
                        model,values_json,message,details_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event["recorded_at"], event["captured_at"], event["source"],
                        event["status"], event["elapsed_ms"], event["sensor_count"],
                        event["model"], self._json(event["values"]), event.get("message"),
                        self._json(event["details"]) if event.get("details") is not None else None,
                    ),
                )
            self._storage_error = None
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self._storage_error = f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _sample_event(snapshot: dict[str, Any], source: str) -> dict[str, Any]:
        point = snapshot_point(snapshot)
        sensors = snapshot.get("sensors", {})
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "captured_at": snapshot.get("captured_at"),
            "source": source,
            "status": "success" if snapshot.get("ok") else "partial",
            "elapsed_ms": snapshot.get("elapsed_ms"),
            "sensor_count": snapshot.get("sensor_count", len(sensors)),
            "model": snapshot.get("model"),
            "values": {
                key: sensors.get(key, {}).get("value")
                for key in (
                    "pv_power", "grid_power", "battery_power", "battery_soc",
                    "backup_power", "gen_port_power", "load_power",
                )
            },
        }

    def _record_locked(
        self,
        snapshot: dict[str, Any],
        point: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        self._persist_sample(snapshot, point, event)
        self._points.append(point)
        if self._latest is None or _snapshot_order_key(snapshot) > _snapshot_order_key(self._latest):
            self._latest = snapshot
        self._events.append(event)

    def record(self, snapshot: dict[str, Any], source: str = "unknown") -> dict[str, Any]:
        point = snapshot_point(snapshot)
        event = self._sample_event(snapshot, source)
        with self._lock:
            self._record_locked(snapshot, point, event)
        return point

    def record_once(
        self,
        snapshot: dict[str, Any],
        source: str = "unknown",
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        """Record a capture once; a same-capture retry returns the first row."""
        point = snapshot_point(snapshot)
        event = self._sample_event(snapshot, source)
        with self._lock:
            duplicate = self._stored_duplicate(point, source)
            if duplicate is not None:
                stored_point, stored_snapshot = duplicate
                return stored_point, True, stored_snapshot or snapshot
            self._record_locked(snapshot, point, event)
        return point, False, snapshot

    def record_error(
        self,
        source: str,
        error: Exception | str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "captured_at": None,
            "source": source,
            "status": "error",
            "elapsed_ms": None,
            "sensor_count": 0,
            "model": None,
            "values": {},
            "message": f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error),
        }
        if details:
            event["details"] = dict(details)
        with self._lock:
            self._persist_event(event)
            self._events.append(event)
        return dict(event)

    def storage_status(self) -> dict[str, Any]:
        with self._lock:
            points = len(self._points)
            events = len(self._events)
            return {
                "persistent": self._storage_path is not None,
                "path": str(self._storage_path) if self._storage_path is not None else None,
                "saved_samples": self._saved_count if self._storage_path is not None else points,
                "cached_points": points,
                "cached_events": events,
                "last_saved_at": self._last_saved_at,
                "error": self._storage_error,
            }

    def activity(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)[-limit:]
        return [dict(event) for event in reversed(events)]

    def query(self, minutes: int = 60) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        cutoff_ms = cutoff.timestamp() * 1000
        with self._lock:
            return [dict(point) for point in self._points if (point.get("timestamp_ms") or 0) >= cutoff_ms]

    def latest_snapshot(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if predicate is None or (self._latest is not None and predicate(self._latest)):
                return self._latest
            if self._storage_path is None:
                return None
            try:
                with closing(self._connect()) as connection:
                    rows = connection.execute(
                        """
                        SELECT snapshot_zlib
                        FROM telemetry_samples
                        ORDER BY timestamp_ms IS NULL, timestamp_ms DESC,
                                 received_at IS NULL, received_at DESC, id ASC
                        """
                    )
                    for row in rows:
                        snapshot = self._unpack_snapshot(row[0])
                        if predicate(snapshot):
                            return snapshot
            except (sqlite3.Error, ValueError, zlib.error) as exc:
                self._storage_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(f"telemetry latest-sample lookup failed: {exc}") from exc
            return None

    def home_assistant_payload(self, max_age_seconds: int = 180) -> dict[str, Any] | None:
        snapshot = self.latest_snapshot()
        if snapshot is None:
            return None
        captured_at = snapshot.get("captured_at")
        age_seconds = None
        if captured_at:
            try:
                captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
                age_seconds = round((datetime.now(timezone.utc) - captured).total_seconds(), 1)
            except (TypeError, ValueError):
                pass
        sensors = {}
        for key in HA_SENSOR_KEYS:
            sensor = snapshot.get("sensors", {}).get(key)
            if not sensor:
                continue
            sensors[key] = {
                "name": sensor.get("name"),
                "value": sensor.get("value"),
                "unit": sensor.get("unit"),
                "category": sensor.get("category"),
                "label": sensor.get("label"),
                "active_flags": sensor.get("active_flags"),
            }
        return {
            "available": bool(snapshot.get("ok")) and (
                age_seconds is not None and age_seconds <= max_age_seconds
            ),
            "captured_at": captured_at,
            "age_seconds": age_seconds,
            "model": snapshot.get("model"),
            "phase_count": snapshot.get("phase_count"),
            "mppt_count": snapshot.get("mppt_count"),
            "sensors": sensors,
        }
