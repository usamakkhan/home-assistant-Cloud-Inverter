from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ComparisonField:
    key: str
    label: str
    local_key: str
    unit: str
    absolute_tolerance: float
    percent_tolerance: float = 3.0
    multiplier: float = 1.0
    transform: str = "identity"


# CloudInverter's information page labels normalized to the units used here.
# Power values are W and energy values are kWh, even when the portal displays
# kW or MWh. Battery power is negative while charging in the local protocol.
CLOUD_FIELDS = (
    ComparisonField("current_power", "Current / PV power", "pv_power", "W", 100),
    ComparisonField("temperature", "Inverter temperature", "temperature", "°C", 2, 1),
    ComparisonField("battery_voltage", "Battery voltage", "battery_voltage", "V", 0.5, 1),
    ComparisonField("battery_current", "Battery current", "battery_current", "A", 0.5, 5),
    ComparisonField("battery_charging_power", "Battery charging power", "battery_power", "W", 100, 8, transform="charge"),
    ComparisonField("battery_discharging_power", "Battery discharging power", "battery_power", "W", 100, 8, transform="discharge"),
    ComparisonField("battery_soc", "Battery SOC", "battery_soc", "%", 1, 1),
    ComparisonField("battery_discharge_today", "Battery discharge today", "battery_discharge_today", "kWh", 0.1, 2),
    ComparisonField("battery_charge_today", "Battery charge today", "battery_charge_today", "kWh", 0.1, 2),
    ComparisonField("battery_discharge_total", "Battery discharge total", "battery_discharge_total", "kWh", 0.2, 0.2),
    ComparisonField("battery_charge_total", "Battery charge total", "battery_charge_total", "kWh", 0.2, 0.2),
    ComparisonField("pv1_voltage", "MPPT1 voltage", "pv1_voltage", "V", 1, 1),
    ComparisonField("pv1_current", "MPPT1 current", "pv1_current", "A", 0.25, 4),
    ComparisonField("pv1_power", "MPPT1 power", "pv1_power", "W", 75, 5),
    ComparisonField("pv2_voltage", "MPPT2 voltage", "pv2_voltage", "V", 1, 1),
    ComparisonField("pv2_current", "MPPT2 current", "pv2_current", "A", 0.25, 4),
    ComparisonField("pv2_power", "MPPT2 power", "pv2_power", "W", 75, 5),
    ComparisonField("pv_peak_today", "Peak PV power today", "pv_peak_today", "W", 100, 3),
    ComparisonField("today_energy", "PV energy today", "today_energy", "kWh", 0.1, 1, multiplier=0.001),
    ComparisonField("total_energy", "PV energy total", "total_energy", "kWh", 0.2, 0.1),
    ComparisonField("generation_hours", "Generation hours", "generation_hours", "h", 1, 0.1),
    ComparisonField("grid_voltage", "Grid L1 voltage", "grid_voltage", "V", 1, 1),
    ComparisonField("grid_current", "Grid L1 current", "grid_current", "A", 0.35, 5),
    ComparisonField("grid_power", "Grid L1 power", "grid_power", "W", 100, 6),
    ComparisonField("grid_frequency", "Grid frequency", "grid_frequency", "Hz", 0.05, 0.2),
    ComparisonField("grid_export_today", "Feed-in energy today", "grid_export_today", "kWh", 0.1, 2),
    ComparisonField("grid_export_total", "Feed-in energy total", "grid_export_total", "kWh", 0.2, 0.1),
    ComparisonField("grid_import_today", "Purchased energy today", "grid_import_today", "kWh", 0.1, 2),
    ComparisonField("grid_import_total", "Purchased energy total", "grid_import_total", "kWh", 0.2, 0.1),
    ComparisonField("normal_voltage", "Normal Load L1 voltage", "load_voltage", "V", 1, 1),
    ComparisonField("normal_current", "Normal Load L1 current", "load_current", "A", 0.2, 5),
    ComparisonField("normal_power", "Normal Load L1 power", "load_power", "W", 75, 6),
    ComparisonField("normal_energy_today", "Normal Load consumption today", "load_energy_today", "kWh", 0.1, 2),
    ComparisonField("normal_energy_total", "Normal Load total consumption", "load_energy_total", "kWh", 0.2, 0.1),
    ComparisonField("backup_voltage", "Backup Load L1 voltage", "backup_voltage", "V", 1, 1),
    ComparisonField("backup_current", "Backup Load L1 current", "backup_current", "A", 0.25, 5),
    ComparisonField("backup_power", "Backup Load L1 power", "backup_power", "W", 100, 6),
    ComparisonField("backup_frequency", "Backup Load frequency", "backup_frequency", "Hz", 0.05, 0.2),
    ComparisonField("backup_energy_today", "Backup Load consumption today", "backup_energy_today", "kWh", 0.1, 2),
    ComparisonField("backup_energy_total", "Backup Load total consumption", "backup_energy_total", "kWh", 0.2, 0.1),
    ComparisonField("gen_voltage", "GEN smart-load L1 voltage", "gen_port_voltage", "V", 1, 1),
    ComparisonField("gen_current", "GEN smart-load L1 current", "gen_port_current", "A", 0.3, 5),
    ComparisonField("gen_power", "GEN smart-load L1 power", "gen_port_power", "W", 100, 6),
    ComparisonField("gen_frequency", "GEN smart-load frequency", "gen_port_frequency", "Hz", 0.05, 0.2),
    ComparisonField("gen_energy_today", "GEN smart-load consumption today", "gen_port_energy_today", "kWh", 0.1, 2),
    ComparisonField("gen_energy_total", "GEN smart-load total consumption", "gen_port_energy_total", "kWh", 0.2, 0.1),
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _local_value(snapshot: dict[str, Any], field: ComparisonField) -> float | None:
    sensor = snapshot.get("sensors", {}).get(field.local_key)
    if not sensor:
        return None
    value = _number(sensor.get("value"))
    if value is None:
        return None
    value *= field.multiplier
    if field.transform == "charge":
        value = max(-value, 0)
    elif field.transform == "discharge":
        value = max(value, 0)
    return round(value, 4)


def compare_snapshot(
    snapshot: dict[str, Any],
    cloud_reference: dict[str, Any] | None,
    cloud_captured_at: str | None = None,
) -> dict[str, Any]:
    reference = cloud_reference or {}
    rows: list[dict[str, Any]] = []
    compared = within = 0
    for field in CLOUD_FIELDS:
        local = _local_value(snapshot, field)
        cloud = _number(reference.get(field.key))
        row: dict[str, Any] = {
            "key": field.key,
            "label": field.label,
            "unit": field.unit,
            "local": local,
            "cloud": cloud,
            "status": "reference_missing" if cloud is None else "local_missing",
        }
        if local is not None and cloud is not None:
            delta = round(local - cloud, 4)
            absolute_delta = abs(delta)
            tolerance = max(
                field.absolute_tolerance,
                abs(cloud) * field.percent_tolerance / 100,
            )
            is_within = absolute_delta <= tolerance
            percent_error = None if cloud == 0 else round(absolute_delta / abs(cloud) * 100, 3)
            row.update({
                "delta": delta,
                "absolute_delta": round(absolute_delta, 4),
                "percent_error": percent_error,
                "tolerance": round(tolerance, 4),
                "within_tolerance": is_within,
                "status": "match" if is_within else "different",
            })
            compared += 1
            within += int(is_within)
        rows.append(row)

    age_seconds = None
    if cloud_captured_at and snapshot.get("captured_at"):
        try:
            cloud_time = datetime.fromisoformat(cloud_captured_at.replace("Z", "+00:00"))
            local_time = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
            age_seconds = round(abs((local_time - cloud_time).total_seconds()), 1)
        except (TypeError, ValueError):
            pass
    return {
        "cloud_captured_at": cloud_captured_at,
        "local_captured_at": snapshot.get("captured_at"),
        "reference_age_seconds": age_seconds,
        "reference_stale": age_seconds is not None and age_seconds > 90,
        "compared_count": compared,
        "within_tolerance_count": within,
        "accuracy_percent": round(within / compared * 100, 1) if compared else None,
        "rows": rows,
    }


def partition_single_phase_sensors(
    sensors: dict[str, dict[str, Any]],
    phase_count: int | None,
    mppt_count: int | None,
) -> dict[str, Any]:
    inactive_phase_keys: set[str] = set()
    if phase_count == 1:
        inactive_phase_keys.update(
            key for key in sensors
            if "_l2_" in key or "_l3_" in key or key.startswith("ac_l2") or key.startswith("ac_l3")
        )

    visible: dict[str, dict[str, Any]] = {}
    zero_reference: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for key, sensor in sensors.items():
        if key not in inactive_phase_keys:
            visible[key] = sensor
            continue
        value = _number(sensor.get("value"))
        item = {"key": key, **sensor, "expected_zero": not key.endswith("frequency"), "source": "measured"}
        if value == 0:
            item["state"] = "confirmed_zero"
            zero_reference.append(item)
        elif key in {"ac_l2_frequency", "ac_l3_frequency"} and value == _number(sensors.get("ac_frequency", {}).get("value")):
            # This single-phase model mirrors the common AC frequency into the
            # unused phase-frequency words. It is not evidence of L2/L3.
            item["state"] = "mirrored_common_frequency"
            item["source"] = "protocol mirror"
            zero_reference.append(item)
        else:
            item["state"] = "unexpected_nonzero"
            anomalies.append(item)
            visible[key] = sensor

    if mppt_count is not None:
        for index in range(mppt_count + 1, 10):
            for quantity, unit in (("voltage", "V"), ("current", "A"), ("power", "W")):
                zero_reference.append({
                    "key": f"pv{index}_{quantity}",
                    "name": f"PV{index} {quantity}",
                    "value": 0,
                    "unit": unit,
                    "expected_zero": True,
                    "state": "not_applicable_virtual_zero",
                    "source": "MPPT capability",
                })
    return {
        "visible_sensors": visible,
        "zero_reference_sensors": zero_reference,
        "zero_anomalies": anomalies,
    }


def cloud_field_schema() -> list[dict[str, Any]]:
    return [
        {"key": field.key, "label": field.label, "unit": field.unit}
        for field in CLOUD_FIELDS
    ]
