"""Device-page configuration text entities for Waste Collection Schedule sensors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_VALUE_TEMPLATE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DATE_TEMPLATE, CONF_SENSORS, DOMAIN
from .init_ui import WCSCoordinator
from .sensor_config_helpers import build_updated_options


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up configuration text entities for each configured waste sensor."""
    coordinator: WCSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[TextEntity] = []

    for sensor_config in entry.options.get(CONF_SENSORS, []):
        sensor_name = sensor_config[CONF_NAME]
        entities.extend(
            [
                WasteSensorTemplateText(
                    entry,
                    coordinator,
                    sensor_name,
                    key=CONF_VALUE_TEMPLATE,
                    label="custom state text",
                    icon="mdi:code-braces",
                ),
                WasteSensorTemplateText(
                    entry,
                    coordinator,
                    sensor_name,
                    key=CONF_DATE_TEMPLATE,
                    label="date display text",
                    icon="mdi:calendar-edit",
                ),
            ]
        )

    async_add_entities(entities)


class WasteSensorTemplateText(TextEntity):
    """Text entity for editing a waste sensor template directly from the device page."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        sensor_name: str,
        key: str,
        label: str,
        icon: str,
    ) -> None:
        self._entry = entry
        self._sensor_name = sensor_name
        self._key = key
        self._attr_name = f"{sensor_name} {label}"
        self._attr_unique_id = (
            f"{coordinator.shell.unique_id}_ui_sensor_config_{sensor_name}_{key}_text"
        )
        self._attr_device_info = coordinator.device_info
        self._attr_icon = icon

    @property
    def sensor_config(self) -> Mapping[str, Any]:
        """Return the latest stored configuration for this sensor."""
        return next(
            sensor
            for sensor in self._entry.options.get(CONF_SENSORS, [])
            if sensor.get(CONF_NAME) == self._sensor_name
        )

    @property
    def native_value(self) -> str:
        """Return the current template string."""
        return str(self.sensor_config.get(self._key, ""))

    async def async_set_value(self, value: str) -> None:
        """Persist the edited template string."""
        if value.strip():
            options = build_updated_options(
                self._entry,
                sensor_name=self._sensor_name,
                updates={self._key: value},
            )
        else:
            options = build_updated_options(
                self._entry,
                sensor_name=self._sensor_name,
                removals=(self._key,),
            )

        self.hass.config_entries.async_update_entry(self._entry, options=options)
