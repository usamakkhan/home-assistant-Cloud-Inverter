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
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .local_coordinator import SolarMaxCoordinator
from .direct_coordinator import DirectSolarMaxCoordinator
from .const import CONF_SOURCE, SOURCE_DIRECT


@dataclass(frozen=True, kw_only=True)
class SolarMaxSensorDescription(SensorEntityDescription):
    source_key: str
    value_field: str = "value"


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
    *,
    lifetime: bool = True,
) -> SolarMaxSensorDescription:
    return SolarMaxSensorDescription(
        key=key,
        source_key=key,
        name=name,
        native_unit_of_measurement=unit,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING if lifetime else SensorStateClass.TOTAL,
    )


SENSORS = (
    power("pv_power", "Solar power"),
    measurement("pv1_voltage", "PV1 voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("pv1_current", "PV1 current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    power("pv1_power", "PV1 power"),
    measurement("pv2_voltage", "PV2 voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("pv2_current", "PV2 current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    power("pv2_power", "PV2 power"),
    power("pv_peak_today", "PV peak power today"),
    energy("today_energy", "Solar energy today", UnitOfEnergy.WATT_HOUR, lifetime=False),
    energy("total_energy", "Solar energy total"),
    SolarMaxSensorDescription(key="generation_hours", source_key="generation_hours", name="Generation time", native_unit_of_measurement=UnitOfTime.HOURS, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.TOTAL_INCREASING),
    SolarMaxSensorDescription(key="inverter_mode", source_key="inverter_mode", name="Inverter mode", value_field="label"),
    measurement("temperature", "Inverter temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    power("grid_power", "Grid power"),
    measurement("grid_voltage", "Grid voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("grid_current", "Grid current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("grid_frequency", "Grid frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("grid_import_today", "Grid imported energy today", lifetime=False),
    energy("grid_import_total", "Grid imported energy total"),
    energy("grid_export_today", "Grid exported energy today", lifetime=False),
    energy("grid_export_total", "Grid exported energy total"),
    power("battery_power", "Battery power"),
    SolarMaxSensorDescription(key="battery_soc", source_key="battery_soc", name="Battery state of charge", native_unit_of_measurement=PERCENTAGE, device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT),
    measurement("battery_voltage", "Battery voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("battery_current", "Battery current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("battery_temperature", "Battery temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    energy("battery_charge_today", "Battery charged energy today", lifetime=False),
    energy("battery_charge_total", "Battery charged energy total"),
    energy("battery_discharge_today", "Battery discharged energy today", lifetime=False),
    energy("battery_discharge_total", "Battery discharged energy total"),
    power("backup_power", "Backup Load power"),
    measurement("backup_voltage", "Backup Load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("backup_current", "Backup Load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("backup_frequency", "Backup Load frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("backup_energy_today", "Backup Load energy today", lifetime=False),
    energy("backup_energy_total", "Backup Load energy total"),
    power("gen_port_power", "GEN smart-load power"),
    measurement("gen_port_voltage", "GEN smart-load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("gen_port_current", "GEN smart-load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    measurement("gen_port_frequency", "GEN smart-load frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    energy("gen_port_energy_today", "GEN smart-load energy today", lifetime=False),
    energy("gen_port_energy_total", "GEN smart-load energy total"),
    power("load_power", "Normal Load power"),
    measurement("load_voltage", "Normal Load voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    measurement("load_current", "Normal Load current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    energy("load_energy_today", "Normal Load energy today", lifetime=False),
    energy("load_energy_total", "Normal Load energy total"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: SolarMaxCoordinator | DirectSolarMaxCoordinator = entry.runtime_data
    async_add_entities(SolarMaxSensor(coordinator, entry, description) for description in SENSORS)


class SolarMaxSensor(CoordinatorEntity[SolarMaxCoordinator], SensorEntity):
    """A sensor backed by the analyzer's cached snapshot."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarMaxCoordinator | DirectSolarMaxCoordinator,
        entry: ConfigEntry,
        description: SolarMaxSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self):
        sensor = self.coordinator.data.get("sensors", {}).get(self.entity_description.source_key)
        return None if sensor is None else sensor.get(self.entity_description.value_field)

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(self.coordinator.data.get("available"))
            and self.entity_description.source_key in self.coordinator.data.get("sensors", {})
        )

    @property
    def device_info(self) -> DeviceInfo:
        model = self.coordinator.data.get("model") or "PV9000"
        direct = self.entry.data.get(CONF_SOURCE) == SOURCE_DIRECT
        identity = (
            f"direct:{self.coordinator.host}:{self.coordinator.port}"
            if direct else f"local:{self.coordinator.base_url}"
        )
        info = DeviceInfo(
            identifiers={(DOMAIN, identity)},
            name="Cloud Inverter Direct" if direct else "Cloud Inverter Local",
            manufacturer="SolarMax / Senergy",
            model=model,
        )
        if not direct:
            info["configuration_url"] = self.coordinator.base_url
        return info
