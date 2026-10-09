from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
MAX_FUTURE_CAPTURE_SKEW_SECONDS = 300


@dataclass(frozen=True, slots=True)
class SystemSpec:
    id: str
    name: str
    manufacturer: str
    model: str
    panel_count: int
    panel_watts: float
    inverter_ac_watts: float

    @property
    def dc_nameplate_watts(self) -> float:
        return self.panel_count * self.panel_watts

    @property
    def dc_nameplate_kwp(self) -> float:
        return self.dc_nameplate_watts / 1000

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["array"] = {
            "panel_count": self.panel_count,
            "panel_watts": self.panel_watts,
            "dc_nameplate_watts": self.dc_nameplate_watts,
            "dc_nameplate_kwp": self.dc_nameplate_kwp,
        }
        return result


PRIMARY_SYSTEM = SystemSpec(
    id="primary",
    name="My SolarMax",
    manufacturer="SolarMax",
    model="PV9000 / SM-ONYX-UL-6KW",
    panel_count=12,
    panel_watts=585,
    inverter_ac_watts=6000,
)

DEFAULT_NEIGHBOR_SYSTEM = SystemSpec(
    id="neighbor",
    name="Neighbor Knox",
    manufacturer="Knox",
    model="Krypton 6kW / PV7200W",
    panel_count=10,
    panel_watts=585,
    inverter_ac_watts=6000,
)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def point_metrics(point: dict[str, Any], system: SystemSpec) -> dict[str, Any]:
    """Normalize one history point without turning missing readings into zero."""
    power = finite_number(point.get("pv_power"))
    energy_wh = finite_number(point.get("today_energy"))
    if power is not None and power < 0:
        power = None
    if energy_wh is not None and energy_wh < 0:
        energy_wh = None
    return {
        "pv_power_w": power,
        "power_per_panel_w": power / system.panel_count if power is not None else None,
        "specific_power_w_kwp": power * 1000 / system.dc_nameplate_watts if power is not None else None,
        "capacity_utilization_percent": (
            power * 100 / system.dc_nameplate_watts if power is not None else None
        ),
        "energy_today_kwh": energy_wh / 1000 if energy_wh is not None else None,
        "specific_yield_kwh_kwp": energy_wh / system.dc_nameplate_watts if energy_wh is not None else None,
    }


def canonical_latest(snapshot: dict[str, Any] | None, system: SystemSpec) -> dict[str, Any]:
    if snapshot is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "device": system.to_dict(),
            "available": False,
            "captured_at": None,
            "received_at": None,
            "age_seconds": None,
            "age_basis": None,
            "metrics": {},
        }
    sensors = snapshot.get("sensors", {})
    point = {
        "pv_power": sensors.get("pv_power", {}).get("value"),
        "today_energy": sensors.get("today_energy", {}).get("value"),
    }
    captured = parse_timestamp(snapshot.get("captured_at"))
    received = parse_timestamp(snapshot.get("received_at"))
    freshness_time = received or captured
    age = None
    if freshness_time is not None:
        age = max(0.0, (datetime.now(timezone.utc) - freshness_time).total_seconds())
    metrics = point_metrics(point, system)
    return {
        "schema_version": SCHEMA_VERSION,
        "device": system.to_dict(),
        "available": bool(snapshot.get("ok")),
        "captured_at": snapshot.get("captured_at"),
        "received_at": snapshot.get("received_at"),
        "age_seconds": round(age, 1) if age is not None else None,
        "age_basis": "received_at" if received is not None else ("captured_at" if captured is not None else None),
        "capture": {
            "ok": bool(snapshot.get("ok")),
            "source": snapshot.get("source") or snapshot.get("capture_source"),
            "profile": snapshot.get("driver") or snapshot.get("profile"),
            "profile_confidence": snapshot.get("profile_confidence", "verified" if system.id == "primary" else "unverified"),
        },
        "metrics": metrics,
    }


def _timestamp_ms(point: dict[str, Any]) -> int | None:
    raw = finite_number(point.get("timestamp_ms"))
    if raw is not None:
        return round(raw)
    parsed = parse_timestamp(point.get("captured_at"))
    return round(parsed.timestamp() * 1000) if parsed is not None else None


