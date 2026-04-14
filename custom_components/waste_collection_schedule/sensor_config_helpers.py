"""Helpers for device-page configuration entities tied to waste sensors."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

try:
    from .const import CONF_SENSORS
except ImportError:  # pragma: no cover - fallback for direct test imports
    from const import CONF_SENSORS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

CONF_NAME = "name"


def update_sensor_config_list(
    sensors: list[dict[str, Any]],
    sensor_name: str,
    updates: dict[str, Any] | None = None,
    removals: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return a new sensor list with updates applied to one sensor by name."""
    updated_sensors = deepcopy(sensors)
    for sensor in updated_sensors:
        if sensor.get(CONF_NAME) != sensor_name:
            continue

        for key in removals:
            sensor.pop(key, None)

        if updates:
            sensor.update(updates)

        return updated_sensors

    raise KeyError(f"Sensor '{sensor_name}' not found")


def build_updated_options(
    entry: ConfigEntry,
    sensor_name: str,
    updates: dict[str, Any] | None = None,
    removals: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a new config entry options payload for one sensor update."""
    options = deepcopy(dict(entry.options))
    options[CONF_SENSORS] = update_sensor_config_list(
        options.get(CONF_SENSORS, []),
        sensor_name=sensor_name,
        updates=updates,
        removals=removals,
    )
    return options
