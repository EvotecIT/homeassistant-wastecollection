"""Helpers for normalizing sensor form input without Home Assistant runtime."""

from typing import Any

try:
    from homeassistant.const import CONF_VALUE_TEMPLATE

    from .const import CONF_DATE_TEMPLATE
    from .sensor_template_presets import DATE_TEMPLATE_PRESETS, get_all_value_template_presets
except ImportError:  # pragma: no cover - fallback for direct test imports
    from const import CONF_DATE_TEMPLATE
    from sensor_template_presets import DATE_TEMPLATE_PRESETS, get_all_value_template_presets

    CONF_VALUE_TEMPLATE = "value_template"


def apply_template_presets(sensor_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Move selected preset values into their matching template fields."""
    errors: dict[str, str] = {}
    args = sensor_input.copy()
    preset_maps = {
        CONF_VALUE_TEMPLATE: get_all_value_template_presets(),
        CONF_DATE_TEMPLATE: DATE_TEMPLATE_PRESETS,
    }

    for key in [CONF_VALUE_TEMPLATE, CONF_DATE_TEMPLATE]:
        preset_key = key + "_preset"
        if sensor_input.get(preset_key):
            if sensor_input[preset_key] == "Custom":
                args.pop(preset_key, None)
                continue
            if sensor_input.get(key):
                errors[key] = "preset_selected"
                errors[preset_key] = "preset_selected"
                continue
            if sensor_input[preset_key] == "Default":
                args[key] = ""
            else:
                args[key] = preset_maps[key].get(
                    sensor_input[preset_key], sensor_input[preset_key]
                )
        args.pop(preset_key, None)

    return args, errors
