from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    key: str
    name: str
    address: int
    info_key: str
    risk: str
    portal_control: str
    notes: str


# Legacy read-back inventory. Guarded upload capabilities are independently
# defined in controls.py; this catalog itself never authorizes physical writes.
FEATURES = (
    FeatureSpec("work_mode", "Hybrid work mode", 0x2100, "hybrid_work_mode", "high", "Work mode", "Changes power-flow strategy."),
    FeatureSpec("schedule", "Schedule 1 recurrence and time range", 0x2101, "schedule_1_charge", "high", "Schedule 1", "Time fields span 0x2101-0x2105. Separate Time-based Control switch is 0x214C on newer portal protocols."),
    FeatureSpec("grid_charge", "Charge from grid", 0x2115, "grid_charge_enabled", "high", "Charge by Grid", "May increase grid consumption."),
    FeatureSpec("grid_charge_power", "Maximum grid charge power", 0x2116, "maximum_grid_charge_power_w", "critical", "Remote settings", "Must remain within inverter and battery limits."),
    FeatureSpec("grid_charge_end", "Grid charge end SOC", 0x2117, "grid_charge_end_soc_percent", "high", "Battery threshold", "Portal may display voltage mode instead of SOC mode."),
    FeatureSpec("charge_power", "Maximum battery charge power", 0x2118, "maximum_charge_power_w", "critical", "Remote settings", "Battery/BMS safety limit."),
    FeatureSpec("charge_end", "Charge end SOC", 0x2119, "charge_end_soc_percent", "high", "Battery threshold", "Upper state-of-charge target."),
    FeatureSpec("discharge_power", "Maximum battery discharge power", 0x211A, "maximum_discharge_power_w", "critical", "Remote settings", "Battery and cable safety limit."),
    FeatureSpec("discharge_end", "Discharge end SOC", 0x211B, "discharge_end_soc_percent", "critical", "Battery threshold", "Protects reserve capacity during outages."),
    FeatureSpec("off_grid", "Off-grid output enable", 0x211C, "off_grid_enabled", "critical", "Not captured in portal", "Distinct from hybrid work mode. Can energize or de-energize backed-up circuits."),
    FeatureSpec("off_grid_voltage", "Off-grid nominal voltage", 0x211D, "off_grid_nominal_voltage_v", "critical", "Not captured in portal", "Not Capacity Mode. Incorrect voltage can damage loads."),
    FeatureSpec("off_grid_frequency", "Off-grid nominal frequency", 0x211E, "off_grid_nominal_frequency_hz", "critical", "Not captured in portal", "Not Capacity Mode. Incorrect frequency can damage loads."),
    FeatureSpec("off_grid_start", "Off-grid start SOC", 0x211F, "off_grid_start_soc_percent", "high", "Not captured in portal", "Not verified as a GEN smart-load threshold; do not use to control AC, heater or water geyser."),
    FeatureSpec("max_discharge_current", "Maximum discharge current", 0x2120, "maximum_discharge_current_a", "critical", "Remote settings", "Battery/BMS safety limit."),
    FeatureSpec("max_charge_current", "Maximum charge current", 0x2121, "maximum_charge_current_a", "critical", "Remote settings", "Battery/BMS safety limit."),
    FeatureSpec("dynamic_power_limit", "Dynamic output power limit", 0x3005, "dynamic_power_limit_percent", "critical", "Power limit", "Can curtail inverter output."),
)


def feature_inventory(current_info: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    info = current_info or {}
    rows = []
    for feature in FEATURES:
        item = asdict(feature)
        item["address_hex"] = f"0x{feature.address:04X}"
        item["current_value"] = info.get(feature.info_key)
        item["read_mapped"] = True
        item["write_supported"] = False
        item["write_tested"] = False
        item["control_status"] = "read-back catalog; see Remote settings for upload capability"
        rows.append(item)
    return rows
