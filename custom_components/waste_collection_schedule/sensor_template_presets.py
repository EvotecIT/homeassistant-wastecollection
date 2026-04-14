"""Shared preset definitions for waste sensor display templates."""

from collections.abc import Mapping

DEFAULT_OPTION = "Default"
CUSTOM_OPTION = "Custom"

VALUE_TEMPLATE_PRESETS: dict[str, str] = {
    "In .. days": "in {{value.daysTo}} days",
    ".. in .. days": '{{value.types|join(", ")}} in {{value.daysTo}} days',
    "Numeric daysTo": "{{value.daysTo}}",
    "Today / Tomorrow / In .. days": "{% if value.daysTo == 0 %}Today{% elif value.daysTo == 1 %}Tomorrow{% else %}in {{value.daysTo}} days{% endif %}",
    "On weekday, dd.mm.yyyy": 'on {{value.date.strftime("%a")}}, {{value.date.strftime("%d.%m.%Y")}}',
    "On weekday, yyyy-mm-dd": 'on {{value.date.strftime("%a")}}, {{value.date.strftime("%Y-%m-%d")}}',
    "Next collection types": '{{value.types|join(", ")}}',
}

DATE_TEMPLATE_PRESETS: dict[str, str] = {
    "DD.MM.YYYY": '{{value.date.strftime("%d.%m.%Y")}}',
    "Weekday, DD.MM.YYYY": '{{value.date.strftime("%a, %d.%m.%Y")}}',
    "MM/DD/YYYY": '{{value.date.strftime("%m/%d/%Y")}}',
    "Weekday, MM/DD/YYYY": '{{value.date.strftime("%a, %m/%d/%Y")}}',
    "YYYY-MM-DD": '{{value.date.strftime("%Y-%m-%d")}}',
    "Weekday, YYYY-MM-DD": '{{value.date.strftime("%a, %Y-%m-%d")}}',
}


def get_preset_option(template: str | None, presets: Mapping[str, str]) -> str:
    """Return the matching preset label for a stored template string."""
    if not template:
        return DEFAULT_OPTION

    for label, preset_template in presets.items():
        if template == preset_template:
            return label

    return CUSTOM_OPTION
