"""Dedicated editor panel for managing waste sensors and collection type labels."""

from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_VALUE_TEMPLATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .config_flow import get_preview_sensor_input, validate_sensor_user_input
from .const import (
    CONF_ADD_DAYS_TO,
    CONF_ALIAS,
    CONF_COLLECTION_TYPES,
    CONF_COUNT,
    CONF_CUSTOMIZE,
    CONF_DATE_TEMPLATE,
    CONF_DEDICATED_CALENDAR_TITLE,
    CONF_DETAILS_FORMAT,
    CONF_EVENT_INDEX,
    CONF_ICON,
    CONF_LEADTIME,
    CONF_PICTURE,
    CONF_SENSORS,
    CONF_SHOW,
    CONF_SOURCE_CALENDAR_TITLE,
    CONF_TYPE,
    CONF_USE_DEDICATED_CALENDAR,
    DOMAIN,
)
from .sensor import DetailsFormat, render_sensor_preview
from .sensor_config_helpers import build_replaced_sensor_options
from .sensor_template_presets import DATE_TEMPLATE_PRESETS, VALUE_TEMPLATE_PRESETS
from .waste_collection_schedule import Collection, CollectionAggregator
from .waste_collection_schedule.type_aliases import (
    get_customize_alias,
    get_uncustomized_types,
)

if TYPE_CHECKING:
    from .wcs_coordinator import WCSCoordinator

PANEL_COMPONENT = "custom"
PANEL_NAME = "waste-collection-schedule-editor"
PANEL_URL = f"{DOMAIN}-editor"
PANEL_TITLE = "Waste Schedule Editor"
PANEL_ICON = "mdi:trash-can-edit"
PANEL_STATIC_URL = f"/{DOMAIN}/editor.js"
PANEL_FILE = Path(__file__).parent / "frontend" / "waste-collection-editor.js"
EDITOR_REGISTERED = "_editor_registered"
EDITOR_DATA_COMMAND = f"{DOMAIN}/editor/get_data"
EDITOR_PREVIEW_COMMAND = f"{DOMAIN}/editor/preview_sensor"
EDITOR_SAVE_SENSOR_COMMAND = f"{DOMAIN}/editor/save_sensor"
EDITOR_SAVE_TYPE_COMMAND = f"{DOMAIN}/editor/save_type"


try:
    from homeassistant.components.http import StaticPathConfig

    async def _async_register_static_path(
        hass: HomeAssistant, url_path: str, path: str, cache_headers: bool = False
    ) -> None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_path, path, cache_headers)]
        )

except ImportError:  # pragma: no cover - compatibility fallback

    async def _async_register_static_path(
        hass: HomeAssistant, url_path: str, path: str, cache_headers: bool = False
    ) -> None:
        hass.http.register_static_path(url_path, path, cache_headers)


def _compile_template(
    hass: HomeAssistant, template_value: str | None
) -> Any | None:
    """Compile a stored template string for preview rendering."""
    if not template_value:
        return None
    if hasattr(template_value, "async_render_with_possible_json_value"):
        return template_value

    template = cv.template(template_value)
    template.hass = hass
    return template


def _stringify_preview_value(value: Any) -> str:
    """Serialize preview values for the custom panel."""
    if isinstance(value, Collection):
        return f"{value.date.isoformat()}: {', '.join(value.types)}"
    if isinstance(value, list):
        return ", ".join(_stringify_preview_value(item) for item in value) or "-"
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {_stringify_preview_value(val)}" for key, val in value.items())
    if value in (None, ""):
        return "-"
    return str(value)


def _serialize_preview(
    state: Any, attributes: Mapping[str, Any]
) -> dict[str, Any]:
    """Convert preview output into a frontend-friendly payload."""
    detail_lines = [
        {"label": str(key), "value": _stringify_preview_value(value)}
        for key, value in attributes.items()
    ]
    return {
        "state": _stringify_preview_value(state),
        "detail_lines": detail_lines,
    }


def _sanitize_sensor_config(sensor_config: dict[str, Any]) -> dict[str, Any]:
    """Convert stored sensor config into JSON-friendly values."""
    sanitized = deepcopy(sensor_config)
    details_format = sanitized.get(CONF_DETAILS_FORMAT, DetailsFormat.upcoming.value)
    if isinstance(details_format, DetailsFormat):
        sanitized[CONF_DETAILS_FORMAT] = details_format.value
    return sanitized


