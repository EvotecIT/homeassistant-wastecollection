import importlib
import inspect
import json
import logging
import types
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Tuple, TypedDict, Union, cast, get_origin

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, CONF_VALUE_TEMPLATE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    DurationSelector,
    DurationSelectorConfig,
    IconSelector,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
from homeassistant.helpers.translation import async_get_translations
from voluptuous.schema_builder import UNDEFINED
from waste_collection_schedule.collection import Collection
from waste_collection_schedule.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
    SourceArgumentRequired,
    SourceArgumentSuggestionsExceptionBase,
)

from .const import (
    CONF_ADD_DAYS_TO,
    CONF_ALIAS,
    CONF_COLLECTION_TYPES,
    CONF_COUNT,
    CONF_COUNTRY_NAME,
    CONF_CUSTOMIZE,
    CONF_DATE_TEMPLATE,
    CONF_DAY_OFFSET,
    CONF_DAY_OFFSET_DEFAULT,
    CONF_DAY_SWITCH_TIME,
    CONF_DAY_SWITCH_TIME_DEFAULT,
    CONF_DEDICATED_CALENDAR_TITLE,
    CONF_DETAILS_FORMAT,
    CONF_EVENT_INDEX,
    CONF_FETCH_TIME,
    CONF_FETCH_TIME_DEFAULT,
    CONF_ICON,
    CONF_LEADTIME,
    CONF_PICTURE,
    CONF_RANDOM_FETCH_TIME_OFFSET,
    CONF_RANDOM_FETCH_TIME_OFFSET_DEFAULT,
    CONF_SENSORS,
    CONF_SEPARATOR,
    CONF_SEPARATOR_DEFAULT,
    CONF_SHOW,
    CONF_SOURCE_ARGS,
    CONF_SOURCE_CALENDAR_TITLE,
    CONF_SOURCE_NAME,
    CONF_TYPE,
    CONF_USE_DEDICATED_CALENDAR,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    DOMAIN,
)
from .init_ui import WCSCoordinator
from .sensor import DetailsFormat, render_sensor_preview
from .sensor_form_helpers import apply_template_presets
from .sensor_template_presets import (
    DATE_TEMPLATE_PRESETS,
    VALUE_TEMPLATE_PRESETS,
    get_preset_option,
)
from .waste_collection_schedule import CollectionAggregator, Customize, SourceShell
from .waste_collection_schedule.type_aliases import (
    get_customize_label,
    get_uncustomized_types,
)

_LOGGER = logging.getLogger(__name__)

# Load source lists and metadata for configuration
_SOURCES_FILE = Path(__file__).parent / "sources.json"
_SOURCE_METADATA_FILE = Path(__file__).parent / "source_metadata.json"
_SOURCES: dict[str, list[Any]] = {}
_SOURCE_METADATA: dict[str, dict[str, Any]] = {}


def _load_sources() -> dict[str, list[Any]]:
    """Load sources.json with error handling."""
    try:
        with open(_SOURCES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _LOGGER.error(f"Failed to load sources.json: {e}")
        return {}


def _load_source_metadata() -> dict[str, dict[str, Any]]:
    """Load source_metadata.json with error handling."""
    try:
        with open(_SOURCE_METADATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _LOGGER.warning(f"Failed to load source metadata: {e}")
        return {}


# Initialize both files on module import
_SOURCES = _load_sources()
_SOURCE_METADATA = _load_source_metadata()


SECTION_GENERAL = "general"
SECTION_MANAGE = "manage"
SECTION_CUSTOMIZE_BASIC = "basic"
SECTION_CUSTOMIZE_APPEARANCE = "appearance"
SECTION_CUSTOMIZE_CALENDAR = "calendar"
SECTION_SENSOR_IDENTITY = "identity"
SECTION_SENSOR_DISPLAY = "display"
SECTION_SENSOR_FILTERING = "filtering"
SECTION_SENSOR_MANAGEMENT = "management"
SECTION_CUSTOMIZE_MANAGEMENT = "management"
CONF_ADVANCED_MODE = "advanced_mode"


def _get_source_metadata(source: str) -> dict[str, Any]:
    """Get metadata for a source, with fallback to empty dict."""
    return _SOURCE_METADATA.get(source, {})


def flatten_section_input(
    user_input: dict[str, Any] | None, section_names: set[str]
) -> dict[str, Any] | None:
    """Flatten section-based flow data into the flat structure used internally."""
    if user_input is None:
        return None

    flattened: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in section_names and isinstance(value, dict):
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


class PreviewSource:
    """Tiny source wrapper used to build preview shells from cached collections."""

    def __init__(self, collections: list[Collection]) -> None:
        self._collections = collections

    def fetch(self) -> list[Collection]:
        return deepcopy(self._collections)


def get_customize_objects(
    customize_options: dict[str, dict[str, Any]] | None,
) -> dict[str, Customize]:
    """Convert stored customization dictionaries into runtime Customize objects."""
    if not customize_options:
        return {}

    return {
        waste_type: Customize(
            waste_type=waste_type,
            alias=customize.get(CONF_ALIAS),
            show=customize.get(CONF_SHOW, True),
            icon=customize.get(CONF_ICON),
            picture=customize.get(CONF_PICTURE),
            use_dedicated_calendar=customize.get(CONF_USE_DEDICATED_CALENDAR, False),
            dedicated_calendar_title=customize.get(CONF_DEDICATED_CALENDAR_TITLE),
        )
        for waste_type, customize in customize_options.items()
    }


def normalize_sensor_user_input(sensor_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply preset handling and normalize enum values for sensor forms."""
    args, errors = apply_template_presets(sensor_input)

    if CONF_DETAILS_FORMAT in args and isinstance(args[CONF_DETAILS_FORMAT], str):
        args[CONF_DETAILS_FORMAT] = DetailsFormat[args[CONF_DETAILS_FORMAT]]

    return args, errors


def get_preview_sensor_input(
    hass: HomeAssistant, sensor_input: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize sensor input and compile templates for preview rendering."""
    args, errors = normalize_sensor_user_input(sensor_input)

    for key in [CONF_VALUE_TEMPLATE, CONF_DATE_TEMPLATE]:
        if key not in args or not args[key]:
            continue
        try:
            args[key] = cv.template(args[key])
            args[key].hass = hass
        except vol.Invalid:
            errors[key] = "invalid_template"

    return args, errors


def build_preview_shell(
    collections: list[Collection],
    customize_options: dict[str, dict[str, Any]] | None,
    calendar_title: str | None,
    day_offset: int,
) -> SourceShell:
    """Build a temporary shell for previewing sensors without refetching."""
    shell = SourceShell(
        source=PreviewSource(collections),
        customize=get_customize_objects(customize_options),
        title=calendar_title or "Waste Collection Schedule",
        description="Preview",
        url=None,
        calendar_title=calendar_title,
        unique_id="waste_collection_schedule_preview",
        day_offset=day_offset,
    )
    shell.fetch()
    return shell


SUPPORTED_ARG_TYPES = {
    str: cv.string,
    int: cv.positive_int,
    bool: cv.boolean,
    list: TextSelector(TextSelectorConfig(multiple=True)),
    list[str]: TextSelector(TextSelectorConfig(multiple=True)),
    list[str] | str: TextSelector(TextSelectorConfig(multiple=True)),
    list[str] | str | None: TextSelector(TextSelectorConfig(multiple=True)),
    list[str | int]: TextSelector(TextSelectorConfig(multiple=True)),
    list[date | str]: TextSelector(
        TextSelectorConfig(multiple=True, type=TextSelectorType.DATE)
    ),
    date | str: TextSelector(TextSelectorConfig(type=TextSelectorType.DATE)),
    date | str | None: TextSelector(TextSelectorConfig(type=TextSelectorType.DATE)),
    dict: ObjectSelector(),
    str | int: cv.string,
    date: cv.date,
    datetime: cv.datetime,
}


def get_customize_schema(defaults: dict[str, Any] = {}, add_delete: bool = False):
    schema = {
        vol.Required(SECTION_CUSTOMIZE_BASIC): section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_ALIAS, default=defaults.get(CONF_ALIAS, UNDEFINED)
                    ): str,
                    vol.Optional(
                        CONF_SHOW, default=defaults.get(CONF_SHOW, True)
                    ): cv.boolean,
                }
            ),
            {"collapsed": False},
        ),
        vol.Required(SECTION_CUSTOMIZE_APPEARANCE): section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_ICON, default=defaults.get(CONF_ICON, UNDEFINED)
                    ): IconSelector(),
                    vol.Optional(
                        CONF_PICTURE, default=defaults.get(CONF_PICTURE, UNDEFINED)
                    ): str,
                }
            ),
            {"collapsed": True},
        ),
        vol.Required(SECTION_CUSTOMIZE_CALENDAR): section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_USE_DEDICATED_CALENDAR,
                        default=defaults.get(CONF_USE_DEDICATED_CALENDAR, UNDEFINED),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_DEDICATED_CALENDAR_TITLE,
                        default=defaults.get(
                            CONF_DEDICATED_CALENDAR_TITLE, UNDEFINED
                        ),
                    ): str,
                }
            ),
            {"collapsed": True},
        ),
    }
    if add_delete:
        schema[vol.Required(SECTION_CUSTOMIZE_MANAGEMENT)] = section(
            vol.Schema({vol.Optional("delete"): cv.boolean}),
            {"collapsed": True},
        )
    return vol.Schema(schema)


