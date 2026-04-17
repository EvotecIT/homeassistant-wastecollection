"""Shared preset definitions for waste sensor display templates."""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_OPTION = "Default"
CUSTOM_OPTION = "Custom"
DEFAULT_PRESET_LANGUAGE = "en"
PRESET_LANGUAGE_OPTIONS: dict[str, str] = {
    "English": "en",
    "Polski": "pl",
}
PRESET_LANGUAGE_LABELS = {
    value: label for label, value in PRESET_LANGUAGE_OPTIONS.items()
}

EN_RELATIVE_TEMPLATE = (
    "{% if value.daysTo == 0 %}Today{% elif value.daysTo == 1 %}Tomorrow"
    "{% else %}in {{value.daysTo}} days{% endif %}"
)
PL_RELATIVE_TEMPLATE = (
    "{% if value.daysTo == 0 %}Dzisiaj{% elif value.daysTo == 1 %}Jutro"
    "{% else %}za {{value.daysTo}} dni{% endif %}"
)

VALUE_TEMPLATE_PRESET_DEFINITIONS: list[dict[str, tuple[str, str]]] = [
    {
        "en": ("in 13 days", "in {{value.daysTo}} days"),
        "pl": ("za 13 dni", "za {{value.daysTo}} dni"),
    },
    {
        "en": ("Bio in 13 days", '{{value.types|join(", ")}} in {{value.daysTo}} days'),
        "pl": ("Bio za 13 dni", '{{value.types|join(", ")}} za {{value.daysTo}} dni'),
    },
    {
        "en": ("13", "{{value.daysTo}}"),
        "pl": ("13", "{{value.daysTo}}"),
    },
    {
        "en": ("Today / Tomorrow / in 13 days", EN_RELATIVE_TEMPLATE),
        "pl": ("Dzisiaj / Jutro / za 13 dni", PL_RELATIVE_TEMPLATE),
    },
    {
        "en": (
            "on Tue, 14.04.2026",
            'on {{value.date.strftime("%a")}}, {{value.date.strftime("%d.%m.%Y")}}',
        ),
        "pl": ("14.04.2026", '{{value.date.strftime("%d.%m.%Y")}}'),
    },
    {
        "en": (
            "on Tue, 2026-04-14",
            'on {{value.date.strftime("%a")}}, {{value.date.strftime("%Y-%m-%d")}}',
        ),
        "pl": ("2026-04-14", '{{value.date.strftime("%Y-%m-%d")}}'),
    },
    {
        "en": ("Bio", '{{value.types|join(", ")}}'),
        "pl": ("Bio", '{{value.types|join(", ")}}'),
    },
]


def normalize_preset_language(language: str | None) -> str:
    """Return a supported preset language code."""
    if language in PRESET_LANGUAGE_LABELS:
        return language
    return DEFAULT_PRESET_LANGUAGE


def get_preset_language_label(language: str | None) -> str:
    """Return the user-facing label for a preset language code."""
    return PRESET_LANGUAGE_LABELS[normalize_preset_language(language)]


def get_preset_language_value(label: str) -> str:
    """Return the preset language code for a user-facing label."""
    return PRESET_LANGUAGE_OPTIONS.get(label, DEFAULT_PRESET_LANGUAGE)


def get_value_template_presets(language: str | None) -> dict[str, str]:
    """Return state-text presets for the selected language."""
    language = normalize_preset_language(language)
    return {
        labels[language][0]: labels[language][1]
        for labels in VALUE_TEMPLATE_PRESET_DEFINITIONS
    }


def get_all_value_template_presets() -> dict[str, str]:
    """Return every state-text preset across supported languages."""
    presets: dict[str, str] = {}
    for labels in VALUE_TEMPLATE_PRESET_DEFINITIONS:
        for label, template in labels.values():
            presets[label] = template
    return presets


def find_value_template_preset_index(template: str | None) -> int | None:
    """Return the stable preset index matching a stored state template."""
    if not template:
        return None

    for index, labels in enumerate(VALUE_TEMPLATE_PRESET_DEFINITIONS):
        if any(template == preset_template for _, preset_template in labels.values()):
            return index
    return None


def infer_preset_language_from_template(template: str | None) -> str:
    """Infer the display language from a known state-text template."""
    if not template:
        return DEFAULT_PRESET_LANGUAGE

    for labels in VALUE_TEMPLATE_PRESET_DEFINITIONS:
        for language, (_, preset_template) in labels.items():
            if template == preset_template:
                return language
    return DEFAULT_PRESET_LANGUAGE


def convert_value_template_language(
    template: str | None, language: str | None
) -> str | None:
    """Convert a known state-text preset template to another language."""
    index = find_value_template_preset_index(template)
    if index is None:
        return None

    language = normalize_preset_language(language)
    return VALUE_TEMPLATE_PRESET_DEFINITIONS[index][language][1]


VALUE_TEMPLATE_PRESETS = get_value_template_presets(DEFAULT_PRESET_LANGUAGE)

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
