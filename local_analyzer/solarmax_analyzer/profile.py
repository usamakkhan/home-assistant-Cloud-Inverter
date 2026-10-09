from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any

from .discovery import validate_host
from .modbus import ModbusClient
from .comparison import partition_single_phase_sensors


@dataclass(frozen=True, slots=True)
class RegisterSpec:
    key: str
    name: str
    address: int
    data_type: str
    scale: float
    unit: str

    @property
    def count(self) -> int:
        return 2 if self.data_type in {"u32", "s32"} else 1


# Senergy/APD Modbus protocol v1.2 addresses, validated against the local
# SM-ONYX-UL-6KW. All entries below are documented read-only registers.
SPECS = (
    RegisterSpec("ac_voltage", "Inverter L1 voltage", 0x1001, "u16", 0.1, "V"),
    RegisterSpec("ac_current", "Inverter L1 current", 0x1002, "u16", 0.01, "A"),
    RegisterSpec("ac_power", "Inverter L1 power", 0x1003, "s32", 0.1, "W"),
    RegisterSpec("ac_frequency", "Inverter L1 frequency", 0x1005, "u16", 0.01, "Hz"),
    RegisterSpec("ac_l2_voltage", "Inverter L2 voltage", 0x1006, "u16", 0.1, "V"),
    RegisterSpec("ac_l2_current", "Inverter L2 current", 0x1007, "u16", 0.01, "A"),
    RegisterSpec("ac_l2_power", "Inverter L2 power", 0x1008, "s32", 0.1, "W"),
    RegisterSpec("ac_l2_frequency", "Inverter L2 frequency", 0x100A, "u16", 0.01, "Hz"),
    RegisterSpec("ac_l3_voltage", "Inverter L3 voltage", 0x100B, "u16", 0.1, "V"),
    RegisterSpec("ac_l3_current", "Inverter L3 current", 0x100C, "u16", 0.01, "A"),
    RegisterSpec("ac_l3_power", "Inverter L3 power", 0x100D, "s32", 0.1, "W"),
    RegisterSpec("ac_l3_frequency", "Inverter L3 frequency", 0x100F, "u16", 0.01, "Hz"),
    RegisterSpec("pv1_voltage", "PV1 voltage", 0x1010, "u16", 0.1, "V"),
    RegisterSpec("pv1_current", "PV1 current", 0x1011, "u16", 0.01, "A"),
    RegisterSpec("pv1_power", "PV1 power", 0x1012, "u32", 0.1, "W"),
    RegisterSpec("pv2_voltage", "PV2 voltage", 0x1014, "u16", 0.1, "V"),
    RegisterSpec("pv2_current", "PV2 current", 0x1015, "u16", 0.01, "A"),
    RegisterSpec("pv2_power", "PV2 power", 0x1016, "u32", 0.1, "W"),
    RegisterSpec("pv3_voltage", "PV3 voltage", 0x1018, "u16", 0.1, "V"),
    RegisterSpec("pv3_current", "PV3 current", 0x1019, "u16", 0.01, "A"),
    RegisterSpec("pv3_power", "PV3 power", 0x101A, "u32", 0.1, "W"),
    RegisterSpec("temperature", "Inverter temperature", 0x101C, "s16", 1, "°C"),
    RegisterSpec("inverter_mode", "Inverter mode code", 0x101D, "u16", 1, ""),
    RegisterSpec("error_1", "Error code 1", 0x101E, "u16", 1, ""),
    RegisterSpec("error_2", "Error code 2", 0x101F, "u16", 1, ""),
    RegisterSpec("error_3", "Error code 3", 0x1020, "u16", 1, ""),
    RegisterSpec("total_energy", "Total generated energy", 0x1021, "u32", 1, "kWh"),
    RegisterSpec("generation_hours", "Total generation time", 0x1023, "u32", 1, "h"),
    RegisterSpec("today_energy", "Energy generated today", 0x1027, "u32", 1, "Wh"),
    RegisterSpec("grid_active_power_total", "Grid total active power", 0x1037, "s32", 0.1, "W"),
    RegisterSpec("grid_reactive_power_total", "Grid total reactive power", 0x1039, "s32", 0.1, "var"),
    RegisterSpec("pv_peak_today", "PV peak power today", 0x103B, "s32", 0.1, "W"),
    RegisterSpec("power_factor", "Power factor", 0x103D, "s16", 0.001, ""),
    RegisterSpec("pv4_voltage", "PV4 voltage", 0x103E, "u16", 0.1, "V"),
    RegisterSpec("pv4_current", "PV4 current", 0x103F, "u16", 0.01, "A"),
    RegisterSpec("pv4_power", "PV4 power", 0x1040, "u32", 0.1, "W"),
    RegisterSpec("pv_power", "PV total input power", 0x1048, "u32", 0.1, "W"),
    RegisterSpec("total_energy_wh_remainder", "Total energy Wh remainder", 0x104C, "u16", 1, "Wh"),
    RegisterSpec("pv5_voltage", "PV5 voltage", 0x1080, "u16", 0.1, "V"),
    RegisterSpec("pv5_current", "PV5 current", 0x1081, "u16", 0.01, "A"),
    RegisterSpec("pv5_power", "PV5 power", 0x1082, "u32", 0.1, "W"),
    RegisterSpec("pv6_voltage", "PV6 voltage", 0x1084, "u16", 0.1, "V"),
    RegisterSpec("pv6_current", "PV6 current", 0x1085, "u16", 0.01, "A"),
    RegisterSpec("pv6_power", "PV6 power", 0x1086, "u32", 0.1, "W"),
    RegisterSpec("pv7_voltage", "PV7 voltage", 0x1088, "u16", 0.1, "V"),
    RegisterSpec("pv7_current", "PV7 current", 0x1089, "u16", 0.01, "A"),
    RegisterSpec("pv7_power", "PV7 power", 0x108A, "u32", 0.1, "W"),
    RegisterSpec("pv8_voltage", "PV8 voltage", 0x108C, "u16", 0.1, "V"),
    RegisterSpec("pv8_current", "PV8 current", 0x108D, "u16", 0.01, "A"),
    RegisterSpec("pv8_power", "PV8 power", 0x108E, "u32", 0.1, "W"),
    RegisterSpec("pv9_voltage", "PV9 voltage", 0x1090, "u16", 0.1, "V"),
    RegisterSpec("pv9_current", "PV9 current", 0x1091, "u16", 0.01, "A"),
    RegisterSpec("pv9_power", "PV9 power", 0x1092, "u32", 0.1, "W"),
    RegisterSpec("grid_power", "Grid L1 power", 0x1300, "s32", 0.1, "W"),
    RegisterSpec("grid_l2_power", "Grid L2 power", 0x1302, "s32", 0.1, "W"),
    RegisterSpec("grid_l3_power", "Grid L3 power", 0x1304, "s32", 0.1, "W"),
    RegisterSpec("grid_import_total", "Grid import total", 0x1306, "u32", 0.01, "kWh"),
    RegisterSpec("grid_export_total", "Grid export total", 0x1308, "u32", 0.01, "kWh"),
    RegisterSpec("load_power", "Measured load L1 power", 0x130A, "s32", 0.1, "W"),
    RegisterSpec("load_l2_power", "Measured load L2 power", 0x130C, "s32", 0.1, "W"),
    RegisterSpec("load_l3_power", "Measured load L3 power", 0x130E, "s32", 0.1, "W"),
    RegisterSpec("load_energy_total", "Load energy total", 0x1310, "u32", 0.01, "kWh"),
    RegisterSpec("grid_voltage", "Grid L1 voltage", 0x131A, "u16", 0.1, "V"),
    RegisterSpec("grid_l2_voltage", "Grid L2 voltage", 0x131B, "u16", 0.1, "V"),
    RegisterSpec("grid_l3_voltage", "Grid L3 voltage", 0x131C, "u16", 0.1, "V"),
    RegisterSpec("grid_current", "Grid L1 current", 0x131D, "s32", 0.01, "A"),
    RegisterSpec("grid_l2_current", "Grid L2 current", 0x131F, "s32", 0.01, "A"),
    RegisterSpec("grid_l3_current", "Grid L3 current", 0x1321, "s32", 0.01, "A"),
    RegisterSpec("load_voltage", "Load L1 voltage", 0x1323, "u16", 0.1, "V"),
    RegisterSpec("load_l2_voltage", "Load L2 voltage", 0x1324, "u16", 0.1, "V"),
    RegisterSpec("load_l3_voltage", "Load L3 voltage", 0x1325, "u16", 0.1, "V"),
    RegisterSpec("load_current", "Load L1 current", 0x1326, "s32", 0.01, "A"),
    RegisterSpec("load_l2_current", "Load L2 current", 0x1328, "s32", 0.01, "A"),
    RegisterSpec("load_l3_current", "Load L3 current", 0x132A, "s32", 0.01, "A"),
    RegisterSpec("grid_import_today", "Grid import today", 0x1332, "u32", 0.01, "kWh"),
    RegisterSpec("grid_export_today", "Grid export today", 0x1334, "u32", 0.01, "kWh"),
    RegisterSpec("load_energy_today", "Load energy today", 0x1336, "u32", 0.01, "kWh"),
    RegisterSpec("grid_frequency", "Grid frequency", 0x1338, "u16", 0.01, "Hz"),
    RegisterSpec("backup_voltage", "Backup/load voltage", 0x1350, "u16", 0.1, "V"),
    RegisterSpec("backup_current", "Backup/load current", 0x1351, "s32", 0.01, "A"),
    RegisterSpec("backup_power", "Backup/load power", 0x1353, "s32", 0.1, "W"),
    RegisterSpec("backup_frequency", "Backup/load frequency", 0x1355, "u16", 0.01, "Hz"),
    RegisterSpec("backup_l2_voltage", "Backup L2 voltage", 0x1356, "u16", 0.1, "V"),
    RegisterSpec("backup_l2_current", "Backup L2 current", 0x1357, "s32", 0.01, "A"),
    RegisterSpec("backup_l2_power", "Backup L2 power", 0x1359, "s32", 0.1, "W"),
    RegisterSpec("backup_l3_voltage", "Backup L3 voltage", 0x135B, "u16", 0.1, "V"),
    RegisterSpec("backup_l3_current", "Backup L3 current", 0x135C, "s32", 0.01, "A"),
    RegisterSpec("backup_l3_power", "Backup L3 power", 0x135E, "s32", 0.1, "W"),
    RegisterSpec("backup_energy_today", "Backup/load energy today", 0x1360, "u32", 0.01, "kWh"),
    RegisterSpec("backup_energy_total", "Backup/load energy total", 0x1362, "u32", 0.01, "kWh"),
    # SolarMax/Senergy cloud-validated extension. This is the multifunction
    # GEN connector; depending on configuration it can be generator input,
    # smart-load output, or AC-coupled inverter input.
    RegisterSpec("gen_port_voltage", "GEN port L1 voltage", 0x136A, "u16", 0.1, "V"),
    RegisterSpec("gen_port_current", "GEN port L1 current", 0x136B, "s32", 0.01, "A"),
    RegisterSpec("gen_port_power", "GEN port L1 power", 0x136D, "s32", 0.1, "W"),
    RegisterSpec("gen_port_l2_voltage", "GEN port L2 voltage", 0x136F, "u16", 0.1, "V"),
    RegisterSpec("gen_port_l2_current", "GEN port L2 current", 0x1370, "s32", 0.01, "A"),
    RegisterSpec("gen_port_l2_power", "GEN port L2 power", 0x1372, "s32", 0.1, "W"),
    RegisterSpec("gen_port_l3_voltage", "GEN port L3 voltage", 0x1374, "u16", 0.1, "V"),
    RegisterSpec("gen_port_l3_current", "GEN port L3 current", 0x1375, "s32", 0.01, "A"),
    RegisterSpec("gen_port_l3_power", "GEN port L3 power", 0x1377, "s32", 0.1, "W"),
    RegisterSpec("gen_port_frequency", "GEN port frequency", 0x1379, "u16", 0.01, "Hz"),
    RegisterSpec("gen_port_energy_today", "GEN port energy today", 0x137A, "u32", 0.01, "kWh"),
    RegisterSpec("gen_port_energy_total", "GEN port energy total", 0x137C, "u32", 0.01, "kWh"),
    RegisterSpec("battery_soc", "Battery state of charge", 0x2000, "u16", 1, "%"),
    RegisterSpec("battery_temperature", "Battery temperature", 0x2001, "s16", 1, "°C"),
    RegisterSpec("battery_bms_status", "BMS status code", 0x2002, "u16", 1, ""),
    RegisterSpec("battery_voltage", "Battery voltage", 0x2006, "u16", 0.1, "V"),
    RegisterSpec("battery_current", "Battery current", 0x2007, "s32", 0.01, "A"),
    RegisterSpec("battery_power", "Battery power", 0x2009, "s32", 0.1, "W"),
    RegisterSpec("battery_charge_today", "Battery charge energy today", 0x200B, "u32", 0.01, "kWh"),
    RegisterSpec("battery_charge_total", "Battery charge energy total", 0x200D, "u32", 0.01, "kWh"),
    RegisterSpec("battery_discharge_today", "Battery discharge energy today", 0x200F, "u32", 0.01, "kWh"),
    RegisterSpec("battery_discharge_total", "Battery discharge energy total", 0x2011, "u32", 0.01, "kWh"),
    RegisterSpec("error_4", "Error code 4", 0x2013, "u16", 1, ""),
)


