from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .peer import canonical_latest, finite_number, parse_timestamp, PRIMARY_SYSTEM, SystemSpec
from .peer_store import PeerStateStore


DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "primary_stale": {
        "enabled": True,
        "stale_after_seconds": 45,
    },
    "neighbor_stale": {
        "enabled": True,
        "stale_after_seconds": 45,
    },
    "peer_underperformance": {
        "enabled": False,
        "deficit_percent": 30.0,
        "clear_deficit_percent": 15.0,
        "trigger_for_seconds": 600,
        "clear_for_seconds": 300,
        "activation_w_per_kwp": 100.0,
        "minimum_pairs": 6,
        "max_sample_age_seconds": 45,
    },
    "primary_fault_words": {
        "enabled": True,
    },
}


class AlertEngine:
    """Persistent, deduplicated alerts with explicit calibration and suppression states."""

    def __init__(
        self,
        store: PeerStateStore,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()

    def rules(self) -> dict[str, dict[str, Any]]:
        return {
            rule_id: self.store.rule(rule_id, defaults)
            for rule_id, defaults in DEFAULT_RULES.items()
        }

    def update_rules(self, patch: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not isinstance(patch, dict):
            raise ValueError("rules must be a JSON object")
        unknown = set(patch) - set(DEFAULT_RULES)
        if unknown:
            raise ValueError(f"unknown alert rule(s): {', '.join(sorted(unknown))}")
        rules = self.rules()
        validated: dict[str, dict[str, Any]] = {}
        for rule_id, changes in patch.items():
            if not isinstance(changes, dict):
                raise ValueError(f"{rule_id} must be a JSON object")
            unsupported = set(changes) - set(DEFAULT_RULES[rule_id])
            if unsupported:
                raise ValueError(f"unsupported {rule_id} field(s): {', '.join(sorted(unsupported))}")
            merged = {**rules[rule_id], **changes}
            if not isinstance(merged.get("enabled"), bool):
                raise ValueError(f"{rule_id}.enabled must be true or false")
            for key, value in merged.items():
                if key == "enabled":
                    continue
                number = finite_number(value)
                if number is None or number < 0:
                    raise ValueError(f"{rule_id}.{key} must be a non-negative number")
                if key.endswith("seconds") or key == "minimum_pairs":
                    if int(number) != number:
                        raise ValueError(f"{rule_id}.{key} must be an integer")
                    merged[key] = int(number)
                else:
                    merged[key] = number
            if rule_id == "peer_underperformance":
                if merged["clear_deficit_percent"] >= merged["deficit_percent"]:
                    raise ValueError("clear deficit must be lower than trigger deficit")
                if not 0 < merged["deficit_percent"] <= 100:
                    raise ValueError("deficit percent must be between 0 and 100")
                if merged["minimum_pairs"] < 2:
                    raise ValueError("minimum_pairs must be at least 2")
            rules[rule_id] = merged
            validated[rule_id] = merged
        # Validate the whole request before opening the write transaction.  A
        # multi-rule API update is one configuration change, never a partial
        # series of independent saves.
        self.store.save_rules(validated)
        return rules

    def _save(
        self,
        alert_id: str,
        state_name: str,
        message: str,
        severity: str,
        device_id: str,
        details: dict[str, Any],
        *,
        pending_since: float | None = None,
        recovering_since: float | None = None,
    ) -> dict[str, Any]:
        previous = self.store.state(alert_id)
        now_iso = self._now_iso()
        opened_at = previous.get("opened_at") if previous else None
        resolved_at = previous.get("resolved_at") if previous else None
        if state_name == "firing" and (
            not previous or previous.get("state") not in {"firing", "recovering"}
        ):
            opened_at = now_iso
            resolved_at = None
        if state_name == "healthy" and previous and previous.get("state") in {"firing", "recovering"}:
            resolved_at = now_iso
        state = {
            "id": alert_id,
            "state": state_name,
            "pending_since": pending_since,
            "recovering_since": recovering_since,
            "opened_at": opened_at,
            "resolved_at": resolved_at,
            "updated_at": now_iso,
            "message": message,
            "severity": severity,
            "device_id": device_id,
            "details": details,
        }
        changed = previous is None or previous.get("state") != state_name
        refresh_due = True
        if previous and previous.get("updated_at"):
            updated = parse_timestamp(previous["updated_at"])
            refresh_due = updated is None or self.clock() - updated.timestamp() >= 60
        if changed or refresh_due:
            self.store.save_alert_state(state, emit_event=changed)
        return state

    @staticmethod
    def _age(snapshot: dict[str, Any] | None, now: float) -> float | None:
        if not snapshot:
            return None
        # API-ingested telemetry carries a server-authored received_at.  The
        # client-authored captured_at remains useful for display/alignment but
        # must not be able to make an old or future-dated upload look fresh.
        freshness_time = (
            parse_timestamp(snapshot.get("received_at"))
            or parse_timestamp(snapshot.get("captured_at"))
        )
        return max(0.0, now - freshness_time.timestamp()) if freshness_time else None

    def _stale_alert(
        self,
        alert_id: str,
        device_id: str,
        snapshot: dict[str, Any] | None,
        rule: dict[str, Any],
        *,
        monitoring_enabled: bool,
        setup_required: bool = False,
    ) -> dict[str, Any]:
        if not rule["enabled"]:
            return self._save(alert_id, "disabled", "Freshness alert is disabled.", "warning", device_id, {})
        if setup_required and snapshot is None:
            return self._save(
                alert_id, "setup_required", "Enter and verify the neighbor logger IP before freshness can be monitored.",
                "info", device_id, {},
            )
        if not monitoring_enabled:
            return self._save(
                alert_id, "monitoring_disabled", "Automatic collection is intentionally disabled.",
                "info", device_id, {},
            )
        if snapshot is not None and not snapshot.get("ok"):
            return self._save(
                alert_id, "firing", "The latest telemetry capture is partial or failed.",
                "warning", device_id, {"capture_ok": False},
            )
        age = self._age(snapshot, self.clock())
        threshold = float(rule["stale_after_seconds"])
        if age is None or age > threshold:
            return self._save(
                alert_id,
                "firing",
                "No fresh telemetry is available." if age is None else f"Latest telemetry is {age:.1f} seconds old.",
                "warning",
                device_id,
                {"age_seconds": age, "stale_after_seconds": threshold},
            )
        return self._save(
            alert_id, "healthy", f"Telemetry is fresh ({age:.1f} seconds old).", "info", device_id,
            {"age_seconds": age, "stale_after_seconds": threshold},
        )

    def _fault_alert(self, snapshot: dict[str, Any] | None, rule: dict[str, Any]) -> dict[str, Any]:
        if not rule["enabled"]:
            return self._save("primary_fault_words", "disabled", "Raw fault-word alert is disabled.", "critical", "primary", {})
        sensors = snapshot.get("sensors", {}) if snapshot else {}
        values = {
            key: finite_number(sensors.get(key, {}).get("value"))
            for key in ("error_1", "error_2", "error_3", "error_4")
        }
        known = {key: value for key, value in values.items() if value is not None}
        previous = self.store.state("primary_fault_words")
        if len(known) < 4:
            held = "firing" if previous and previous.get("state") in {"firing", "recovering"} else "unknown"
            return self._save(
                "primary_fault_words", held,
                "All four raw fault words are not available; a prior fault cannot be cleared.",
                "critical", "primary", {"raw": values, "evaluation": "suspended"}
            )
        active = {key: value for key, value in known.items() if value != 0}
        if active:
            return self._save(
                "primary_fault_words", "firing", "One or more raw SolarMax fault words are non-zero.",
                "critical", "primary", {"raw": values, "active": active, "decoded": False},
            )
        return self._save(
            "primary_fault_words", "healthy", "All captured SolarMax fault words are zero.",
            "info", "primary", {"raw": values, "decoded": False},
        )

    def _performance_alert(self, comparison: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
        alert_id = "peer_underperformance"
        previous = self.store.state(alert_id)
        if not rule["enabled"]:
            return self._save(
                alert_id, "calibration_required",
                "Peer performance alerts are off until array conditions and a baseline are confirmed.",
                "warning", "neighbor", {"enabled": False},
            )
        alignment = comparison.get("alignment", {})
        if not isinstance(alignment, dict):
            alignment = {}
        aligned_pair_count = int(alignment.get("pair_count") or 0)
        max_age = float(rule["max_sample_age_seconds"])
        newest_allowed = self.clock() - max_age
        comparable_pairs: list[tuple[dict[str, Any], datetime, datetime]] = []
        recent_comparable_pairs: list[tuple[dict[str, Any], datetime, datetime]] = []
        points = comparison.get("points")
        if not isinstance(points, list):
            points = []
        for point in points:
            if not isinstance(point, dict) or not point.get("comparable"):
                continue
            primary_metrics = point.get("primary")
            neighbor_metrics = point.get("neighbor")
            if not isinstance(primary_metrics, dict) or not isinstance(neighbor_metrics, dict):
                continue
            primary = finite_number(primary_metrics.get("specific_power_w_kwp"))
            neighbor = finite_number(neighbor_metrics.get("specific_power_w_kwp"))
            if primary is None or neighbor is None:
                continue
            primary_time = parse_timestamp(point.get("primary_captured_at"))
            neighbor_time = parse_timestamp(point.get("neighbor_captured_at"))
            if primary_time is None or neighbor_time is None:
                continue
            candidate = (point, primary_time, neighbor_time)
            comparable_pairs.append(candidate)
            if (
                primary_time.timestamp() >= newest_allowed
                and neighbor_time.timestamp() >= newest_allowed
            ):
                recent_comparable_pairs.append(candidate)

        comparable_pair_count = len(comparable_pairs)
        recent_comparable_pair_count = len(recent_comparable_pairs)
        minimum_pairs = int(rule["minimum_pairs"])
        if recent_comparable_pair_count < minimum_pairs:
            held = "firing" if previous and previous.get("state") in {"firing", "recovering"} else "calibrating"
            return self._save(
                alert_id, held,
                f"Waiting for {minimum_pairs} recent comparable pairs; "
                f"{recent_comparable_pair_count} available.",
                "warning", "neighbor", {
                    "aligned_pair_count": aligned_pair_count,
                    "comparable_pair_count": comparable_pair_count,
                    "recent_comparable_pair_count": recent_comparable_pair_count,
                    "minimum_pairs": minimum_pairs,
                    "max_sample_age_seconds": max_age,
                    "evaluation": "suspended",
                },
            )
        latest, primary_time, neighbor_time = max(
            recent_comparable_pairs,
            key=lambda candidate: min(candidate[1].timestamp(), candidate[2].timestamp()),
        )
        primary = finite_number(latest["primary"].get("specific_power_w_kwp"))
        neighbor = finite_number(latest["neighbor"].get("specific_power_w_kwp"))
        activation = float(rule["activation_w_per_kwp"])
        if primary is None or neighbor is None:
            held = "firing" if previous and previous.get("state") in {"firing", "recovering"} else "unknown"
            return self._save(
                alert_id, held, "Comparable PV values are unavailable; alert state was not cleared.",
                "warning", "neighbor", {"evaluation": "suspended"},
            )
        if max(primary, neighbor) < activation:
            held = "firing" if previous and previous.get("state") in {"firing", "recovering"} else "suppressed_low_light"
            return self._save(
                alert_id, held, "Low-light period: relative performance evaluation is suppressed.",
                "info", "neighbor", {"evaluation": "suppressed", "activation_w_per_kwp": activation},
            )
        deficit = max(0.0, (primary - neighbor) * 100 / primary) if primary > 0 else 0.0
        trigger = float(rule["deficit_percent"])
        clear = float(rule["clear_deficit_percent"])
        now = self.clock()
        state_name = previous.get("state") if previous else "healthy"
        pending_since = previous.get("pending_since") if previous else None
        recovering_since = previous.get("recovering_since") if previous else None
        details = {
            "primary_w_per_kwp": primary,
            "neighbor_w_per_kwp": neighbor,
            "deficit_percent": deficit,
            "trigger_percent": trigger,
            "clear_percent": clear,
            "aligned_pair_count": aligned_pair_count,
            "comparable_pair_count": comparable_pair_count,
            "recent_comparable_pair_count": recent_comparable_pair_count,
            "sample_skew_ms": latest.get("skew_ms"),
        }
        if deficit >= trigger:
            recovering_since = None
            if state_name == "firing":
                return self._save(alert_id, "firing", f"Possible sustained neighbor underperformance: {deficit:.1f}% normalized deficit.", "warning", "neighbor", details, pending_since=pending_since)
            pending_since = pending_since or now
            if now - pending_since >= float(rule["trigger_for_seconds"]):
                return self._save(alert_id, "firing", f"Possible sustained neighbor underperformance: {deficit:.1f}% normalized deficit.", "warning", "neighbor", details, pending_since=pending_since)
            return self._save(alert_id, "pending", f"Normalized deficit {deficit:.1f}% is being timed before an alert.", "warning", "neighbor", details, pending_since=pending_since)
        pending_since = None
        if state_name in {"firing", "recovering"}:
            if deficit <= clear:
                recovering_since = recovering_since or now
                if now - recovering_since >= float(rule["clear_for_seconds"]):
                    return self._save(alert_id, "healthy", "Normalized output recovered for the configured clear period.", "info", "neighbor", details)
                return self._save(alert_id, "recovering", f"Normalized deficit is recovering at {deficit:.1f}%.", "warning", "neighbor", details, recovering_since=recovering_since)
            return self._save(alert_id, "firing", f"Possible neighbor underperformance remains open at {deficit:.1f}%.", "warning", "neighbor", details)
        return self._save(alert_id, "healthy", f"Latest normalized difference is within the configured alert range ({deficit:.1f}%).", "info", "neighbor", details)

    def evaluate(
        self,
        primary_snapshot: dict[str, Any] | None,
        neighbor_snapshot: dict[str, Any] | None,
        neighbor_system: SystemSpec,
        neighbor_config: dict[str, Any],
        comparison: dict[str, Any],
        *,
        primary_monitoring: bool,
        primary_stale_after_seconds: float | None = None,
        neighbor_stale_after_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        rules = self.rules()
        primary_rule = dict(rules["primary_stale"])
        if primary_stale_after_seconds is not None:
            primary_rule["stale_after_seconds"] = max(
                float(primary_rule["stale_after_seconds"]), float(primary_stale_after_seconds)
            )
        neighbor_rule = dict(rules["neighbor_stale"])
        if neighbor_stale_after_seconds is not None:
            neighbor_rule["stale_after_seconds"] = max(
                float(neighbor_rule["stale_after_seconds"]), float(neighbor_stale_after_seconds)
            )
        results = [
            self._stale_alert(
                "primary_stale", "primary", primary_snapshot, primary_rule,
                monitoring_enabled=primary_monitoring,
            ),
            self._stale_alert(
                "neighbor_stale", "neighbor", neighbor_snapshot, neighbor_rule,
                monitoring_enabled=neighbor_snapshot is not None,
                setup_required=not bool(neighbor_config.get("host")),
            ),
            self._fault_alert(primary_snapshot, rules["primary_fault_words"]),
            self._performance_alert(comparison, rules["peer_underperformance"]),
        ]
        return results