def _sensor_defaults(defaults: dict[str, Any]) -> dict[str, Any]:
    """Add derived UI defaults for sensor preset selectors."""
    derived_defaults = defaults.copy()
    derived_defaults[CONF_VALUE_TEMPLATE + "_preset"] = get_preset_option(
        defaults.get(CONF_VALUE_TEMPLATE), VALUE_TEMPLATE_PRESETS
    )
    derived_defaults[CONF_DATE_TEMPLATE + "_preset"] = get_preset_option(
        defaults.get(CONF_DATE_TEMPLATE), DATE_TEMPLATE_PRESETS
    )
    return derived_defaults


def _show_advanced_sensor_fields(defaults: dict[str, Any]) -> bool:
    """Return True when the advanced sensor editor should be expanded."""
    if defaults.get(CONF_ADVANCED_MODE):
        return True

    for key in [
        CONF_VALUE_TEMPLATE,
        CONF_DATE_TEMPLATE,
        CONF_COUNT,
        CONF_LEADTIME,
        CONF_EVENT_INDEX,
        CONF_COLLECTION_TYPES,
    ]:
        if defaults.get(key) not in (None, "", [], False):
            return True

    return False


def _should_refresh_sensor_form(
    user_input: dict[str, Any], defaults: dict[str, Any] | None = None
) -> bool:
    """Return True when the user toggled advanced mode and the form should redraw."""
    derived_defaults = _sensor_defaults(defaults or {})
    current_show_advanced = _show_advanced_sensor_fields(derived_defaults)
    requested_show_advanced = user_input.get(CONF_ADVANCED_MODE, current_show_advanced)
    return bool(requested_show_advanced) != current_show_advanced


