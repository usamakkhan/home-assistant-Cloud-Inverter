from __future__ import annotations

import argparse
from pathlib import Path

from solarmax_analyzer.peer_api import DiskTelemetryReader, create_peer_server


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independent, read-only-first Knox neighbor telemetry and comparison API"
    )
    parser.add_argument("--bind", default="127.0.0.1", help="API bind address")
    parser.add_argument("--port", type=int, default=8767, help="API port")
    parser.add_argument("--dashboard-port", type=int, default=8765, help="allowed local dashboard Origin port")
    parser.add_argument(
        "--primary-db",
        default=str(ROOT / "data" / "telemetry.sqlite3"),
        help="SolarMax telemetry SQLite journal used only for comparison",
    )
    args = parser.parse_args()
    for label, value in (("API", args.port), ("dashboard Origin", args.dashboard_port)):
        if not 1 <= value <= 65535:
            parser.error(f"{label} port must be between 1 and 65535")
    primary = DiskTelemetryReader(args.primary_db)
    try:
        server = create_peer_server(
            args.bind,
            args.port,
            primary,
            ROOT / "data",
            dashboard_port=args.dashboard_port,
        )
    except OSError as exc:
        parser.error(f"cannot start API on {args.bind}:{args.port}: {exc}")
    print("Knox Neighbor Comparison API 1.0")
    print(f"API root: http://127.0.0.1:{args.port}/v1")
    print("Inverter writes: disabled; Knox decoder: unverified")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Knox API")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
