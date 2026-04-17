"""Device-page actions for Waste Collection Schedule sensors."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SENSOR_ID, CONF_SENSORS, DOMAIN
from .sensor_config_helpers import (
    build_added_collection_type_sensor_options,
    build_removed_sensor_options,
    build_ui_sensor_device_identifier,
    missing_collection_types,
)
from .wcs_coordinator import WCSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up add/remove action buttons for waste pickup sensors."""
    coordinator: WCSCoordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = entry.options.get(CONF_SENSORS, [])
    entities: list[ButtonEntity] = []

    for collection_type in missing_collection_types(coordinator._aggregator.types, sensors):
        entities.append(CreateWasteSensorButton(entry, coordinator, collection_type))

    for sensor_config in sensors:
        sensor_id = sensor_config.get(CONF_SENSOR_ID)
        sensor_name = sensor_config.get(CONF_NAME, coordinator.shell.calendar_title)
        if not sensor_id:
            continue

        entities.append(RemoveWasteSensorButton(entry, coordinator, sensor_id, sensor_name))

    async_add_entities(entities)


class CreateWasteSensorButton(ButtonEntity):
    """Button that creates a per-type waste pickup sensor."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:plus-circle"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        collection_type: str,
    ) -> None:
        self._entry = entry
        self._collection_type = collection_type
        self._attr_name = f"Create {collection_type} sensor"
        self._attr_unique_id = (
            f"{coordinator.shell.unique_id}_ui_sensor_action_create_{collection_type}"
        )
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Create the waste sensor and let the config entry reload."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=build_added_collection_type_sensor_options(
                self._entry, self._collection_type
            ),
        )


class RemoveWasteSensorButton(ButtonEntity):
    """Button that removes one configured waste pickup sensor."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:trash-can-outline"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WCSCoordinator,
        sensor_id: str,
        sensor_name: str,
    ) -> None:
        self._entry = entry
        self._sensor_id = sensor_id
        self._attr_name = "Remove waste sensor"
        self._attr_unique_id = (
            f"{coordinator.shell.unique_id}_ui_sensor_action_remove_{sensor_id}"
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

    async def async_press(self) -> None:
        """Remove the waste sensor and let the config entry reload."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=build_removed_sensor_options(self._entry, self._sensor_id),
        )