def get_sensor_schema(
    fetched_types, add_delete: bool = False, defaults: dict[str, Any] | None = None
):
    defaults = _sensor_defaults(defaults or {})
    show_advanced = _show_advanced_sensor_fields(defaults)
    display_fields: dict[Any, Any] = {
        vol.Optional(
            CONF_DETAILS_FORMAT,
            default=defaults.get(CONF_DETAILS_FORMAT, "upcoming"),
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        label=k,
                        value=k,
                    )
                    for k in DetailsFormat.__members__.keys()
                ],
                translation_key="details_format",
            )
        ),
        vol.Optional(
            CONF_VALUE_TEMPLATE + "_preset",
            default=defaults.get(CONF_VALUE_TEMPLATE + "_preset", "Default"),
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(label="Use built-in default", value="Default"),
                    *[
                        SelectOptionDict(label=label, value=label)
                        for label in VALUE_TEMPLATE_PRESETS
                    ],
                    SelectOptionDict(label="Write my own template", value="Custom"),
                ],
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=False,
                multiple=False,
            )
        ),
        vol.Optional(
            CONF_DATE_TEMPLATE + "_preset",
            default=defaults.get(CONF_DATE_TEMPLATE + "_preset", "Default"),
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(label="Use built-in default", value="Default"),
                    *[
                        SelectOptionDict(label=label, value=label)
                        for label in DATE_TEMPLATE_PRESETS
                    ],
                    SelectOptionDict(label="Write my own template", value="Custom"),
                ],
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=False,
                multiple=False,
            )
        ),
        vol.Optional(
            CONF_ADD_DAYS_TO,
            default=defaults.get(CONF_ADD_DAYS_TO, UNDEFINED),
        ): cv.boolean,
        vol.Optional(
            CONF_ADVANCED_MODE,
            default=defaults.get(CONF_ADVANCED_MODE, show_advanced),
        ): cv.boolean,
    }
    if show_advanced:
        display_fields.update(
            {
                vol.Optional(
                    CONF_VALUE_TEMPLATE,
                    default=defaults.get(CONF_VALUE_TEMPLATE, UNDEFINED),
                ): TemplateSelector(),
                vol.Optional(
                    CONF_DATE_TEMPLATE,
                    default=defaults.get(CONF_DATE_TEMPLATE, UNDEFINED),
                ): TemplateSelector(),
            }
        )

    schema = {
        vol.Required(SECTION_SENSOR_IDENTITY): section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME, default=defaults.get(CONF_NAME, UNDEFINED)
                    ): cv.string,
                }
            ),
            {"collapsed": False},
        ),
        vol.Required(SECTION_SENSOR_DISPLAY): section(
            vol.Schema(display_fields),
            {"collapsed": False},
        ),
    }

    if show_advanced:
        schema[vol.Required(SECTION_SENSOR_FILTERING)] = section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_COUNT, default=defaults.get(CONF_COUNT, UNDEFINED)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                    vol.Optional(
                        CONF_LEADTIME, default=defaults.get(CONF_LEADTIME, UNDEFINED)
                    ): int,
                    vol.Optional(
                        CONF_EVENT_INDEX,
                        default=defaults.get(CONF_EVENT_INDEX, UNDEFINED),
                    ): int,
                    vol.Optional(
                        CONF_COLLECTION_TYPES,
                        default=defaults.get(CONF_COLLECTION_TYPES, UNDEFINED),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=fetched_types,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                            multiple=True,
                        )
                    ),
                }
            ),
            {"collapsed": True},
        )
    management_schema = {}
    if add_delete:
        management_schema[vol.Optional("delete")] = cv.boolean
    else:
        management_schema[vol.Optional("skip", default=False)] = cv.boolean
        management_schema[vol.Optional("additional", default=False)] = cv.boolean

    schema[vol.Required(SECTION_SENSOR_MANAGEMENT)] = section(
        vol.Schema(management_schema),
        {"collapsed": True},
    )

    return vol.Schema(schema)


def validate_sensor_user_input(
    sensor_input: dict[str, Any], existing_sensors
) -> Tuple[dict[str, Any], dict[str, str]]:
    """
    Validate sensor user input.

    Args:
        sensor_input (dict[str, Any]): user input

    Returns:
        Tuple[dict, dict]: errors, extracted args
    """
    args, errors = normalize_sensor_user_input(sensor_input)
    args.pop(CONF_ADVANCED_MODE, None)
    for key in [CONF_VALUE_TEMPLATE, CONF_DATE_TEMPLATE]:
        if args.get(key) == "":
            args.pop(key, None)

    # validate value_template and date_template against cv.template
    for key in [CONF_VALUE_TEMPLATE, CONF_DATE_TEMPLATE]:
        if key in args and args[key]:
            try:
                cv.template(args[key])
            except vol.Invalid:
                errors[key] = "invalid_template"

    if sensor_input.get("skip", False) and sensor_input.get("additional", False):
        errors["base"] = "skip_additional"

    # map CONF_DETAILS_FORMAT to enum DetailsFormat
    if CONF_DETAILS_FORMAT in args:
        args[CONF_DETAILS_FORMAT] = DetailsFormat[args[CONF_DETAILS_FORMAT]]

    if not args.get(CONF_NAME):
        errors[CONF_NAME] = "sensor_name_empty"
    # enforce unique Name
    elif any([x[CONF_NAME] == args[CONF_NAME] for x in existing_sensors]):
        errors[CONF_NAME] = "name_exists"

    return args, errors if args.get("skip", False) is False else {}


class SourceDict(TypedDict):
    title: str
    module: str
    default_params: dict[str, Any]
    id: str


class WasteCollectionConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Config flow."""

    VERSION = CONFIG_VERSION
    MINOR_VERSION = CONFIG_MINOR_VERSION
    _country: str | None = None
    _source: str | None = None

    _options: dict = {}
    _sources: dict[str, list[SourceDict]] = {}
    _error_suggestions: dict[str, list[Any]]

    async def _async_setup_sources(self) -> None:
        if len(self._sources) > 0:
            return

        # Use pre-loaded sources from module level
        self._sources = _SOURCES

        async def args_method(args_input):
            return await self.async_step_args(args_input)

        async def reconfigure_method(args_input):
            return await self.async_step_reconfigure(args_input)

        for sources in self._sources.values():
            for source in sources:
                setattr(
                    self,
                    f"async_step_args_{source['id']}",
                    args_method,
                )
                setattr(
                    self,
                    f"async_step_reconfigure_{source['id']}",
                    reconfigure_method,
                )

    # Step 1: User selects country
    async def async_step_user(
        self, info: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self._async_setup_sources()

        if info is not None:
            self._country = info[CONF_COUNTRY_NAME]
            return await self.async_step_source()

        SCHEMA = vol.Schema(
            {
                vol.Required(CONF_COUNTRY_NAME): SelectSelector(
                    SelectSelectorConfig(
                        options=[""] + list(self._sources.keys()),
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=SCHEMA)

    # Step 2: User selects source
    async def async_step_source(
        self, info: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._country = cast(str, self._country)
        sources = self._sources[self._country]
        sources_options = [SelectOptionDict(value="", label="")] + [
            SelectOptionDict(
                value=f"{x['module']}\t{x['title']}\t{x['id']}",
                label=f"{x['title']} ({x['module']})",
            )
            for x in sources
        ]

        SCHEMA = vol.Schema(
            {
                vol.Required(CONF_SOURCE_NAME): SelectSelector(
                    SelectSelectorConfig(
                        options=sources_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=True,
                        multiple=False,
                        custom_value=True,  # allows to properly search while typing in the dropdown
                    )
                )
            }
        )

        errors = {}
        if info is not None:
            if not (
                "\t" in info[CONF_SOURCE_NAME]
                and info[CONF_SOURCE_NAME].split("\t")[0]
                in [x["module"] for x in sources]
            ):
                errors[CONF_SOURCE_NAME] = "invalid_source"
            else:
                self._source = info[CONF_SOURCE_NAME].split("\t")[0]
                self._title = info[CONF_SOURCE_NAME].split("\t")[1]
                self._id = info[CONF_SOURCE_NAME].split("\t")[2]
                self._extra_info_default_params = next(
                    (
                        x["default_params"]
                        for x in self._sources[self._country]
                        if info[CONF_SOURCE_NAME].startswith(
                            f"{x['module']}\t{x['title']}"
                        )
                    ),
                    {},
                )
                return await self.async_step_args()

        return self.async_show_form(step_id="source", data_schema=SCHEMA, errors=errors)

    async def __get_simple_annotation_type(self, annotation: Any) -> Any:
        if annotation in SUPPORTED_ARG_TYPES:
            return SUPPORTED_ARG_TYPES[annotation]
        if (
            isinstance(annotation, types.GenericAlias)
            and annotation.__origin__ in SUPPORTED_ARG_TYPES
        ):
            return SUPPORTED_ARG_TYPES[annotation.__origin__]

        if getattr(annotation, "__origin__", None) is Literal:
            return SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(label=x, value=x)
                        for x in annotation.__args__
                        if x is not None
                    ],
                    custom_value=False,
                    multiple=False,
                )
            )
        return None

    async def __get_type_by_annotation(self, annotation: Any) -> Any:
        if a := await self.__get_simple_annotation_type(annotation):
            return a
        if (
            (isinstance(annotation, types.GenericAlias))
            or (
                get_origin(annotation) is not None and hasattr(annotation, "__origin__")
            )
            and (a := await self.__get_simple_annotation_type(annotation.__origin__))
        ):
            return a
        return_val = None
        is_string = False

        if (
            isinstance(annotation, types.UnionType)
            or getattr(annotation, "__origin__", None) is Union
        ):
            for arg in annotation.__args__:
                if a := await self.__get_type_by_annotation(arg):
                    if isinstance(a, ObjectSelector):
                        return a
                    if not is_string:
                        return_val = a
                    is_string = a == cv.string
        return return_val

    async def __get_arg_schema(
        self,
        source: str,
        pre_filled: dict[str, Any],
        args_input: dict[str, Any] | None,
        include_title=True,
    ) -> Tuple[vol.Schema, types.ModuleType]:
        """Get schema for source arguments.

        Args:
            source (str): source name
            pre_filled (dict[str, Any]): arguments that are pre-filled (description suggested_value)
            args_input (dict[str, Any] | None): user input used to pre-fill the form with higher priority than pre_filled
            include_title (bool, optional): weather to include the title name field (only used on initial configure not on reconfigure). Defaults to True.

        Returns:
            Tuple[vol.Schema, types.ModuleType]: schema, module
        """
        suggestions: dict[str, list[Any]] = {}
        if hasattr(self, "_error_suggestions"):
            suggestions = {
                key: value
                for key, value in self._error_suggestions.items()
                if len(value) > 0
            }

        # Import source and get arguments
        module = await self.hass.async_add_executor_job(
            importlib.import_module, f"waste_collection_schedule.source.{source}"
        )

        args = dict(inspect.signature(module.Source.__init__).parameters)
        del args["self"]  # Remove self
        # Convert schema for vol
        vol_args = {}
        title = source  # Default title Should probably be overwritten by the module
        if hasattr(module, "TITLE") and isinstance(module.TITLE, str):
            title = module.TITLE
        if hasattr(self, "_title") and isinstance(self._title, str):
            title = self._title

        if include_title:
            description = None
            if args_input is not None and CONF_SOURCE_CALENDAR_TITLE in args_input:
                description = {
                    "suggested_value": args_input[CONF_SOURCE_CALENDAR_TITLE]
                }
            vol_args = {
                vol.Optional(
                    CONF_SOURCE_CALENDAR_TITLE,
                    description=description,
                    default=title,
                ): str,
            }

        MODULE_FLOW_TYPES = (
            module.CONFIG_FLOW_TYPES if hasattr(module, "CONFIG_FLOW_TYPES") else {}
        )

        for arg in args:
            default = args[arg].default
            arg_name = args[arg].name
            field_type = None

            annotation = args[arg].annotation
            description = None
            if args_input is not None and arg_name in args_input:
                description = {"suggested_value": args_input[arg_name]}
                _LOGGER.debug(
                    f"Setting suggested value for {arg_name} to {args_input[arg_name]} (previously filled in)"
                )
            elif arg_name in pre_filled:
                _LOGGER.debug(
                    f"Setting default value for {arg_name} to {pre_filled[arg_name]}"
                )
                description = {
                    "suggested_value": pre_filled[arg_name],
                }
            if annotation != inspect._empty:
                field_type = (
                    await self.__get_type_by_annotation(annotation) or field_type
                )
            _LOGGER.debug(
                f"Default for {arg_name}: {type(default) if default is not inspect.Signature.empty else inspect.Signature.empty}"
            )

            if arg_name in MODULE_FLOW_TYPES:
                flow_type = MODULE_FLOW_TYPES[arg_name]
                if flow_type.get("type") == "SELECT":
                    field_type = SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(label=x, value=x)
                                for x in flow_type.get("values")
                            ],
                            translation_key="custom_flow_types",
                            mode=SelectSelectorMode.DROPDOWN,
                            multiple=flow_type.get("multiple", False),
                        )
                    )

            if field_type is None:
                field_type = SUPPORTED_ARG_TYPES.get(type(default))

            if (
                (field_type or str) in (str, cv.string)
                or (
                    isinstance(field_type, TextSelector)
                    and "multiple" in field_type.config
                    and field_type.config.get("type", TextSelectorType.TEXT)
                    == TextSelectorType.TEXT
                    and field_type.config["multiple"]
                )
            ) and args[arg].name in suggestions:
                _LOGGER.debug(
                    f"Adding suggestions to {arg_name}: {suggestions[arg_name]}"
                )
                # Add suggestions to the field if fetch/init raised an Exception with suggestions
                field_type = SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(label=x, value=x)
                            for x in suggestions[arg_name]
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                        multiple=isinstance(field_type, TextSelector),
                    )
                )

            if default == inspect.Signature.empty:
                vol_args[vol.Required(arg_name, description=description)] = (
                    field_type or str
                )

            elif field_type or (default is None):
                # Handle boolean, int, string, date, datetime, list defaults
                vol_args[
                    vol.Optional(
                        arg_name,
                        default=UNDEFINED if default is None else default,
                        description=description,
                    )
                ] = (
                    field_type or cv.string
                )
            else:
                _LOGGER.debug(
                    f"Unsupported type: {type(default)}: {arg_name}: {default}: {field_type}"
                )

        schema = vol.Schema(vol_args)
        return schema, module

    async def __validate_args_user_input(
        self, source: str, args_input: dict[str, Any], module: types.ModuleType
    ) -> Tuple[dict[str, str], dict[str, str], dict[str, Any]]:
        """Validate user input for source arguments.

        Args:
            source (str): source name
            args_input (dict[str, Any]): user input
            module (types.ModuleType): the module of the source

        Returns:
            Tuple[dict, dict, dict]: errors, description_placeholders, options
        """
        errors = {}
        description_placeholders: dict[str, str] = {}

        if hasattr(module, "validate_params"):
            errors.update(module.validate_params(args_input))
        options = {}

        # Pop title if provided
        if CONF_SOURCE_CALENDAR_TITLE in args_input:
            options[CONF_SOURCE_CALENDAR_TITLE] = args_input.pop(
                CONF_SOURCE_CALENDAR_TITLE
            )

        await self.async_set_unique_id(source + json.dumps(args_input))
        self._abort_if_unique_id_configured()

        try:
            instance = await self.hass.async_add_executor_job(
                self._get_source_instance, module, args_input
            )

            resp: list[Collection] = await self.hass.async_add_executor_job(
                instance.fetch
            )
            self._preview_collections = deepcopy(resp)

            if len(resp) == 0:
                errors["base"] = "fetch_empty"
            self._fetched_types = list({x.type.strip() for x in resp})
        except SourceArgumentSuggestionsExceptionBase as e:
            if not hasattr(self, "_error_suggestions"):
                self._error_suggestions = {}
            self._error_suggestions.update({e.argument: e.suggestions})
            errors[e.argument] = "invalid_arg"
            description_placeholders["invalid_arg_message"] = e.simple_message
            if e.suggestion_type != str and e.suggestion_type != int:
                description_placeholders["invalid_arg_message"] = e.message
        except SourceArgumentRequired as e:
            errors[e.argument] = "invalid_arg"
            description_placeholders["invalid_arg_message"] = e.message
        except SourceArgumentException as e:
            errors[e.argument] = "invalid_arg"
            description_placeholders["invalid_arg_message"] = e.message
        except SourceArgumentExceptionMultiple as e:
            description_placeholders["invalid_arg_message"] = e.message
            if len(e.arguments) == 0:
                errors["base"] = "invalid_arg"
            else:
                for arg in e.arguments:
                    errors[f"{source}_{arg}"] = "invalid_arg"
        except Exception as e:
            errors["base"] = "fetch_error"
            description_placeholders["fetch_error_message"] = str(e)
        return errors, description_placeholders, options

    def _get_source_instance(self, module, args_input: dict[str, Any]):
        kwargs = args_input
        return module.Source(**kwargs)

    def _get_description_placeholders(self, source: str) -> dict[str, str]:
        """Get description placeholders (URLs and howto) for a source."""
        placeholders: dict[str, str] = {}
        if source in _SOURCE_METADATA:
            metadata = _SOURCE_METADATA[source]
            placeholders["docs_url"] = metadata.get("docs_url", "")
            placeholders.update(metadata.get("urls", {}))
            # Get howto for current language (defaults to English)
            howto_dict = metadata.get("howto", {})
            # Try to get howto for the current language
            hass = getattr(self, "hass", None)
            language = getattr(getattr(hass, "config", None), "language", "en")
            placeholders["howto"] = howto_dict.get(language, howto_dict.get("en", ""))
            if placeholders["howto"]:
                placeholders["howto"] = placeholders["howto"].rstrip("\n") + "\n\n"
        return placeholders

    async def async_source_selected(self) -> None:
        async def args_method(args_input):
            return await self.async_step_args(args_input)

        setattr(
            self,
            f"async_step_args_{self._id}",
            args_method,
        )
        return await self.async_step_args()

    # Step 3: User fills in source arguments
    async def async_step_args(self, args_input=None) -> ConfigFlowResult:
        self._source = cast(str, self._source)
        schema, module = await self.__get_arg_schema(
            self._source, self._extra_info_default_params, args_input
        )
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = self._get_description_placeholders(
            self._id
        )
        # If all args are filled in
        if args_input is not None:
            # if contains method:
            (
                errors,
                validation_placeholders,
                options,
            ) = await self.__validate_args_user_input(self._source, args_input, module)

            if len(errors) > 0:
                schema, module = await self.__get_arg_schema(
                    self._source, self._extra_info_default_params, args_input
                )
                # Update placeholders with validation errors
                description_placeholders.update(validation_placeholders)
            else:
                self._args_data = {
                    CONF_SOURCE_NAME: self._source,
                    CONF_SOURCE_ARGS: args_input,
                }
                self._options.update(options)
                self.async_show_form(step_id="options")
                return await self.async_step_flow_type()
        return self.async_show_form(
            step_id=f"args_{self._id}",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_flow_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        schema = vol.Schema(
            {
                vol.Optional("show_customize_config", default=False): bool,
                vol.Optional("show_sensor_config", default=False): bool,
            }
        )

        if user_input is not None:
            self._show_customize_config = user_input.get("show_customize_config", False)
            self._show_sensor_config = user_input.get("show_sensor_config", False)
            if self._show_customize_config:
                return await self.async_step_customize_select()
            elif self._show_sensor_config:
                return await self.async_step_sensor()
            else:
                return await self.finish()
        return self.async_show_form(step_id="flow_type", data_schema=schema)

    async def async_step_customize_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        schema = vol.Schema(
            {
                vol.Optional(CONF_TYPE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._fetched_types,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                        multiple=True,
                    )
                ),
            }
        )

        if user_input is not None:
            self._customize_types = list(set(user_input.get(CONF_TYPE, [])))
            self._fetched_types = list({*self._fetched_types, *self._customize_types})
            return await self.async_step_customize()
        return self.async_show_form(step_id="customize_select", data_schema=schema)

    async def async_step_customize(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        types = []
        if hasattr(self, "_customize_types"):
            types = self._customize_types
        if not hasattr(self, "_customize_index"):
            self._customize_index = 0
        if CONF_CUSTOMIZE not in self._options:
            self._options[CONF_CUSTOMIZE] = {}
        if self._customize_index >= len(types):
            if self._show_sensor_config:
                return await self.async_step_sensor()
            else:
                return await self.finish()

        errors = {}

        if user_input is not None:
            sectioned_user_input = user_input
            user_input = flatten_section_input(
                sectioned_user_input,
                {
                    SECTION_CUSTOMIZE_BASIC,
                    SECTION_CUSTOMIZE_APPEARANCE,
                    SECTION_CUSTOMIZE_CALENDAR,
                    SECTION_CUSTOMIZE_MANAGEMENT,
                },
            )
            if user_input.get(CONF_DEDICATED_CALENDAR_TITLE, "") and not user_input.get(
                CONF_USE_DEDICATED_CALENDAR, False
            ):
                errors[CONF_DEDICATED_CALENDAR_TITLE] = (
                    "dedicated_calendar_title_without_use_dedicated_calendar"
                )
            else:
                if CONF_ALIAS in user_input:
                    self._fetched_types.remove(types[self._customize_index])
                    self._fetched_types.append(user_input[CONF_ALIAS])
                self._options[CONF_CUSTOMIZE][types[self._customize_index]] = user_input
                self._customize_index += 1
                return await self.async_step_customize()

        schema = get_customize_schema()
        if errors:
            schema = self.add_suggested_values_to_schema(schema, sectioned_user_input)
        return self.async_show_form(
            step_id="customize",
            data_schema=schema,
            description_placeholders={
                "type": types[self._customize_index],
                "index": self._customize_index + 1,
                "total": len(types),
            },
            errors=errors,
        )

    async def async_step_sensor(
        self, sensor_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not hasattr(self, "sensors"):
            self.sensors: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        schema_defaults = sensor_input or {}
        if sensor_input is not None:
            sensor_input = flatten_section_input(
                sensor_input,
                {
                    SECTION_SENSOR_IDENTITY,
                    SECTION_SENSOR_DISPLAY,
                    SECTION_SENSOR_FILTERING,
                    SECTION_SENSOR_MANAGEMENT,
                },
            )
            schema_defaults = sensor_input or {}
            if sensor_input and _should_refresh_sensor_form(sensor_input):
                return self.async_show_form(
                    step_id="sensor",
                    data_schema=self.add_suggested_values_to_schema(
                        get_sensor_schema(self._fetched_types, defaults=sensor_input),
                        sensor_input,
                    ),
                    errors=errors,
                    description_placeholders={
                        "sensor_number": str(len(self.sensors) + 1)
                    },
                )
            args, errors = validate_sensor_user_input(sensor_input, self.sensors)
            if len(errors) == 0 or args.get("skip", False) is True:
                if args.get("skip", False) is False:
                    self.sensors.append(args)
                if args.get("additional", False) is False:
                    self._options.update({CONF_SENSORS: self.sensors})
                    return await self.finish()

        return self.async_show_form(
            step_id="sensor",
            data_schema=self.add_suggested_values_to_schema(
                get_sensor_schema(self._fetched_types, defaults=schema_defaults),
                sensor_input or {},
            ),
            errors=errors,
            description_placeholders={"sensor_number": str(len(self.sensors) + 1)},
        )

    async def finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._title,
            data=self._args_data,
            options=self._options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return WasteCollectionOptionsFlow(config_entry)

    @staticmethod
    async def async_setup_preview(hass: HomeAssistant) -> None:
        """Register websocket preview support for the sensor editor."""
        websocket_api.async_register_command(hass, ws_start_preview)

    async def async_step_reconfigure(self, args_input: dict[str, Any] | None = None):
        await self._async_setup_sources()

        config_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if config_entry is None:
            return self.async_abort(reason="reconfigure_failed")

        source = config_entry.data["name"]
        schema, module = await self.__get_arg_schema(
            source, config_entry.data["args"], args_input, include_title=False
        )
        title = module.TITLE
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = self._get_description_placeholders(
            source
        )
        # If all args are filled in
        if args_input is not None:
            # if contains method:
            (
                errors,
                validation_placeholders,
                options,
            ) = await self.__validate_args_user_input(source, args_input, module)
            # Update placeholders with validation errors
            description_placeholders.update(validation_placeholders)
            if len(errors) == 0:
                data = {**config_entry.data}
                data.update({CONF_SOURCE_NAME: source, CONF_SOURCE_ARGS: args_input})
                # Preserve existing options (sensors, customizations, etc.)
                # and only update the fields returned by validation
                merged_options = {**config_entry.options, **options}
                return self.async_update_reload_and_abort(
                    config_entry,
                    title=title,
                    unique_id=config_entry.unique_id,
                    data=data,
                    options=merged_options,
                    reason="reconfigure_successful",
                )
        return self.async_show_form(
            step_id=f"reconfigure_{source}",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )


class WasteCollectionOptionsFlow(OptionsFlow):
    """Options flow."""

    def __init__(self, entry) -> None:
        self._entry: ConfigEntry = entry

    async def translate(self, text: str) -> str:
        user_language = self.hass.config.language
        return await async_get_translations(self.hass, user_language, DOMAIN)(text)

    async def async_get_preview_collections(self) -> list[Collection]:
        """Load source collections once so preview can reuse real schedule data."""
        if hasattr(self, "_preview_collections"):
            return self._preview_collections

        coordinator: WCSCoordinator | None = self.hass.data.get(DOMAIN, {}).get(
            self._entry.entry_id
        )
        if coordinator is None:
            raise HomeAssistantError("Preview is not available for this entry")

        self._preview_collections = await self.hass.async_add_executor_job(
            coordinator.shell._source.fetch
        )
        return self._preview_collections

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        # get SourceShells
        collection_types = []
        calendar_title = UNDEFINED
        # get the right coordinator
        coordinator: WCSCoordinator = self.hass.data.get(DOMAIN, {}).get(
            self._entry.entry_id
        )

        if coordinator and isinstance(coordinator, WCSCoordinator):
            collection_types = list(coordinator._aggregator.types)
            calendar_title = coordinator._shell.calendar_title

        customize_options = self._entry.options.get(CONF_CUSTOMIZE, {})
        uncustomized_types = get_uncustomized_types(collection_types, customize_options)

        SCHEMA = vol.Schema(
            {
                vol.Required(SECTION_GENERAL): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_SOURCE_CALENDAR_TITLE,
                                default=self._entry.options.get(
                                    CONF_SOURCE_CALENDAR_TITLE, calendar_title
                                ),
                            ): cv.string,
                            vol.Optional(
                                CONF_SEPARATOR,
                                default=self._entry.options.get(
                                    CONF_SEPARATOR, CONF_SEPARATOR_DEFAULT
                                ),
                            ): cv.string,
                            vol.Optional(
                                CONF_FETCH_TIME,
                                default=self._entry.options.get(
                                    CONF_FETCH_TIME, CONF_FETCH_TIME_DEFAULT
                                ),
                            ): TimeSelector(),
                            vol.Optional(
                                CONF_RANDOM_FETCH_TIME_OFFSET,
                                default={
                                    "hours": self._entry.options.get(
                                        CONF_RANDOM_FETCH_TIME_OFFSET,
                                        CONF_RANDOM_FETCH_TIME_OFFSET_DEFAULT,
                                    )
                                    // 60,
                                    "minutes": self._entry.options.get(
                                        CONF_RANDOM_FETCH_TIME_OFFSET,
                                        CONF_RANDOM_FETCH_TIME_OFFSET_DEFAULT,
                                    )
                                    % 60,
                                    "seconds": 0,
                                },
                            ): DurationSelector(
                                DurationSelectorConfig(enable_day=False)
                            ),
                            vol.Optional(
                                CONF_DAY_SWITCH_TIME,
                                default=self._entry.options.get(
                                    CONF_DAY_SWITCH_TIME,
                                    CONF_DAY_SWITCH_TIME_DEFAULT,
                                ),
                            ): TimeSelector(),
                            vol.Optional(
                                CONF_DAY_OFFSET,
                                default=self._entry.options.get(
                                    CONF_DAY_OFFSET, CONF_DAY_OFFSET_DEFAULT
                                ),
                            ): int,
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_MANAGE): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                "sensor_select",
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    translation_key="sensor_select",
                                    options=[
                                        *[
                                            SelectOptionDict(
                                                label=x[CONF_NAME],
                                                value=x[CONF_NAME],
                                            )
                                            for x in self._entry.options.get(
                                                CONF_SENSORS, []
                                            )
                                        ],
                                        SelectOptionDict(
                                            label="add_new_sensor",
                                            value="sensor_select_add_new",
                                        ),
                                    ],
                                    custom_value=False,
                                    multiple=True,
                                )
                            ),
                            vol.Optional(
                                "customize_select",
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=[
                                        *[
                                            SelectOptionDict(
                                                label=get_customize_label(key, value),
                                                value=key,
                                            )
                                            for key, value in customize_options.items()
                                        ],
                                        *[
                                            SelectOptionDict(label=x, value=x)
                                            for x in uncustomized_types
                                        ],
                                    ],
                                    custom_value=True,
                                    multiple=True,
                                )
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
            }
        )
        errors = {}

        # If form filled, update options
        if user_input is not None:
            user_input = flatten_section_input(
                user_input, {SECTION_GENERAL, SECTION_MANAGE}
            )
            # Check if the times are valid format
            try:
                cv.time(user_input[CONF_FETCH_TIME])
            except vol.Invalid:
                errors[CONF_FETCH_TIME] = "time_format"
            try:
                cv.time(user_input[CONF_DAY_SWITCH_TIME])
            except vol.Invalid:
                errors[CONF_DAY_SWITCH_TIME] = "time_format"
            if len(errors) == 0:
                user_input[CONF_RANDOM_FETCH_TIME_OFFSET] = (
                    user_input[CONF_RANDOM_FETCH_TIME_OFFSET]["hours"] * 60
                    + user_input[CONF_RANDOM_FETCH_TIME_OFFSET]["minutes"]
                )
                self._options = user_input

                self._customize_select = user_input.get("customize_select", [])
                self._customize_select_idx = 0
                self._options[CONF_CUSTOMIZE] = {
                    k: v
                    for k, v in self._entry.options.get(CONF_CUSTOMIZE, {}).items()
                    if k not in self._customize_select
                }
                self._sensor_select = user_input.get("sensor_select", [])
                self._sensor_select_idx = 0
                self._options[CONF_SENSORS] = [
                    s
                    for s in self._entry.options.get(CONF_SENSORS, [])
                    if s[CONF_NAME] not in self._sensor_select
                ]
                return await self.async_step_customize()

        return self.async_show_form(step_id="init", data_schema=SCHEMA, errors=errors)

    def get_types_of_sensors_and_customizations(self):
        fetched_types = [
            value.get(CONF_ALIAS, key)
            for key, value in self._entry.options.get(CONF_CUSTOMIZE, {}).items()
        ]
        for c in self._entry.options.get(CONF_SENSORS, []):
            if CONF_COLLECTION_TYPES in c:
                fetched_types.extend(
                    c[CONF_COLLECTION_TYPES]
                    if isinstance(c[CONF_COLLECTION_TYPES], list)
                    else [c[CONF_COLLECTION_TYPES]]
                )
        return list(set(fetched_types))

    async def async_step_customize(self, user_input: dict[str, Any] | None = None):
        if self._customize_select is None or self._customize_select_idx >= len(
            self._customize_select
        ):
            return await self.async_step_sensor()

        defaults = self._entry.options.get(CONF_CUSTOMIZE, {}).get(
            self._customize_select[self._customize_select_idx], {}
        )
        is_new = self._customize_select[
            self._customize_select_idx
        ] not in self._entry.options.get(CONF_CUSTOMIZE, {})
        schema = self.add_suggested_values_to_schema(
            get_customize_schema(defaults, add_delete=not is_new), user_input
        )
        if user_input is not None:
            sectioned_user_input = user_input
            user_input = flatten_section_input(
                sectioned_user_input,
                {
                    SECTION_CUSTOMIZE_BASIC,
                    SECTION_CUSTOMIZE_APPEARANCE,
                    SECTION_CUSTOMIZE_CALENDAR,
                    SECTION_CUSTOMIZE_MANAGEMENT,
                },
            )
            if not user_input.get(
                "delete", False
            ):  # only re-add the (modified) customization if not deleted
                user_input.pop("delete", None)
                self._options[CONF_CUSTOMIZE][
                    self._customize_select[self._customize_select_idx]
                ] = user_input
                self._customize_select_idx += 1
            return await self.async_step_customize()

        return self.async_show_form(
            step_id="customize",
            data_schema=schema,
            description_placeholders={
                "index": str(self._customize_select_idx + 1),
                "total": str(len(self._customize_select)),
                "type": self._customize_select[self._customize_select_idx],
            },
        )

    async def async_step_sensor(self, user_input: dict[str, Any] | None = None):
        if self._sensor_select is None or self._sensor_select_idx >= len(
            self._sensor_select
        ):
            _LOGGER.debug("self._options: %s", self._options)
            return self.async_create_entry(data=self._options)

        # find sensor with the same name
        original_sensor = next(
            (
                x
                for x in self._entry.options.get(CONF_SENSORS, [])
                if x[CONF_NAME] == self._sensor_select[self._sensor_select_idx]
            ),
            None,
        )

        schema = self.add_suggested_values_to_schema(
            get_sensor_schema(
                self.get_types_of_sensors_and_customizations(),
                add_delete=True,
                defaults=original_sensor or {},
            ),
            user_input,
        )
        errors: dict[str, str] = {}
        # is_new = self._sensor_select[self._sensor_select_idx] == "sensor_select_add_new"

        if user_input is not None:
            user_input = flatten_section_input(
                user_input,
                {
                    SECTION_SENSOR_IDENTITY,
                    SECTION_SENSOR_DISPLAY,
                    SECTION_SENSOR_FILTERING,
                    SECTION_SENSOR_MANAGEMENT,
                },
            )
            if user_input and _should_refresh_sensor_form(
                user_input, defaults=original_sensor or {}
            ):
                return self.async_show_form(
                    step_id="sensor",
                    errors=errors,
                    data_schema=self.add_suggested_values_to_schema(
                        get_sensor_schema(
                            self.get_types_of_sensors_and_customizations(),
                            add_delete=True,
                            defaults={**(original_sensor or {}), **user_input},
                        ),
                        user_input,
                    ),
                    description_placeholders={
                        "sensor_number": str(self._sensor_select_idx + 1),
                    },
                )
            if user_input.get(
                "delete", False
            ):  # only re-add the (modified) sensor if not deleted
                self._sensor_select_idx += 1
                return await self.async_step_sensor()

            user_input.pop("delete", None)
            args, errors = validate_sensor_user_input(
                user_input, self._options[CONF_SENSORS]
            )

            if len(errors) == 0:
                self._options[CONF_SENSORS].append(args)
                self._sensor_select_idx += 1
                return await self.async_step_sensor()

        return self.async_show_form(
            step_id="sensor",
            errors=errors,
            data_schema=schema,
            description_placeholders={
                "sensor_number": str(self._sensor_select_idx + 1),
            },
        )


def _get_preview_flow(
    hass: HomeAssistant, flow_type: str, flow_id: str
) -> WasteCollectionConfigFlow | WasteCollectionOptionsFlow:
    """Return the live flow handler for preview generation."""
    manager = (
        hass.config_entries.flow
        if flow_type == "config_flow"
        else hass.config_entries.options
    )

    flow = manager._progress.get(flow_id)  # noqa: SLF001
    if flow is None:
        raise HomeAssistantError("Flow not found")
    return cast(WasteCollectionConfigFlow | WasteCollectionOptionsFlow, flow)


async def _build_preview_context(
    hass: HomeAssistant,
    flow: WasteCollectionConfigFlow | WasteCollectionOptionsFlow,
    flow_type: str,
) -> tuple[
    list[Collection],
    dict[str, dict[str, Any]],
    str | None,
    str,
    datetime.time,
    int,
]:
    """Collect the cached schedule data and display options needed for preview."""
    if flow_type == "config_flow":
        config_flow = cast(WasteCollectionConfigFlow, flow)
        preview_collections = getattr(config_flow, "_preview_collections", None)
        if preview_collections is None:
            raise HomeAssistantError("Preview is not available until source data is loaded")

        options = config_flow._options
        return (
            preview_collections,
            options.get(CONF_CUSTOMIZE, {}),
            options.get(CONF_SOURCE_CALENDAR_TITLE),
            options.get(CONF_SEPARATOR, CONF_SEPARATOR_DEFAULT),
            cv.time(options.get(CONF_DAY_SWITCH_TIME, CONF_DAY_SWITCH_TIME_DEFAULT)),
            options.get(CONF_DAY_OFFSET, CONF_DAY_OFFSET_DEFAULT),
        )

    options_flow = cast(WasteCollectionOptionsFlow, flow)
    preview_collections = await options_flow.async_get_preview_collections()
    options = options_flow._options

    return (
        preview_collections,
        options.get(CONF_CUSTOMIZE, {}),
        options.get(CONF_SOURCE_CALENDAR_TITLE),
        options.get(CONF_SEPARATOR, CONF_SEPARATOR_DEFAULT),
        cv.time(options.get(CONF_DAY_SWITCH_TIME, CONF_DAY_SWITCH_TIME_DEFAULT)),
        options.get(CONF_DAY_OFFSET, CONF_DAY_OFFSET_DEFAULT),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "waste_collection_schedule/start_preview",
        vol.Required("flow_id"): str,
        vol.Required("flow_type"): vol.Any("config_flow", "options_flow"),
        vol.Required("user_input"): dict,
    }
)
@websocket_api.async_response
async def ws_start_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Generate a live preview for the sensor editor."""
    flow = _get_preview_flow(hass, msg["flow_type"], msg["flow_id"])
    raw_user_input = flatten_section_input(
        msg["user_input"],
        {
            SECTION_SENSOR_IDENTITY,
            SECTION_SENSOR_DISPLAY,
            SECTION_SENSOR_FILTERING,
            SECTION_SENSOR_MANAGEMENT,
        },
    )
    if raw_user_input is None:
        raise HomeAssistantError("Preview input is missing")

    sensor_input, errors = get_preview_sensor_input(hass, raw_user_input)
    if errors:
        connection.send_message(
            {
                "id": msg["id"],
                "type": websocket_api.TYPE_RESULT,
                "success": False,
                "error": {"code": "invalid_user_input", "message": errors},
            }
        )
        return

    (
        preview_collections,
        customize_options,
        calendar_title,
        separator,
        day_switch_time,
        day_offset,
    ) = await _build_preview_context(hass, flow, msg["flow_type"])

    preview_shell = build_preview_shell(
        collections=preview_collections,
        customize_options=customize_options,
        calendar_title=calendar_title,
        day_offset=day_offset,
    )
    preview_aggregator = CollectionAggregator([preview_shell])

    try:
        state, attributes, _, _ = render_sensor_preview(
            aggregator=preview_aggregator,
            separator=separator,
            day_switch_time=day_switch_time,
            details_format=sensor_input.get(CONF_DETAILS_FORMAT, DetailsFormat.upcoming),
            count=sensor_input.get(CONF_COUNT),
            leadtime=sensor_input.get(CONF_LEADTIME),
            collection_types=sensor_input.get(CONF_COLLECTION_TYPES),
            value_template=sensor_input.get(CONF_VALUE_TEMPLATE),
            date_template=sensor_input.get(CONF_DATE_TEMPLATE),
            add_days_to=sensor_input.get(CONF_ADD_DAYS_TO, False),
            event_index=sensor_input.get(CONF_EVENT_INDEX),
        )
    except Exception as err:  # noqa: BLE001
        connection.send_result(msg["id"])
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {"error": str(err)},
            )
        )
        connection.subscriptions[msg["id"]] = lambda: None
        return

    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(
            msg["id"],
            {"attributes": attributes, "state": state},
        )
    )
    connection.subscriptions[msg["id"]] = lambda: None