def align_history(
    primary_points: Iterable[dict[str, Any]],
    neighbor_points: Iterable[dict[str, Any]],
    primary_system: SystemSpec = PRIMARY_SYSTEM,
    neighbor_system: SystemSpec = DEFAULT_NEIGHBOR_SYSTEM,
    *,
    max_skew_seconds: float = 15,
) -> list[dict[str, Any]]:
    """Pair timestamps one-to-one, maximizing matches before minimizing total skew.

    An independent nearest-neighbor choice can consume the only viable sample for
    a later point.  Candidate pairs form an ordered bipartite graph, so the best
    non-crossing chain gives a maximum-cardinality matching.  Absolute timestamp
    distance is Monge: crossing pairs can always be uncrossed without increasing
    skew or violating the tolerance.  The Fenwick-tree dynamic program below
    therefore finds a globally optimal matching without a quadratic timestamp
    matrix.  Readings are never interpolated and missing values are never zeroed.
    """
    left = sorted(
        ((timestamp, point) for point in primary_points if (timestamp := _timestamp_ms(point)) is not None),
        key=lambda item: item[0],
    )
    right = sorted(
        ((timestamp, point) for point in neighbor_points if (timestamp := _timestamp_ms(point)) is not None),
        key=lambda item: item[0],
    )
    tolerance_ms = max(0, round(float(max_skew_seconds) * 1000))
    if not left or not right:
        return []

    right_times = [item[0] for item in right]

    # A state is (pair count, total skew, last edge id).  For every right-side
    # prefix, retain the longest chain and then the lowest-skew chain.  Updates
    # for one left sample are delayed until all of its candidates are queried,
    # which prevents a sample from pairing more than once.
    State = tuple[int, int, int | None]
    empty: State = (0, 0, None)
    tree: list[State] = [empty for _ in range(len(right) + 1)]
    edges: list[tuple[int, int, int | None]] = []

    def better(candidate: State, current: State) -> bool:
        return candidate[0] > current[0] or (
            candidate[0] == current[0] and candidate[1] < current[1]
        )

    def query(stop: int) -> State:
        result = empty
        while stop > 0:
            if better(tree[stop], result):
                result = tree[stop]
            stop -= stop & -stop
        return result

    def update(position: int, state: State) -> None:
        while position < len(tree):
            if better(state, tree[position]):
                tree[position] = state
            position += position & -position

    for left_index, (left_time, _left_point) in enumerate(left):
        start = bisect_left(right_times, left_time - tolerance_ms)
        stop = bisect_right(right_times, left_time + tolerance_ms)
        pending: list[tuple[int, State]] = []
        for right_index in range(start, stop):
            previous = query(right_index)  # Strictly earlier right indexes only.
            edge_id = len(edges)
            skew_ms = abs(right[right_index][0] - left_time)
            edges.append((left_index, right_index, previous[2]))
            pending.append(
                (
                    right_index + 1,
                    (previous[0] + 1, previous[1] + skew_ms, edge_id),
                )
            )
        for position, state in pending:
            update(position, state)

    matched_indexes: list[tuple[int, int]] = []
    edge_id = query(len(right))[2]
    while edge_id is not None:
        left_index, right_index, edge_id = edges[edge_id]
        matched_indexes.append((left_index, right_index))
    matched_indexes.reverse()

    pairs: list[dict[str, Any]] = []
    for left_index, right_index in matched_indexes:
        left_time, left_point = left[left_index]
        right_time, right_point = right[right_index]
        skew_ms = abs(right_time - left_time)
        primary_metrics = point_metrics(left_point, primary_system)
        neighbor_metrics = point_metrics(right_point, neighbor_system)
        primary_specific = primary_metrics["specific_power_w_kwp"]
        neighbor_specific = neighbor_metrics["specific_power_w_kwp"]
        comparable = primary_specific is not None and neighbor_specific is not None
        pairs.append({
            "timestamp_ms": left_time,
            "primary_captured_at": left_point.get("captured_at"),
            "neighbor_captured_at": right_point.get("captured_at"),
            "skew_ms": skew_ms,
            "comparable": comparable,
            "primary": primary_metrics,
            "neighbor": neighbor_metrics,
            "delta": {
                "specific_power_w_kwp": (
                    primary_specific - neighbor_specific if comparable else None
                ),
                "neighbor_to_primary_percent": (
                    neighbor_specific * 100 / primary_specific
                    if comparable and primary_specific != 0
                    else (100.0 if comparable and neighbor_specific == 0 else None)
                ),
            },
        })
    return pairs


