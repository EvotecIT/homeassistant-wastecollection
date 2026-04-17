"""Device-page configuration selects for Waste Collection Schedule sensors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_VALUE_TEMPLATE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_DATE_TEMPLATE,
    CONF_DETAILS_FORMAT,
    CONF_SENSOR_ID,
    CONF_SENSORS,
    DOMAIN,
)
from .sensor import DetailsFormat
from .sensor_config_helpers import (
    build_ui_sensor_device_identifier,
    build_updated_options_by_sensor_id,
)
from .sensor_template_presets import (
    CUSTOM_OPTION,
    DATE_TEMPLATE_PRESETS,
    DEFAULT_OPTION,
    VALUE_TEMPLATE_PRESETS,
    get_preset_option,
)
from .wcs_coordinator import WCSCoordinator

LAYOUT_LABELS = {
    DetailsFormat.upcoming.value: "Upcoming list",
    DetailsFormat.appointment_types.value: "By collection type",
    DetailsFormat.generic.value: "All attributes",
    DetailsFormat.hidden.value: "Hide details",
}
LAYOUT_VALUES = {label: value for value, label in LAYOUT_LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up quick configuration selects for each configured waste sensor."""
    coordinator: WCSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []

    for sensor_config in entry.options.get(CONF_SENSORS, []):
        sensor_id = sensor_config.get(CONF_SENSOR_ID)
        sensor_name = sensor_config.get(CONF_NAME, coordinator.shell.calendar_title)
        if not sensor_id:
            continue

        entities.extend(
            [
                WasteSensorLayoutSelect(entry, coordinator, sensor_id, sensor_name),
                WasteSensorTemplatePresetSelect(
                    entry,
                    coordinator,
                    sensor_id,
                    sensor_name,
                    key=CONF_VALUE_TEMPLATE,
                    key_suffix="state_preset",
                    label="State text",
                    presets=VALUE_TEMPLATE_PRESETS,
                    icon="mdi:format-text",
                ),
                WasteSensorTemplatePresetSelect(
                    entry,
                    coordinator,
                    sensor_id,
                    sensor_name,
                    key=CONF_DATE_TEMPLATE,
                    key_suffix="date_preset",
                    label="Date format",
                    presets=DATE_TEMPLATE_PRESETS,
                    icon="mdi:calendar-text",
                ),
            ]
        )

    async_add_entities(entities)


class WasteSensorConfigEntity:
    """Common behavior for per-sensor configuration entities."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        sensor_id: str,
        sensor_name: str,
        key_suffix: str,
        display_name: str,
        icon: str | None = None,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._sensor_id = sensor_id
        self._attr_name = display_name
        self._attr_unique_id = (
            f"{coordinator.shell.unique_id}_ui_sensor_control_{sensor_id}_{key_suffix}"
        )
        device_identifier = build_ui_sensor_device_identifier(
            coordinator.shell.unique_id, sensor_id
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            manufacturer=coordinator.shell.title,
            model="Waste Pickup Sensor",
            name=sensor_name,
            via_device=(DOMAIN, coordinator.shell.unique_id),
        )
        if icon:
            self._attr_icon = icon

    @property
    def sensor_config(self) -> Mapping[str, Any]:
        """Return the latest stored configuration for this sensor."""
        return next(
            sensor
            for sensor in self._entry.options.get(CONF_SENSORS, [])
            if sensor.get(CONF_SENSOR_ID) == self._sensor_id
        )

    async def _async_save(
        self,
        updates: dict[str, Any] | None = None,
        removals: tuple[str, ...] = (),
    ) -> None:
        """Persist the updated sensor configuration."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=build_updated_options_by_sensor_id(
                self._entry,
                sensor_id=self._sensor_id,
                updates=updates,
                removals=removals,
            ),
        )


class WasteSensorLayoutSelect(WasteSensorConfigEntity, SelectEntity):
    """Select for choosing the more-info layout of a waste sensor."""

    _attr_options = list(LAYOUT_VALUES.keys())

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        sensor_id: str,
        sensor_name: str,
    ) -> None:
        super().__init__(
            entry,
            coordinator,
            sensor_id,
            sensor_name,
            key_suffix="details_format",
            display_name="Display mode",
            icon="mdi:view-list",
        )

    @property
    def current_option(self) -> str | None:
        """Return the current display mode label."""
        current = self.sensor_config.get(
            CONF_DETAILS_FORMAT, DetailsFormat.upcoming.value
        )
        if isinstance(current, DetailsFormat):
            current = current.value
        return LAYOUT_LABELS.get(str(current), "Upcoming list")

    async def async_select_option(self, option: str) -> None:
        """Persist the selected display mode."""
        await self._async_save(updates={CONF_DETAILS_FORMAT: LAYOUT_VALUES[option]})


class WasteSensorTemplatePresetSelect(WasteSensorConfigEntity, SelectEntity):
    """Select for applying a preset template to a waste sensor field."""

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        sensor_id: str,
        sensor_name: str,
        key: str,
        key_suffix: str,
        label: str,
        presets: dict[str, str],
        icon: str,
    ) -> None:
        super().__init__(
            entry,
            coordinator,
            sensor_id,
            sensor_name,
            key_suffix=key_suffix,
            display_name=label,
            icon=icon,
        )
        self._key = key
        self._presets = presets
        self._attr_options = [DEFAULT_OPTION, *presets.keys(), CUSTOM_OPTION]

    @property
    def current_option(self) -> str | None:
        """Return the current matching preset, default, or custom."""
        return get_preset_option(self.sensor_config.get(self._key), self._presets)

    async def async_select_option(self, option: str) -> None:
        """Apply a preset to the underlying sensor option."""
        if option == CUSTOM_OPTION:
            return
        if option == DEFAULT_OPTION:
            await self._async_save(removals=(self._key,))
            return
        await self._async_save(updates={self._key: self._presets[option]})