INVERTER_MODES = {
    0x00: "Initial",
    0x01: "Standby",
    0x03: "On-grid",
    0x04: "Off-grid",
    0x05: "Fault",
    0x09: "Shutdown",
}

ERROR_FLAGS = {
    "error_1": (
        "Inverter over DC-bias current", "Inverter relay abnormal", "Remote off",
        "Inverter over temperature", "GFCI abnormal", "PV string reverse",
        "System type error", "Fan abnormal", "DC-link unbalance or under voltage",
        "DC-link over voltage", "Internal communication error", "Software incompatibility",
        "Internal storage error", "Data inconsistency", "Inverter abnormal", "Boost abnormal",
    ),
    "error_2": (
        "Grid over voltage", "Grid under voltage", "Grid absent", "Grid over frequency",
        "Grid under frequency", "PV over voltage", "PV insulation abnormal",
        "Leakage current abnormal", "Inverter in power limit state",
        "Internal power supply abnormal", "PV string abnormal", "PV under voltage",
        "PV irradiation weak", "Grid abnormal", "Arc fault detection",
        "AC moving average voltage high",
    ),
    "error_3": (
        "Reserved", "Logger/display EEPROM failure", "Reserved",
        "Single tracker/PID warning", "AFCI lost", "Data logger lost", "Meter lost",
        "Inverter lost", "Grid neutral abnormal", "Surge protector defective",
        "Parallel ID warning", "Parallel sync warning", "Parallel battery abnormal",
        "Parallel grid abnormal", "Generator voltage abnormal", "Reserved",
    ),
    "error_4": (
        "Battery absent", "Battery over voltage", "Battery under voltage",
        "Battery discharge over current", "Battery over temperature",
        "Battery under temperature", "Neutral/live reversed",
        "Backup output voltage abnormal", "Inverter-BMS communication error",
        "Internal communication loss E-M", "Internal communication loss M-D",
        "DCDC abnormal", "Backup over DC-bias voltage", "Backup short circuit",
        "Backup overload", "Reserved",
    ),
}


