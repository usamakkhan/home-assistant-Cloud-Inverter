from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
import uuid
import webbrowser

from solarmax_analyzer import __version__
from solarmax_analyzer.comparison import cloud_field_schema, compare_snapshot
from solarmax_analyzer.collector import CollectorController, CollectorUnavailable
from solarmax_analyzer.discovery import (
    DEFAULT_HOST,
    PRESETS,
    check_tcp,
    scan_addresses,
    validate_host,
)
from solarmax_analyzer.modbus import ModbusClient
from solarmax_analyzer.features import feature_inventory
from solarmax_analyzer.controls import ControlService, catalog as control_catalog
from solarmax_analyzer.history import SERIES, TelemetryHistory
from solarmax_analyzer.peer_api import create_peer_server
from solarmax_analyzer.profile import SPECS, read_device_and_safe_settings, read_profile_snapshot
from solarmax_analyzer.security import run_security_audit


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DASHBOARD_ASSETS = {
    "/assets/portal.css": ("portal.css", "text/css; charset=utf-8"),
    "/assets/dashboard-v2.css": ("dashboard-v2.css", "text/css; charset=utf-8"),
    "/assets/dashboard-ui.js": ("dashboard-ui.js", "application/javascript; charset=utf-8"),
    "/assets/peer-dashboard.css": ("peer-dashboard.css", "text/css; charset=utf-8"),
    "/assets/peer-dashboard.js": ("peer-dashboard.js", "application/javascript; charset=utf-8"),
    "/assets/home-energy-v1.png": ("assets/home-energy-v1.png", "image/png"),
    "/assets/inverter-kit-v1.png": ("assets/inverter-kit-v1.png", "image/png"),
    "/assets/cloud-inverter-icon.png": ("assets/cloud-inverter-icon.png", "image/png"),
}
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
TELEMETRY_HISTORY = TelemetryHistory()
DEVICE_IO_LOCK = threading.Lock()
PROFILE_METADATA_CACHE: dict[str, dict] = {}


def validate_listener_ports(port: int, peer_port: int, *, peer_enabled: bool = True) -> None:
    """Reject invalid or colliding listeners before either service starts."""
    for label, value in (("dashboard", port), ("comparison API", peer_port)):
        if not 1 <= value <= 65535:
            raise ValueError(f"{label} port must be between 1 and 65535")
    if peer_enabled and port == peer_port:
        raise ValueError("dashboard and comparison API ports must be different")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "thread"}


def capture_profile(host: str, unit_id: int) -> dict:
    """Serialize full-device reads so the ESP bridge is never polled concurrently."""
    with DEVICE_IO_LOCK:
        return read_profile_snapshot(host, unit_id, metadata_cache=PROFILE_METADATA_CACHE)


def collector_payload(collector: CollectorController) -> dict:
    state = collector.status()
    state["storage"] = TELEMETRY_HISTORY.storage_status()
    return state


