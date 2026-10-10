from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .direct_coordinator import DirectSolarMaxCoordinator
from .direct_config import direct_unique_id
from .numeric import combine_total_energy, split_direct_battery_power, split_grid_power
from .const import (
    CONF_HOST, CONF_PORT, CONF_UNIT_ID, DEFAULT_DIRECT_UNIT_ID,
)


@dataclass(frozen=True, kw_only=True)
class SolarMaxSensorDescription(SensorEntityDescription):
    source_key: str
    value_field: str = "value"
    battery_direction: str | None = None
    grid_direction: str | None = None


def power(key: str, name: str) -> SolarMaxSensorDescription:
    return SolarMaxSensorDescription(
        key=key,
        source_key=key,
        name=name,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    )


def measurement(key: str, name: str, unit, device_class) -> SolarMaxSensorDescription:
    return SolarMaxSensorDescription(
        key=key,
        source_key=key,
        name=name,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
    )


def energy(
    key: str,
    name: str,
    unit=UnitOfEnergy.KILO_WATT_HOUR,
) -> SolarMaxSensorDescription:
    return SolarMaxSensorDescription(
        key=key,
        source_key=key,
        name=name,
        native_unit_of_measurement=unit,
        device_class=SensorDeviceClass.ENERGY,
        # Daily counters reset to zero; Home Assistant must treat that as a new
        # meter cycle instead of subtracting yesterday's production.
        state_class=SensorStateClass.TOTAL_INCREASING,
    )


SENSORS = (
    power("pv_power", "Instantaneous Solar Production"),
    measurement("pv1_voltage", "PV1 voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("pv1_current", "PV1 current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    power("pv1_power", "PV1 power"),
    measurement("pv2_voltage", "PV2 voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("pv2_current", "PV2 current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    power("pv2_power", "PV2 power"),
    power("pv_peak_today", "PV peak power today"),
    energy("today_energy", "Solar energy today", UnitOfEnergy.WATT_HOUR),
    energy("total_energy", "Solar energy total"),
    SolarMaxSensorDescription(key="generation_hours", source_key="generation_hours", name="Generation time", native_unit_of_measurement=UnitOfTime.HOURS, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.TOTAL_INCREASING),
    SolarMaxSensorDescription(key="inverter_mode", source_key="inverter_mode", name="Inverter mode", value_field="label"),
    measurement("temperature", "Inverter temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    power("grid_power", "Grid power"),
    SolarMaxSensorDescription(key="grid_import_power", source_key="grid_power", name="Instantaneous Power Import", grid_direction="import", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT),
    SolarMaxSensorDescription(key="grid_export_power", source_key="grid_power", name="Instantaneous Power Export", grid_direction="export", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT),
    measurement("grid_voltage", "Grid voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("grid_current", "Grid current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("grid_frequency", "Grid frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("grid_import_today", "Grid imported energy today"),
    energy("grid_import_total", "Grid imported energy total"),
    energy("grid_export_today", "Grid exported energy today"),
    energy("grid_export_total", "Grid exported energy total"),
    power("battery_power", "Instantaneous Battery Power"),
    SolarMaxSensorDescription(key="battery_charging_power", source_key="battery_power", name="Instantaneous Battery Charging Power", battery_direction="charging", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT),
    SolarMaxSensorDescription(key="battery_discharging_power", source_key="battery_power", name="Instantaneous Battery Discharging Power", battery_direction="discharging", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT),
    SolarMaxSensorDescription(key="battery_soc", source_key="battery_soc", name="Battery state of charge", native_unit_of_measurement=PERCENTAGE, device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT),
    measurement("battery_voltage", "Battery voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("battery_current", "Battery current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("battery_temperature", "Battery temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    energy("battery_charge_today", "Battery charged energy today"),
    energy("battery_charge_total", "Battery charged energy total"),
    energy("battery_discharge_today", "Battery discharged energy today"),
    energy("battery_discharge_total", "Battery discharged energy total"),
    power("backup_power", "Backup Load power"),
    measurement("backup_voltage", "Backup Load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("backup_current", "Backup Load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("backup_frequency", "Backup Load frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("backup_energy_today", "Backup Load energy today"),
    energy("backup_energy_total", "Backup Load energy total"),
    power("gen_port_power", "GEN smart-load power"),
    measurement("gen_port_voltage", "GEN smart-load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("gen_port_current", "GEN smart-load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("gen_port_frequency", "GEN smart-load frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("gen_port_energy_today", "GEN smart-load energy today"),
    energy("gen_port_energy_total", "GEN smart-load energy total"),
    power("load_power", "Normal Load power"),
    measurement("load_voltage", "Normal Load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("load_current", "Normal Load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    energy("load_energy_today", "Normal Load energy today"),
    energy("load_energy_total", "Normal Load energy total"),
    SolarMaxSensorDescription(
        key="last_value_change",
        source_key="last_value_change",
        name="Last local value change",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DirectSolarMaxCoordinator = entry.runtime_data
    async_add_entities(SolarMaxSensor(coordinator, entry, description) for description in SENSORS)


class SolarMaxSensor(CoordinatorEntity[DirectSolarMaxCoordinator], SensorEntity):
    """A sensor backed by Home Assistant's direct Modbus capture."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DirectSolarMaxCoordinator,
        entry: ConfigEntry,
        description: SolarMaxSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self):
        if self.entity_description.key == "last_value_change":
            return self.coordinator.health.last_value_change
        sensor = self.coordinator.data.get("sensors", {}).get(self.entity_description.source_key)
        if sensor is None:
            return None
        value = sensor.get(self.entity_description.value_field)
        if self.entity_description.key == "total_energy":
            remainder = self.coordinator.data.get("sensors", {}).get("total_energy_wh_remainder", {}).get("value")
            return combine_total_energy(value, remainder)
        if self.entity_description.battery_direction:
            charging, discharging = split_direct_battery_power(value)
            return charging if self.entity_description.battery_direction == "charging" else discharging
        if self.entity_description.grid_direction:
            import_power, export_power = split_grid_power(value)
            return import_power if self.entity_description.grid_direction == "import" else export_power
        return value

    @property
    def available(self) -> bool:
        if self.entity_description.key == "last_value_change":
            return super().available and self.native_value is not None
        return (
            super().available
            and bool(self.coordinator.data.get("available"))
            and self.entity_description.source_key in self.coordinator.data.get("sensors", {})
            and self.native_value is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        model = self.coordinator.data.get("model") or "PV9000"
        # Keep the v1.3.0 device identity stable across option changes.
        unit_id = int(self.entry.data.get(CONF_UNIT_ID, DEFAULT_DIRECT_UNIT_ID))
        identity = direct_unique_id(
            self.entry.data[CONF_HOST], self.entry.data[CONF_PORT], unit_id
        )
        return DeviceInfo(
            identifiers={(DOMAIN, identity)},
            name="Solar Touch Direct",
            manufacturer="SolarMax / Senergy",
            model=model,
        )