# Four requests are enough for the full profile and avoid hammering the bridge
# with a separate request per sensor.
BLOCKS = (
    ("inverter_and_pv", 0x1001, 76),
    ("extended_mppt", 0x1080, 20),
    ("grid_and_load", 0x1300, 57),
    ("backup_and_gen_port", 0x1350, 46),
    ("battery", 0x2000, 20),
)


def _signed(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def decode_value(words: list[int], data_type: str) -> int:
    if data_type == "u16":
        return words[0]
    if data_type == "s16":
        return _signed(words[0], 16)
    combined = (words[0] << 16) | words[1]
    if data_type == "u32":
        return combined
    if data_type == "s32":
        return _signed(combined, 32)
    raise ValueError(f"unsupported data type {data_type}")


def decode_register_map(
    registers: dict[int, int], mppt_count: int | None = None
) -> dict[str, dict[str, Any]]:
    decoded: dict[str, dict[str, Any]] = {}
    for spec in SPECS:
        if (
            mppt_count is not None
            and spec.key.startswith("pv")
            and len(spec.key) > 2
            and spec.key[2].isdigit()
            and int(spec.key[2]) > mppt_count
        ):
            continue
        addresses = range(spec.address, spec.address + spec.count)
        if not all(address in registers for address in addresses):
            continue
        words = [registers[address] for address in addresses]
        raw = decode_value(words, spec.data_type)
        value: int | float = raw * spec.scale
        if isinstance(value, float):
            value = round(value, 4)
        decoded[spec.key] = {
            "name": spec.name,
            "address": spec.address,
            "address_hex": f"0x{spec.address:04X}",
            "data_type": spec.data_type,
            "raw_words": words,
            "raw_value": raw,
            "scale": spec.scale,
            "value": value,
            "unit": spec.unit,
            "category": sensor_category(spec.key),
        }
        if spec.key == "inverter_mode":
            decoded[spec.key]["label"] = INVERTER_MODES.get(raw, f"Unknown mode {raw}")
        if spec.key in ERROR_FLAGS:
            decoded[spec.key]["active_flags"] = [
                description
                for bit, description in enumerate(ERROR_FLAGS[spec.key])
                if raw & (1 << bit) and description != "Reserved"
            ]
    return decoded


def sensor_category(key: str) -> str:
    if key.startswith("pv"):
        return "PV inputs"
    if key.startswith("grid"):
        return "Grid"
    if key.startswith("load"):
        return "Normal Load (grid-only)"
    if key.startswith("backup"):
        return "Backup Load (essential/light)"
    if key.startswith("gen_port"):
        return "GEN smart/high-power load"
    if key.startswith("battery"):
        return "Battery"
    if key.startswith("error") or key in {"inverter_mode", "temperature"}:
        return "Status and diagnostics"
    return "Inverter output and totals"


def _covered_addresses() -> set[int]:
    return {
        address
        for spec in SPECS
        for address in range(spec.address, spec.address + spec.count)
    }


def _ascii(words: list[int]) -> str:
    raw = b"".join(value.to_bytes(2, "big") for value in words)
    return raw.rstrip(b"\0").decode("ascii", errors="replace")


def read_device_and_safe_settings(
    host: str, unit_id: int = 1, timeout: float = 4, interval: float = 1.0
) -> dict[str, Any]:
    """Read identity and non-secret configuration; never read 0x3070 password."""
    host = validate_host(host)
    client = ModbusClient(host, timeout=timeout)
    requests = (
        ("model", 0x1A00, 8),
        ("device_capabilities", 0x1A1C, 95),
        ("hybrid_operating", 0x2100, 34),
        ("clock_and_derating", 0x3000, 6),
        ("serial_bus", 0x303E, 15),
        ("meter", 0x30B0, 5),
    )
    blocks: dict[str, dict[str, Any]] = {}
    maps: dict[str, dict[int, int]] = {}
    for index, (name, address, count) in enumerate(requests):
        result = client.read_holding_registers(address, count, unit_id)
        blocks[name] = result.to_dict()
        maps[name] = {
            address + offset: value
            for offset, value in enumerate(result.registers or [])
        }
        if index != len(requests) - 1:
            time.sleep(max(1.0, interval))

    device = maps["device_capabilities"]
    hybrid = maps["hybrid_operating"]
    clock = maps["clock_and_derating"]
    bus = maps["serial_bus"]
    meter = maps["meter"]
    model_words = blocks["model"].get("registers") or []
    month_day = clock.get(0x3001, 0)
    hour_minute = clock.get(0x3002, 0)
    second = clock.get(0x3003, 0) >> 8
    baud_codes = {1: 2400, 2: 4800, 3: 9600, 4: 14400, 5: 19200}
    meter_types = {
        0: "Unknown", 1: "Carlo Gavazzi EM340", 2: "CHINT DTSU666",
        4: "Lovato DMG210", 6: "Carlo Gavazzi ET112", 8: "CHINT DDSU666",
        9: "Carlo Gavazzi EM530", 10: "Carlo Gavazzi EM540",
    }
    production_types = {
        0: "On-grid", 1: "AC-coupled without smart load",
        2: "Hybrid without smart load", 3: "Hybrid with smart load",
        4: "AC-coupled with smart load",
    }
    work_modes = {
        0: "Self-use", 1: "Feed-in priority", 2: "Time-based control",
        3: "Backup", 4: "Battery discharge",
    }
    battery_types = {
        0: "Unavailable", 1: "Lead-acid", 2: "Pylontech lithium",
        3: "Dyness lithium", 4: "Aobo lithium", 5: "UZ lithium",
        6: "VestMoods lithium", 7: "XinYi lithium",
    }

    def hhmm(value: int | None) -> str | None:
        if value is None:
            return None
        return f"{value >> 8:02d}:{value & 0xFF:02d}"

    info = {
        "model": _ascii(model_words) if model_words else None,
        "master_firmware": _ascii([device.get(a, 0) for a in range(0x1A1C, 0x1A1F)]),
        "slave_firmware": _ascii([device.get(a, 0) for a in range(0x1A26, 0x1A29)]),
        "ems_firmware": _ascii([device.get(a, 0) for a in range(0x1A60, 0x1A63)]),
        "dcdc_firmware": _ascii([device.get(a, 0) for a in range(0x1A6F, 0x1A72)]),
        "mppt_count": device.get(0x1A3B),
        "nominal_voltage_v": device.get(0x1A44, 0) / 10,
        "nominal_frequency_hz": device.get(0x1A45, 0) / 100,
        "nominal_power_w": device.get(0x1A46, 0) + (device.get(0x1A4E, 0) << 16),
        "grid_phase_count": device.get(0x1A48),
        "production_type": production_types.get(device.get(0x1A5A), f"Code {device.get(0x1A5A)}"),
        "hybrid_work_mode": work_modes.get(hybrid.get(0x2100), f"Code {hybrid.get(0x2100)}"),
        "schedule_1_recurrence": {0: "Once", 1: "Every day"}.get(hybrid.get(0x2101)),
        "schedule_1_charge": f"{hhmm(hybrid.get(0x2102))}–{hhmm(hybrid.get(0x2103))}",
        "schedule_1_discharge": f"{hhmm(hybrid.get(0x2104))}–{hhmm(hybrid.get(0x2105))}",
        "battery_type": battery_types.get(hybrid.get(0x2110), f"Code {hybrid.get(0x2110)}"),
        "battery_bms_address": hybrid.get(0x2111),
        "configured_battery_capacity_ah": hybrid.get(0x2112),
        "battery_stop_discharge_voltage_v": hybrid.get(0x2113, 0) / 10,
        "battery_stop_charge_voltage_v": hybrid.get(0x2114, 0) / 10,
        "grid_charge_enabled": bool(hybrid.get(0x2115)),
        "maximum_grid_charge_power_w": hybrid.get(0x2116),
        "grid_charge_end_soc_percent": hybrid.get(0x2117),
        "maximum_charge_power_w": hybrid.get(0x2118),
        "charge_end_soc_percent": hybrid.get(0x2119),
        "maximum_discharge_power_w": hybrid.get(0x211A),
        "discharge_end_soc_percent": hybrid.get(0x211B),
        "off_grid_enabled": bool(hybrid.get(0x211C)),
        "off_grid_nominal_voltage_v": hybrid.get(0x211D, 0) / 10,
        "off_grid_nominal_frequency_hz": hybrid.get(0x211E, 0) / 100,
        "off_grid_start_soc_percent": hybrid.get(0x211F),
        "maximum_discharge_current_a": hybrid.get(0x2120, 0) / 100,
        "maximum_charge_current_a": hybrid.get(0x2121, 0) / 100,
        "inverter_clock": (
            f"{clock.get(0x3000, 0):04d}-{month_day >> 8:02d}-{month_day & 0xFF:02d} "
            f"{hour_minute >> 8:02d}:{hour_minute & 0xFF:02d}:{second:02d}"
        ),
        "dynamic_power_limit_percent": clock.get(0x3005),
        "modbus_address": bus.get(0x303E),
        "rs485_baud": baud_codes.get(bus.get(0x304C), bus.get(0x304C)),
        "meter_address": meter.get(0x30B0),
        "meter_type": meter_types.get(meter.get(0x30B1), f"Code {meter.get(0x30B1)}"),
        "meter_power_direction": {0: "Grid to inverter", 1: "Inverter to grid"}.get(meter.get(0x30B2)),
        "power_limit_source": {
            0: "Disabled", 1: "External device", 2: "External CT", 3: "Digital meter"
        }.get(meter.get(0x30B3)),
        "meter_ct_ratio_code": meter.get(0x30B4),
    }
    return {
        "ok": all(block["ok"] for block in blocks.values()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "unit_id": unit_id,
        "read_only": True,
        "wifi_password_register_read": False,
        "info": info,
        "raw_blocks": blocks,
    }


def read_profile_snapshot(
    host: str,
    unit_id: int = 1,
    timeout: float = 4,
    interval: float = 1.0,
    metadata_cache: dict[str, dict[str, Any]] | None = None,
    metadata_ttl_seconds: float = 300.0,
) -> dict[str, Any]:
    host = validate_host(host)
    if not 0 <= unit_id <= 255:
        raise ValueError("unit_id must be between 0 and 255")
    raw_blocks: list[dict[str, Any]] = []
    register_map: dict[int, int] = {}
    started = time.perf_counter()
    cache_key = f"{host}:{unit_id}"
    cached = metadata_cache.get(cache_key) if metadata_cache is not None else None
    metadata_cached = bool(
        cached
        and time.monotonic() - float(cached.get("stored_monotonic", 0)) < max(1.0, metadata_ttl_seconds)
    )

    # One capability read supplies both MPPT count (0x1A3B) and grid phase
    # count (0x1A48), avoiding another request to the rate-sensitive bridge.
    # Keep one TCP session for the bounded capture instead of repeatedly
    # reconnecting to the small Wi-Fi bridge. The session is closed before the
    # vendor cloud quiet window resumes.
    with ModbusClient(host, timeout=timeout) as client:
        if metadata_cached:
            assert cached is not None
            mppt_count = cached.get("mppt_count")
            phase_count = cached.get("phase_count")
            model = cached.get("model")
            capability_observation = cached.get("capability_observation", {})
            model_observation = cached.get("model_observation", {})
        else:
            capability_result = client.read_holding_registers(0x1A3B, 14, unit_id)
            mppt_count = (
                capability_result.registers[0]
                if capability_result.ok and capability_result.registers
                else None
            )
            phase_count = (
                capability_result.registers[0x1A48 - 0x1A3B]
                if capability_result.ok
                and capability_result.registers
                and len(capability_result.registers) > 0x1A48 - 0x1A3B
                else None
            )
            capability_observation = capability_result.to_dict()
            model = None
            model_observation = {}
            time.sleep(max(1.0, interval))
        selected_blocks = [
            block
            for block in BLOCKS
            if block[0] != "extended_mppt" or mppt_count is None or mppt_count > 4
        ]
        for index, (name, address, count) in enumerate(selected_blocks):
            result = client.read_holding_registers(address, count, unit_id)
            item = result.to_dict()
            item["block_name"] = name
            raw_blocks.append(item)
            if result.ok and result.registers:
                register_map.update(
                    {address + offset: value for offset, value in enumerate(result.registers)}
                )
            if index != len(selected_blocks) - 1:
                time.sleep(max(1.0, interval))
        if not metadata_cached:
            time.sleep(max(1.0, interval))
            model_result = client.read_holding_registers(0x1A00, 8, unit_id)
            model_observation = model_result.to_dict()
            if model_result.ok and model_result.registers:
                model = model_observation["interpretation"]["ascii"].rstrip(".")
            if metadata_cache is not None and capability_result.ok and model_result.ok:
                metadata_cache[cache_key] = {
                    "stored_monotonic": time.monotonic(),
                    "mppt_count": mppt_count,
                    "phase_count": phase_count,
                    "model": model,
                    "capability_observation": capability_observation,
                    "model_observation": model_observation,
                }

    sensors = decode_register_map(register_map, mppt_count=mppt_count)
    presentation = partition_single_phase_sensors(sensors, phase_count, mppt_count)
    covered = _covered_addresses()
    unknown_nonzero = [
        {"address": address, "address_hex": f"0x{address:04X}", "raw_value": value}
        for address, value in sorted(register_map.items())
        if address not in covered and value != 0
    ]
    return {
        "ok": bool(register_map),
        "complete": all(block["ok"] for block in raw_blocks),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "unit_id": unit_id,
        "model": model,
        "profile": "Senergy/APD Modbus v1.2 (SolarMax Onyx family)",
        "read_only": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "sensor_count": len(sensors),
        "documented_sensor_count": len(SPECS),
        "mppt_count": mppt_count,
        "phase_count": phase_count,
        "metadata_cached": metadata_cached,
        "sensors": sensors,
        **presentation,
        "unknown_nonzero_registers": unknown_nonzero,
        "raw_blocks": raw_blocks,
        "model_observation": model_observation,
        "capability_observation": capability_observation,
    }
