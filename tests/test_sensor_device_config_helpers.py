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

from sensor_config_helpers import (  # noqa: E402
    build_legacy_ui_sensor_unique_id,
    build_stable_ui_sensor_unique_id,
    build_ui_sensor_device_identifier,
    build_ui_sensor_unique_id,
    ensure_sensor_ids,
    iter_ui_sensor_unique_id_migrations,
    replace_sensor_config,
    update_sensor_config_list,
    update_sensor_config_list_by_id,
)
from sensor_template_presets import (  # noqa: E402
    CUSTOM_OPTION,
    DEFAULT_OPTION,
    VALUE_TEMPLATE_PRESETS,
    get_preset_option,
)

CONF_NAME = "name"
CONF_SENSOR_ID = "sensor_id"
CONF_VALUE_TEMPLATE = "value_template"


def test_get_preset_option_returns_default_for_empty_template():
    assert get_preset_option("", VALUE_TEMPLATE_PRESETS) == DEFAULT_OPTION


def test_get_preset_option_returns_matching_label_for_known_template():
    assert (
        get_preset_option("in {{value.daysTo}} days", VALUE_TEMPLATE_PRESETS)
        == "in 13 days"
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


def test_update_sensor_config_list_by_id_updates_only_matching_sensor():
    sensors = [
        {CONF_NAME: "Bio", CONF_SENSOR_ID: "bio-id"},
        {CONF_NAME: "Paper", CONF_SENSOR_ID: "paper-id"},
    ]

    updated = update_sensor_config_list_by_id(
        sensors,
        sensor_id="paper-id",
        updates={CONF_VALUE_TEMPLATE: "new"},
    )

    assert CONF_VALUE_TEMPLATE not in updated[0]
    assert updated[1][CONF_VALUE_TEMPLATE] == "new"
    assert CONF_VALUE_TEMPLATE not in sensors[1]


def test_replace_sensor_config_replaces_only_target_sensor():
    sensors = [
        {CONF_NAME: "Bio", CONF_VALUE_TEMPLATE: "old"},
        {CONF_NAME: "Paper"},
    ]

    updated = replace_sensor_config(
        sensors,
        original_sensor_name="Bio",
        replacement={CONF_NAME: "Bio Friendly", CONF_VALUE_TEMPLATE: "new"},
    )

    assert updated[0][CONF_NAME] == "Bio Friendly"
    assert updated[0][CONF_VALUE_TEMPLATE] == "new"
    assert updated[1][CONF_NAME] == "Paper"
    assert sensors[0][CONF_NAME] == "Bio"


def test_ensure_sensor_ids_only_fills_missing_ids():
    sensors = [
        {CONF_NAME: "Bio"},
        {CONF_NAME: "Paper", CONF_SENSOR_ID: "keep-me"},
    ]

    values = iter(["generated-id"])
    updated, changed = ensure_sensor_ids(sensors, id_factory=lambda: next(values))

    assert changed is True
    assert updated[0][CONF_SENSOR_ID] == "generated-id"
    assert updated[1][CONF_SENSOR_ID] == "keep-me"
    assert CONF_SENSOR_ID not in sensors[0]


def test_build_ui_sensor_unique_id_uses_stable_id_when_available():
    assert (
        build_ui_sensor_unique_id("source-1", "Bio", "sensor-1")
        == "source-1_ui_sensor_sensor-1"
    )


def test_build_ui_sensor_unique_id_falls_back_to_legacy_name():
    assert build_ui_sensor_unique_id("source-1", "Bio", None) == (
        "source-1_ui_sensor_Bio"
    )


def test_build_ui_sensor_device_identifier_uses_stable_sensor_id():
    assert (
        build_ui_sensor_device_identifier("source-1", "sensor-1")
        == "source-1_sensor_sensor-1"
    )


def test_iter_ui_sensor_unique_id_migrations_returns_name_to_id_pairs():
    sensors = [
        {CONF_NAME: "Bio", CONF_SENSOR_ID: "bio-id"},
        {CONF_NAME: "Paper"},
        {CONF_SENSOR_ID: "missing-name"},
    ]

    assert iter_ui_sensor_unique_id_migrations("source-1", sensors) == [
        (
            build_legacy_ui_sensor_unique_id("source-1", "Bio"),
            build_stable_ui_sensor_unique_id("source-1", "bio-id"),
        )
    ]