class Handler(BaseHTTPRequestHandler):
    server_version = "SolarMaxAnalyzer/" + __version__

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 100_000:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        return json.loads(raw or b"{}")

    @property
    def collector(self) -> CollectorController:
        return self.server.collector

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in DASHBOARD_ASSETS:
            relative_path, content_type = DASHBOARD_ASSETS[path]
            asset = STATIC / relative_path
            if not asset.is_file():
                self._json(404, {"error": "asset not found"})
                return
            content = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/":
            content = (STATIC / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/api/config":
            collector = collector_payload(self.collector)
            self._json(200, {
                "version": __version__,
                "default_host": DEFAULT_HOST,
                "presets": {
                    key: {"label": item.label, "count": len(item.addresses)}
                    for key, item in PRESETS.items()
                },
                "read_only": not bool(getattr(self.server, "controls", None) and self.server.controls.enabled),
                "documented_sensor_count": len(SPECS),
                "security_audit": "non-invasive",
                "cloud_comparison_fields": cloud_field_schema(),
                "recommended_live_interval_seconds": collector["interval_seconds"],
                "background_monitor_interval_seconds": (
                    collector["interval_seconds"] if collector["background_polling"] else 0
                ),
                "collector": collector,
                "peer_api": {
                    "enabled": bool(getattr(self.server, "peer_api_enabled", False)),
                    "port": int(getattr(self.server, "peer_api_port", 8767)),
                    "root": "/v1",
                    "separate_listener": True,
                },
            })
            return
        if path == "/api/collector":
            self._json(200, collector_payload(self.collector))
            return
        if path == "/api/features":
            self._json(200, {
                "read_only": True,
                "write_controls_enabled": bool(getattr(self.server, "controls", None) and self.server.controls.enabled),
                "control_endpoint": "/api/controls",
                "features": feature_inventory(),
            })
            return
        if path == "/api/controls":
            service = getattr(self.server, "controls", None)
            self._json(200, {
                "enabled": bool(service and service.enabled),
                "session": service.session_status() if service else {},
                "fields": control_catalog(enabled=bool(service and service.enabled)),
                "audit": list(service.audit) if service else [],
            })
            return
        if path == "/api/history":
            try:
                minutes = max(1, min(1440, int(query.get("minutes", ["60"])[0])))
            except (TypeError, ValueError):
                self._json(400, {"error": "minutes must be an integer between 1 and 1440"})
                return
            points = TELEMETRY_HISTORY.query(minutes)
            self._json(200, {
                "minutes": minutes,
                "count": len(points),
                "series": SERIES,
                "points": points,
                "storage": TELEMETRY_HISTORY.storage_status(),
            })
            return
        if path == "/api/activity":
            try:
                limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
            except (TypeError, ValueError):
                self._json(400, {"error": "limit must be an integer between 1 and 500"})
                return
            events = TELEMETRY_HISTORY.activity(limit)
            self._json(200, {"count": len(events), "events": events})
            return
        if path == "/api/ha":
            collector_status = self.server.collector.status()
            # Allow a skipped cooperative cloud window and one missed target
            # without hiding valid telemetry immediately.
            max_age = (
                max(180, 2 * collector_status["interval_seconds"] + 90)
                if collector_status["background_polling"] else 180
            )
            payload = TELEMETRY_HISTORY.home_assistant_payload(max_age_seconds=max_age)
            if payload is None:
                self._json(503, {"available": False, "error": "no telemetry captured yet"})
            else:
                self._json(200, payload)
            return
        if path == "/api/latest":
            snapshot = TELEMETRY_HISTORY.latest_snapshot()
            if snapshot is None:
                self._json(503, {"error": "no telemetry captured yet"})
            else:
                self._json(200, {
                    "snapshot": snapshot,
                    "comparison": compare_snapshot(snapshot, {}),
                })
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = public_job(job) if job else None
            if payload is None:
                self._json(404, {"error": "job not found"})
            else:
                self._json(200, payload)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            data = self._body()
            if self.path.startswith("/api/controls/"):
                # Controls are local-browser only, even when HA cache is LAN-served.
                port = self.server.server_port
                allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
                host = self.headers.get("Host", "")
                if self.client_address[0] not in {"127.0.0.1", "::1"} or host not in allowed_hosts or self.headers.get("Origin") != f"http://{host}" or self.headers.get_content_type() != "application/json":
                    self._json(403, {"error": "Controls require a same-origin local browser and application/json"})
                    return
                service = self.server.controls
                if self.path == "/api/controls/read":
                    self._json(200, service.read())
                elif self.path == "/api/controls/session":
                    action = str(data.get("action", "")).strip().lower()
                    if action == "start":
                        result = service.begin_session(data.get("confirmation"))
                    elif action == "end":
                        result = service.end_session()
                    else:
                        raise ValueError("Control session action must be start or end")
                    result["collector"] = collector_payload(self.collector)
                    self._json(200, result)
                elif self.path == "/api/controls/prepare":
                    self._json(200, service.prepare(data.get("key"), data.get("value")))
                elif self.path == "/api/controls/apply":
                    self._json(200, service.apply(data.get("token"), data.get("confirmation")))
                else:
                    self._json(404, {"error": "Unknown control endpoint"})
                return
            if self.path == "/api/collector/mode":
                self.collector.set_mode(
                    str(data.get("mode", "original")),
                    interval_seconds=data.get("interval_seconds"),
                    quiet_window_seconds=data.get("quiet_window_seconds"),
                    confirmed=data.get("confirmed") is True,
                )
                self._json(200, collector_payload(self.collector))
                return
            if self.path == "/api/collector/capture":
                snapshot = self.collector.capture_now(source="manual_live")
                comparison = compare_snapshot(
                    snapshot,
                    data.get("cloud_reference") if isinstance(data.get("cloud_reference"), dict) else {},
                    str(data.get("cloud_captured_at")) if data.get("cloud_captured_at") else None,
                )
                self._json(200, {
                    "snapshot": snapshot,
                    "comparison": comparison,
                    "history_point": TELEMETRY_HISTORY.query(1440)[-1],
                    "collector": collector_payload(self.collector),
                })
                return
            if self.path == "/api/check":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                self._json(200, check_tcp(host))
                return
            if self.path == "/api/read":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                address = int(data.get("address", 0))
                count = int(data.get("count", 1))
                unit_id = int(data.get("unit_id", 1))
                with DEVICE_IO_LOCK:
                    result = ModbusClient(host).read_holding_registers(
                        address, count, unit_id
                    )
                self._json(200, result.to_dict())
                return
            if self.path == "/api/snapshot":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                unit_id = int(data.get("unit_id", 1))
                snapshot = capture_profile(host, unit_id)
                snapshot["history_point"] = TELEMETRY_HISTORY.record(snapshot, source="manual_snapshot")
                self._json(200, snapshot)
                return
            if self.path == "/api/compare":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                unit_id = int(data.get("unit_id", 1))
                snapshot = capture_profile(host, unit_id)
                comparison = compare_snapshot(
                    snapshot,
                    data.get("cloud_reference") if isinstance(data.get("cloud_reference"), dict) else {},
                    str(data.get("cloud_captured_at")) if data.get("cloud_captured_at") else None,
                )
                history_point = TELEMETRY_HISTORY.record(snapshot, source="manual_compare")
                self._json(200, {
                    "snapshot": snapshot,
                    "comparison": comparison,
                    "history_point": history_point,
                })
                return
            if self.path == "/api/device":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                unit_id = int(data.get("unit_id", 1))
                with DEVICE_IO_LOCK:
                    device = read_device_and_safe_settings(host, unit_id)
                device["feature_inventory"] = feature_inventory(device.get("info"))
                self._json(200, device)
                return
            if self.path == "/api/security":
                self.collector.ensure_maintenance()
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                unit_id = int(data.get("unit_id", 1))
                with DEVICE_IO_LOCK:
                    audit = run_security_audit(host, unit_id)
                self._json(200, audit)
                return
            if self.path == "/api/scan":
                self.collector.ensure_maintenance()
                preset_name = str(data.get("preset", "vendor"))
                if preset_name not in PRESETS:
                    raise ValueError("unknown scan preset")
                host = validate_host(str(data.get("host", DEFAULT_HOST)))
                unit_id = int(data.get("unit_id", 1))
                if not 0 <= unit_id <= 255:
                    raise ValueError("unit_id must be between 0 and 255")
                self._start_scan(host, unit_id, preset_name)
                return
            self._json(404, {"error": "not found"})
        except CollectorUnavailable as exc:
            self._json(409, {"error": str(exc), "collector": self.collector.status()})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            source = {
                "/api/snapshot": "manual_snapshot",
                "/api/compare": "manual_compare",
            }.get(self.path)
            if source:
                TELEMETRY_HISTORY.record_error(source, exc)
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _start_scan(self, host: str, unit_id: int, preset_name: str) -> None:
        job_id = uuid.uuid4().hex
        preset = PRESETS[preset_name]
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "host": host,
            "unit_id": unit_id,
            "preset": preset_name,
            "preset_label": preset.label,
            "current": 0,
            "total": len(preset.addresses),
            "result": None,
            "error": None,
        }

        def update(current: int, total: int) -> None:
            with JOBS_LOCK:
                job["current"] = current
                job["total"] = total
                job["updated_at"] = utc_now()

        def run() -> None:
            with JOBS_LOCK:
                job["status"] = "running"
                job["updated_at"] = utc_now()
            try:
                with DEVICE_IO_LOCK:
                    result = scan_addresses(
                        host,
                        preset.addresses,
                        unit_id=unit_id,
                        timeout=1.5,
                        interval=1.0,
                        progress=update,
                    )
                with JOBS_LOCK:
                    job["result"] = result
                    job["status"] = "complete"
                    job["updated_at"] = utc_now()
            except Exception as exc:
                with JOBS_LOCK:
                    job["error"] = f"{type(exc).__name__}: {exc}"
                    job["status"] = "failed"
                    job["updated_at"] = utc_now()

        thread = threading.Thread(target=run, name=f"scan-{job_id}", daemon=True)
        job["thread"] = thread
        with JOBS_LOCK:
            JOBS[job_id] = job
        thread.start()
        self._json(202, public_job(job))