def _build_sensor_preview(
    hass: HomeAssistant,
    coordinator: WCSCoordinator,
    sensor_config: dict[str, Any],
) -> dict[str, Any]:
    """Render a live preview for one stored or edited sensor config."""
    value_template = _compile_template(hass, sensor_config.get(CONF_VALUE_TEMPLATE))
    date_template = _compile_template(hass, sensor_config.get(CONF_DATE_TEMPLATE))

    details_format = sensor_config.get(CONF_DETAILS_FORMAT, DetailsFormat.upcoming.value)
    if isinstance(details_format, str):
        details_format = DetailsFormat(details_format)

    state, attributes, _, _ = render_sensor_preview(
        aggregator=CollectionAggregator([coordinator.shell]),
        separator=coordinator.separator,
        day_switch_time=coordinator.day_switch_time,
        details_format=details_format,
        count=sensor_config.get(CONF_COUNT),
        leadtime=sensor_config.get(CONF_LEADTIME),
        collection_types=sensor_config.get(CONF_COLLECTION_TYPES),
        value_template=value_template,
        date_template=date_template,
        add_days_to=sensor_config.get(CONF_ADD_DAYS_TO, False),
        event_index=sensor_config.get(CONF_EVENT_INDEX),
    )
    return _serialize_preview(state, attributes)


def _build_type_rows(
    customize_options: dict[str, dict[str, Any]],
    live_types: list[str],
) -> list[dict[str, Any]]:
    """Build editable collection type rows for the panel."""
    rows: list[dict[str, Any]] = []

    for raw_type, customize in sorted(customize_options.items()):
        rows.append(
            {
                "raw_type": raw_type,
                "display_name": get_customize_alias(customize) or raw_type,
                "customized": True,
                "config": {
                    CONF_TYPE: raw_type,
                    CONF_ALIAS: customize.get(CONF_ALIAS, ""),
                    CONF_SHOW: customize.get(CONF_SHOW, True),
                    CONF_ICON: customize.get(CONF_ICON, ""),
                    CONF_PICTURE: customize.get(CONF_PICTURE, ""),
                    CONF_USE_DEDICATED_CALENDAR: customize.get(
                        CONF_USE_DEDICATED_CALENDAR, False
                    ),
                    CONF_DEDICATED_CALENDAR_TITLE: customize.get(
                        CONF_DEDICATED_CALENDAR_TITLE, ""
                    ),
                },
            }
        )

    for live_type in sorted(get_uncustomized_types(live_types, customize_options)):
        rows.append(
            {
                "raw_type": live_type,
                "display_name": live_type,
                "customized": False,
                "config": {
                    CONF_TYPE: live_type,
                    CONF_ALIAS: "",
                    CONF_SHOW: True,
                    CONF_ICON: "",
                    CONF_PICTURE: "",
                    CONF_USE_DEDICATED_CALENDAR: False,
                    CONF_DEDICATED_CALENDAR_TITLE: "",
                },
            }
        )

    return rows


def _build_entry_payload(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WCSCoordinator,
) -> dict[str, Any]:
    """Serialize one config entry for the custom editor."""
    sensors = [
        {
            "original_name": sensor_config.get(CONF_NAME),
            "config": _sanitize_sensor_config(sensor_config),
            "preview": _build_sensor_preview(hass, coordinator, sensor_config),
        }
        for sensor_config in entry.options.get(CONF_SENSORS, [])
    ]

    live_types = sorted(CollectionAggregator([coordinator.shell]).types)
    customize_options = entry.options.get(CONF_CUSTOMIZE, {})

    return {
        "entry_id": entry.entry_id,
        "title": entry.options.get(CONF_SOURCE_CALENDAR_TITLE)
        or coordinator.shell.calendar_title
        or entry.title,
        "source_name": entry.data.get("name", ""),
        "sensors": sensors,
        "types": _build_type_rows(customize_options, live_types),
    }


async def async_remove_legacy_config_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove the experimental device-page config entities from the registry."""
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.unique_id and "_ui_sensor_config_" in entity_entry.unique_id:
            registry.async_remove(entity_entry.entity_id)


async def async_register_editor_panel(hass: HomeAssistant) -> None:
    """Register the custom editor panel and websocket commands once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(EDITOR_REGISTERED):
        return

    await _async_register_static_path(hass, PANEL_STATIC_URL, str(PANEL_FILE))
    async_register_built_in_panel(
        hass,
        component_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        config={
            "_panel_custom": {
                "name": PANEL_NAME,
                "embed_iframe": False,
                "trust_external": False,
                "js_url": PANEL_STATIC_URL,
            }
        },
        require_admin=True,
    )
    websocket_api.async_register_command(hass, ws_editor_get_data)
    websocket_api.async_register_command(hass, ws_editor_preview_sensor)
    websocket_api.async_register_command(hass, ws_editor_save_sensor)
    websocket_api.async_register_command(hass, ws_editor_save_type)
    domain_data[EDITOR_REGISTERED] = True


def _get_entry_and_coordinator(
    hass: HomeAssistant, entry_id: str
) -> tuple[ConfigEntry, WCSCoordinator]:
    """Look up the target config entry and coordinator."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise HomeAssistantError("Config entry not found")

    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        raise HomeAssistantError("Config entry is not loaded")

    return entry, coordinator


def _normalize_optional_string(value: Any) -> str | None:
    """Convert blank strings to None when persisting editor values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@websocket_api.websocket_command({vol.Required("type"): EDITOR_DATA_COMMAND})