def comparison_payload(
    primary_points: Iterable[dict[str, Any]],
    neighbor_points: Iterable[dict[str, Any]],
    neighbor_system: SystemSpec = DEFAULT_NEIGHBOR_SYSTEM,
    *,
    max_skew_seconds: float = 15,
) -> dict[str, Any]:
    pairs = align_history(
        primary_points,
        neighbor_points,
        PRIMARY_SYSTEM,
        neighbor_system,
        max_skew_seconds=max_skew_seconds,
    )
    comparable_pairs = [pair for pair in pairs if pair["comparable"]]
    latest_aligned = pairs[-1] if pairs else None
    latest_comparable = comparable_pairs[-1] if comparable_pairs else None
    return {
        "schema_version": SCHEMA_VERSION,
        "available": bool(comparable_pairs),
        "reason": (
            None
            if comparable_pairs
            else "no_comparable_samples" if pairs else "no_aligned_samples"
        ),
        "electrical_point": "dc_pv_input",
        "alignment": {
            "method": "maximum_cardinality_minimum_total_skew_no_interpolation",
            "max_skew_seconds": max_skew_seconds,
            "pair_count": len(pairs),
            "comparable_pair_count": len(comparable_pairs),
        },
        "systems": {
            "primary": PRIMARY_SYSTEM.to_dict(),
            "neighbor": neighbor_system.to_dict(),
        },
        # Keep `latest` as the most recent timestamp-aligned pair for API
        # compatibility.  Consumers making a performance judgment must use the
        # explicit comparable field (or validate `points`) instead.
        "latest": latest_aligned,
        "latest_aligned": latest_aligned,
        "latest_comparable": latest_comparable,
        "points": pairs,
        "cautions": [
            "Roof direction, tilt, shade, temperature, soiling and curtailment can differ.",
            "Performance alerts require a sustained learned baseline; one sample is not diagnostic.",
        ],
    }


def build_neighbor_snapshot(
    payload: dict[str, Any],
    system: SystemSpec,
    *,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate local analysis-tool input for the protocol-neutral neighbor API."""
    if not isinstance(payload, dict):
        raise ValueError("sample must be a JSON object")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a JSON object")
    captured = parse_timestamp(payload.get("captured_at"))
    if captured is None:
        raise ValueError("captured_at must be an ISO-8601 timestamp")
    received = received_at or datetime.now(timezone.utc)
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    received = received.astimezone(timezone.utc)
    if captured > received + timedelta(seconds=MAX_FUTURE_CAPTURE_SKEW_SECONDS):
        raise ValueError(
            f"captured_at must not be more than {MAX_FUTURE_CAPTURE_SKEW_SECONDS} seconds in the future"
        )

    def metric(name: str, *, nonnegative: bool = True) -> float | None:
        raw = metrics.get(name)
        if isinstance(raw, dict):
            raw = raw.get("value")
        if raw is None:
            return None
        value = finite_number(raw)
        if value is None or (nonnegative and value < 0):
            raise ValueError(f"{name} must be a finite{' non-negative' if nonnegative else ''} number or null")
        return value

    pv_power = metric("pv_dc_power_w")
    energy_kwh = metric("energy_today_kwh")
    ac_power = metric("ac_output_power_w")
    battery_soc = metric("battery_soc_percent")
    if battery_soc is not None and not 0 <= battery_soc <= 100:
        raise ValueError("battery_soc_percent must be between 0 and 100")
    if all(value is None for value in (pv_power, energy_kwh, ac_power, battery_soc)):
        raise ValueError("sample must contain at least one supported metric value")
    sensors: dict[str, dict[str, Any]] = {}
    for key, name, value, unit, category in (
        ("pv_power", "PV total input power", pv_power, "W", "PV inputs"),
        ("today_energy", "Energy generated today", energy_kwh * 1000 if energy_kwh is not None else None, "Wh", "Energy"),
        ("ac_power", "AC output power", ac_power, "W", "Inverter"),
        ("battery_soc", "Battery state of charge", battery_soc, "%", "Battery"),
    ):
        if value is not None:
            sensors[key] = {
                "name": name,
                "value": value,
                "unit": unit,
                "category": category,
                "quality": "measured",
                "provenance": str(payload.get("provenance") or "local_analysis_api"),
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "captured_at": captured.isoformat(),
        # Server-authored receipt time is the trust boundary for liveness.
        # captured_at remains the client observation time used for alignment.
        "received_at": received.isoformat(),
        "device_id": system.id,
        "model": system.model,
        "driver": str(payload.get("driver") or "protocol_neutral_ingest"),
        "profile_confidence": str(payload.get("profile_confidence") or "unverified"),
        "capture_source": "neighbor_api_ingest",
        "array": system.to_dict()["array"],
        "sensors": sensors,
        "sensor_count": len(sensors),
    }
