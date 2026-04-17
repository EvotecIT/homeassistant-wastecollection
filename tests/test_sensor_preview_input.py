import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from custom_components.waste_collection_schedule.const import (  # noqa: E402
    CONF_DATE_TEMPLATE,
)
from custom_components.waste_collection_schedule.sensor_form_helpers import (  # noqa: E402
    apply_template_presets,
)
from custom_components.waste_collection_schedule.sensor_template_presets import (  # noqa: E402
    PL_RELATIVE_TEMPLATE,
)

CONF_VALUE_TEMPLATE = "value_template"


def test_apply_template_presets_moves_selected_presets_into_templates():
    args, errors = apply_template_presets(
        {
            CONF_VALUE_TEMPLATE + "_preset": "in 13 days",
            CONF_DATE_TEMPLATE + "_preset": "14.04.2026",
        }
    )

    assert errors == {}
    assert args[CONF_VALUE_TEMPLATE] == "in {{value.daysTo}} days"
    assert args[CONF_DATE_TEMPLATE] == '{{value.date.strftime("%d.%m.%Y")}}'
    assert CONF_VALUE_TEMPLATE + "_preset" not in args
    assert CONF_DATE_TEMPLATE + "_preset" not in args


def test_apply_template_presets_supports_polish_relative_text():
    args, errors = apply_template_presets(
        {
            CONF_VALUE_TEMPLATE + "_preset": "Dzisiaj / Jutro / za 13 dni",
        }
    )

    assert errors == {}
    assert args[CONF_VALUE_TEMPLATE] == PL_RELATIVE_TEMPLATE


def test_apply_template_presets_rejects_preset_and_custom_value_together():
    _, errors = apply_template_presets(
        {
            CONF_VALUE_TEMPLATE: "{{value.daysTo}}",
            CONF_VALUE_TEMPLATE + "_preset": "in 13 days",
        }
    )

    assert errors == {
        CONF_VALUE_TEMPLATE: "preset_selected",
        CONF_VALUE_TEMPLATE + "_preset": "preset_selected",
    }