def ws_editor_get_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the data needed to render the dedicated waste editor."""
    connection.require_admin()

    entries = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            continue
        entries.append(_build_entry_payload(hass, entry, coordinator))

    connection.send_result(
        msg["id"],
        {
            "entries": entries,
            "presets": {
                "value_templates": VALUE_TEMPLATE_PRESETS,
                "date_templates": DATE_TEMPLATE_PRESETS,
                "details_formats": [
                    {"value": key.value, "label": key.name.replace("_", " ").title()}
                    for key in DetailsFormat
                ],
            },
            "panel_url": f"/{PANEL_URL}",
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): EDITOR_PREVIEW_COMMAND,
        vol.Required("entry_id"): str,
        vol.Required("sensor"): dict,
    }
)
def ws_editor_preview_sensor(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Render a preview for unsaved sensor editor changes."""
    connection.require_admin()

    _entry, coordinator = _get_entry_and_coordinator(hass, msg["entry_id"])
    sensor_input, errors = get_preview_sensor_input(hass, msg["sensor"])
    if errors:
        raise HomeAssistantError(str(errors))

    preview = _build_sensor_preview(hass, coordinator, sensor_input)
    connection.send_result(msg["id"], preview)


@websocket_api.websocket_command(
    {
        vol.Required("type"): EDITOR_SAVE_SENSOR_COMMAND,
        vol.Required("entry_id"): str,
        vol.Required("original_name"): str,
        vol.Required("sensor"): dict,
    }
)
def ws_editor_save_sensor(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist one edited sensor definition from the custom editor."""
    connection.require_admin()

    entry, _coordinator = _get_entry_and_coordinator(hass, msg["entry_id"])
    sensor_input = deepcopy(msg["sensor"])

    existing_sensors = [
        sensor
        for sensor in entry.options.get(CONF_SENSORS, [])
        if sensor.get(CONF_NAME) != msg["original_name"]
    ]
    args, errors = validate_sensor_user_input(sensor_input, existing_sensors)
    if errors:
        raise HomeAssistantError(str(errors))

    hass.config_entries.async_update_entry(
        entry,
        options=build_replaced_sensor_options(
            entry,
            original_sensor_name=msg["original_name"],
            replacement=args,
        ),
    )
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): EDITOR_SAVE_TYPE_COMMAND,
        vol.Required("entry_id"): str,
        vol.Required("waste_type"): str,
        vol.Required("customize"): dict,
    }
)
def ws_editor_save_type(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist one edited collection type customization from the custom editor."""
    connection.require_admin()

    entry, _coordinator = _get_entry_and_coordinator(hass, msg["entry_id"])
    customize = deepcopy(entry.options.get(CONF_CUSTOMIZE, {}))
    waste_type = msg["waste_type"]
    current = deepcopy(customize.get(waste_type, {}))
    incoming = msg["customize"]

    alias = _normalize_optional_string(incoming.get(CONF_ALIAS))
    if alias is None:
        current.pop(CONF_ALIAS, None)
    else:
        current[CONF_ALIAS] = alias

    current[CONF_SHOW] = bool(incoming.get(CONF_SHOW, True))

    icon = _normalize_optional_string(incoming.get(CONF_ICON))
    if icon is None:
        current.pop(CONF_ICON, None)
    else:
        current[CONF_ICON] = icon

    picture = _normalize_optional_string(incoming.get(CONF_PICTURE))
    if picture is None:
        current.pop(CONF_PICTURE, None)
    else:
        current[CONF_PICTURE] = picture

    current[CONF_USE_DEDICATED_CALENDAR] = bool(
        incoming.get(CONF_USE_DEDICATED_CALENDAR, False)
    )

    dedicated_calendar_title = _normalize_optional_string(
        incoming.get(CONF_DEDICATED_CALENDAR_TITLE)
    )
    if dedicated_calendar_title is None:
        current.pop(CONF_DEDICATED_CALENDAR_TITLE, None)
    else:
        current[CONF_DEDICATED_CALENDAR_TITLE] = dedicated_calendar_title

    if (
        not current.get(CONF_ALIAS)
        and current.get(CONF_SHOW, True)
        and not current.get(CONF_ICON)
        and not current.get(CONF_PICTURE)
        and not current.get(CONF_USE_DEDICATED_CALENDAR, False)
        and not current.get(CONF_DEDICATED_CALENDAR_TITLE)
    ):
        customize.pop(waste_type, None)
    else:
        customize[waste_type] = current

    options = deepcopy(dict(entry.options))
    options[CONF_CUSTOMIZE] = customize
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"saved": True})
