"""Shared preset definitions for waste sensor display templates."""

from collections.abc import Mapping

DEFAULT_OPTION = "Default"
CUSTOM_OPTION = "Custom"

VALUE_TEMPLATE_PRESETS: dict[str, str] = {
    "in 13 days": "in {{value.daysTo}} days",
    "Bio in 13 days": '{{value.types|join(", ")}} in {{value.daysTo}} days',
    "13": "{{value.daysTo}}",
    "Today / Tomorrow / in 13 days": "{% if value.daysTo == 0 %}Today{% elif value.daysTo == 1 %}Tomorrow{% else %}in {{value.daysTo}} days{% endif %}",
    "on Tue, 14.04.2026": 'on {{value.date.strftime("%a")}}, {{value.date.strftime("%d.%m.%Y")}}',
    "on Tue, 2026-04-14": 'on {{value.date.strftime("%a")}}, {{value.date.strftime("%Y-%m-%d")}}',
    "Bio": '{{value.types|join(", ")}}',
}

DATE_TEMPLATE_PRESETS: dict[str, str] = {
    "14.04.2026": '{{value.date.strftime("%d.%m.%Y")}}',
    "Tue, 14.04.2026": '{{value.date.strftime("%a, %d.%m.%Y")}}',
    "04/14/2026": '{{value.date.strftime("%m/%d/%Y")}}',
    "Tue, 04/14/2026": '{{value.date.strftime("%a, %m/%d/%Y")}}',
    "2026-04-14": '{{value.date.strftime("%Y-%m-%d")}}',
    "Tue, 2026-04-14": '{{value.date.strftime("%a, %Y-%m-%d")}}',
}


def get_preset_option(template: str | None, presets: Mapping[str, str]) -> str:
    """Return the matching preset label for a stored template string."""
    if not template:
        return DEFAULT_OPTION

    for label, preset_template in presets.items():
        if template == preset_template:
            return label

    return CUSTOM_OPTION
