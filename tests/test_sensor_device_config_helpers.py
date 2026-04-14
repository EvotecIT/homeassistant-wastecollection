import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "custom_components",
            "waste_collection_schedule",
        )
    ),
)

from sensor_config_helpers import update_sensor_config_list  # noqa: E402
from sensor_template_presets import (  # noqa: E402
    CUSTOM_OPTION,
    DEFAULT_OPTION,
    VALUE_TEMPLATE_PRESETS,
    get_preset_option,
)

CONF_NAME = "name"
CONF_VALUE_TEMPLATE = "value_template"


def test_get_preset_option_returns_default_for_empty_template():
    assert get_preset_option("", VALUE_TEMPLATE_PRESETS) == DEFAULT_OPTION


def test_get_preset_option_returns_matching_label_for_known_template():
    assert (
        get_preset_option("in {{value.daysTo}} days", VALUE_TEMPLATE_PRESETS)
        == "In .. days"
    )


def test_get_preset_option_returns_custom_for_unknown_template():
    assert get_preset_option("{{value.date}}", VALUE_TEMPLATE_PRESETS) == CUSTOM_OPTION


def test_update_sensor_config_list_updates_only_matching_sensor():
    sensors = [
        {CONF_NAME: "Bio", CONF_VALUE_TEMPLATE: "old"},
        {CONF_NAME: "Paper"},
    ]

    updated = update_sensor_config_list(
        sensors,
        sensor_name="Bio",
        updates={CONF_VALUE_TEMPLATE: "new"},
    )

    assert updated[0][CONF_VALUE_TEMPLATE] == "new"
    assert CONF_VALUE_TEMPLATE not in updated[1]
    assert sensors[0][CONF_VALUE_TEMPLATE] == "old"


def test_update_sensor_config_list_can_remove_keys():
    sensors = [{CONF_NAME: "Bio", CONF_VALUE_TEMPLATE: "old"}]

    updated = update_sensor_config_list(
        sensors,
        sensor_name="Bio",
        removals=(CONF_VALUE_TEMPLATE,),
    )

    assert CONF_VALUE_TEMPLATE not in updated[0]
