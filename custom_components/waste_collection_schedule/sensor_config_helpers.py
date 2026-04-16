"""Helpers for device-page configuration entities tied to waste sensors."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from uuid import uuid4

try:
    from .const import CONF_SENSOR_ID, CONF_SENSORS
except ImportError:  # pragma: no cover - fallback for direct test imports
    from const import CONF_SENSOR_ID, CONF_SENSORS

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


def ensure_sensor_ids(
    sensors: list[dict[str, Any]],
    id_factory: Callable[[], str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return sensors with stable IDs ensured for every configured sensor."""
    updated_sensors = deepcopy(sensors)
    changed = False
    factory = id_factory or (lambda: uuid4().hex)

    for sensor in updated_sensors:
        if sensor.get(CONF_SENSOR_ID):
            continue
        sensor[CONF_SENSOR_ID] = factory()
        changed = True

    return updated_sensors, changed


def replace_sensor_config(
    sensors: list[dict[str, Any]],
    original_sensor_name: str,
    replacement: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return a new sensor list with one sensor fully replaced by name."""
    updated_sensors = deepcopy(sensors)
    for idx, sensor in enumerate(updated_sensors):
        if sensor.get(CONF_NAME) != original_sensor_name:
            continue

        updated_sensors[idx] = deepcopy(replacement)
        return updated_sensors

    raise KeyError(f"Sensor '{original_sensor_name}' not found")


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


def build_replaced_sensor_options(
    entry: ConfigEntry,
    original_sensor_name: str,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    """Build a new config entry options payload with one sensor fully replaced."""
    options = deepcopy(dict(entry.options))
    options[CONF_SENSORS] = replace_sensor_config(
        options.get(CONF_SENSORS, []),
        original_sensor_name=original_sensor_name,
        replacement=replacement,
    )
    return options
