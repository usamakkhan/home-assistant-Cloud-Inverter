"""Keep cloud inverter sensor identities stable across integration upgrades."""

from __future__ import annotations

from typing import Iterable


def cloud_sensor_unique_id(entry_id: str, data_key: str) -> str:
    """Scope a portal measurement to one configured inverter."""
    return f"{entry_id}_{data_key}"


def migrate_legacy_sensor_ids(
    registry: object, entries: Iterable[object], entry_id: str, domain: str
) -> None:
    """Change this entry's old global IDs while retaining entity IDs."""
    for registered in entries:
        if (
            registered.domain == "sensor"
            and registered.platform == domain
            and registered.unique_id.startswith("cloud_inverter_")
        ):
            data_key = registered.unique_id.removeprefix("cloud_inverter_")
            registry.async_update_entity(
                registered.entity_id,
                new_unique_id=cloud_sensor_unique_id(entry_id, data_key),
            )