def main() -> None:
    parser = argparse.ArgumentParser(description="SolarMax PV9000 local portal; inverter controls disabled by default")
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open the local UI automatically"
    )
    parser.add_argument("--bind", default=BIND_HOST, help="HTTP bind address")
    parser.add_argument("--port", type=int, default=BIND_PORT, help="HTTP port")
    parser.add_argument("--enable-inverter-controls", action="store_true", help="opt in to reviewed work-mode/grid-charge uploads from a local browser; Maintenance mode still required")
    parser.add_argument(
        "--monitor-interval",
        type=int,
        default=0,
        help="start background collection at this target interval; 0 starts cloud-only, minimum 10",
    )
    parser.add_argument(
        "--monitor-mode",
        choices=("local", "cooperative"),
        default="cooperative",
        help="background mode used with --monitor-interval (default: cooperative)",
    )
    parser.add_argument("--monitor-host", default=DEFAULT_HOST, help="inverter IP for background monitoring")
    parser.add_argument("--monitor-unit", type=int, default=1, help="Modbus unit for background monitoring")
    parser.add_argument("--peer-api-port", type=int, default=8767, help="independent Knox comparison API port")
    parser.add_argument("--no-peer-api", action="store_true", help="do not start the independent Knox API")
    parser.add_argument(
        "--cloud-quiet-window",
        type=int,
        default=45,
        help="seconds reserved before/after each five-minute cloud boundary (30-90)",
    )
    args = parser.parse_args()
    if args.monitor_interval and args.monitor_interval < 10:
        parser.error("--monitor-interval must be 0 or at least 10 seconds")
    try:
        validate_listener_ports(args.port, args.peer_api_port, peer_enabled=not args.no_peer_api)
    except ValueError as exc:
        parser.error(str(exc))
    monitor_host = validate_host(args.monitor_host)
    if not 0 <= args.monitor_unit <= 255:
        parser.error("--monitor-unit must be between 0 and 255")
    global TELEMETRY_HISTORY
    TELEMETRY_HISTORY = TelemetryHistory(storage_path=ROOT / "data" / "telemetry.sqlite3")
    try:
        server = ThreadingHTTPServer((args.bind, args.port), Handler)
    except OSError as exc:
        parser.error(f"cannot start dashboard on {args.bind}:{args.port}: {exc}")
    collector = CollectorController(
        capture_profile,
        TELEMETRY_HISTORY.record,
        TELEMETRY_HISTORY.record_error,
        monitor_host,
        args.monitor_unit,
        interval_seconds=args.monitor_interval or 180,
        quiet_window_seconds=args.cloud_quiet_window,
    )
    server.collector = collector
    server.controls = ControlService(collector, DEVICE_IO_LOCK, enabled=args.enable_inverter_controls)
    server.peer_api_enabled = not args.no_peer_api
    server.peer_api_port = args.peer_api_port
    peer_server = None
    peer_thread = None
    if not args.no_peer_api:
        try:
            peer_server = create_peer_server(
                args.bind,
                args.peer_api_port,
                TELEMETRY_HISTORY,
                ROOT / "data",
                primary_status=collector.status,
                dashboard_port=args.port,
            )
        except OSError as exc:
            server.server_close()
            parser.error(
                f"cannot start comparison API on {args.bind}:{args.peer_api_port}: {exc}"
            )
        peer_thread = threading.Thread(
            target=peer_server.serve_forever,
            name="knox-neighbor-api",
            daemon=True,
        )
        peer_thread.start()
    collector.start()
    browser_host = "127.0.0.1" if args.bind in {"0.0.0.0", "::"} else args.bind
    url = f"http://{browser_host}:{args.port}"
    print(f"SolarMax PV9000 Analyzer {__version__}")
    print(f"Local web interface: {url}")
    print(f"Physical inverter controls: {'opted in; review required' if args.enable_inverter_controls else 'disabled'}")
    if peer_server:
        print(f"Independent Knox API: http://{browser_host}:{args.peer_api_port}/v1 (decoder unverified; no writes)")
    if args.monitor_interval:
        collector.set_mode(
            args.monitor_mode,
            interval_seconds=args.monitor_interval,
            quiet_window_seconds=args.cloud_quiet_window,
            confirmed=True,
        )
        if args.monitor_mode == "cooperative":
            print(f"Cooperative datalogger: {monitor_host} target {args.monitor_interval}s with ±{args.cloud_quiet_window}s cloud windows")
        else:
            print(f"Local datalogger: {monitor_host} target {args.monitor_interval}s without cloud quiet windows")
    else:
        print("Collector mode: Original / cloud-only (no inverter I/O)")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping analyzer")
    finally:
        collector.stop()
        if peer_server:
            peer_server.shutdown()
            peer_server.server_close()
        if peer_thread:
            peer_thread.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
