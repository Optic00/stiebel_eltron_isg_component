"""Custom integration to integrate stiebel_eltron_isg with Home Assistant.

For more details about this integration, please refer to
https://github.com/pail23/stiebel_eltron_isg
"""

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType
from modbus_connection import ModbusTcpParams
from pystiebeleltron import (
    StiebelEltronModbusError,
    UnknownControllerModelError,
    get_controller_model,
)

from .const import (
    CONF_CONTROLLER_TYPE,
    CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
    DEFAULT_PORT,
    DOMAIN,
    UNIT_ID,
    WPMG_RUN_DIAGNOSTIC,
    ExperimentalControllerModel,
)
from .coordinator import (
    CONTROLLER_FAMILIES,
    ControllerFamily,
    StiebelEltronConfigEntry,
    StiebelEltronDataCoordinator,
    SupportedControllerModel,
    create_api,
)
from .entity import build_unique_id
from .migration import (
    async_migrate_device_identifier,
    async_migrate_unique_ids,
    async_remove_legacy_circulation_pump_switch,
    async_remove_unsupported_wpmsystem_runtime_sensors,
    duplicate_entity_issue_id,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.CLIMATE,
]

# The experimental WPM G is read-only: no button (its reset writes a register),
# number, switch, select or climate platform.
_WPM_G_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_ISSUE_TRACKER = "https://github.com/pail23/stiebel_eltron_isg_component/issues"


def _is_wpm_g(entry: StiebelEltronConfigEntry) -> bool:
    """Return whether the entry was explicitly set up as experimental WPM G."""
    return entry.data.get(CONF_CONTROLLER_TYPE) == CONTROLLER_TYPE_WPM_G_EXPERIMENTAL


def _platforms_for_entry(entry: StiebelEltronConfigEntry) -> list[Platform]:
    """Return the platforms the entry's controller family loads."""
    return _WPM_G_PLATFORMS if _is_wpm_g(entry) else _PLATFORMS


@callback
def _async_remove_wpm_g_diagnostic_button(
    hass: HomeAssistant, entry: StiebelEltronConfigEntry
) -> None:
    """Remove the registry entry of the alpha 3 scan button, which is gone."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.BUTTON, DOMAIN, build_unique_id(entry, WPMG_RUN_DIAGNOSTIC)
    )
    if entity_id is not None:
        registry.async_remove(entity_id)


def _unsupported_controller_issue_id(entry: StiebelEltronConfigEntry) -> str:
    """Return the stable repair issue id for a config entry."""
    return f"unsupported_controller_{entry.entry_id}"


def _create_unsupported_controller_issue(
    hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
    model_id: object,
) -> None:
    """Tell the user how to handle a controller without integration support."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _unsupported_controller_issue_id(entry),
        is_fixable=False,
        learn_more_url=_ISSUE_TRACKER,
        severity=ir.IssueSeverity.ERROR,
        translation_key="unsupported_controller",
        translation_placeholders={"model_id": str(model_id)},
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
) -> bool:
    """Set up this integration using UI."""

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    try:
        unit = async_get_unit(
            hass,
            entry,
            ModbusTcpParams(host=host, port=port),
            UNIT_ID,
        )
    except HomeAssistantError as exception:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="modbus_setup_failed",
            translation_placeholders={"error": str(exception)},
        ) from exception

    model: SupportedControllerModel
    if _is_wpm_g(entry):
        # The WPM G refuses the controller id register, so detection would fail.
        model = ExperimentalControllerModel.WPM_G
        family = ControllerFamily.WPM_G
    else:
        try:
            model = await get_controller_model(unit)
        except StiebelEltronModbusError as exception:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="controller_read_failed",
                translation_placeholders={"error": str(exception)},
            ) from exception
        except UnknownControllerModelError as exception:
            # An unrecognised controller id is a permanent condition, not a
            # transient modbus glitch: fail cleanly instead of retrying forever.
            # Adding support requires a pystiebeleltron update, which reloads the
            # entry anyway.
            _create_unsupported_controller_issue(hass, entry, exception.model_id)
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="unsupported_controller",
                translation_placeholders={"model_id": str(exception.model_id)},
            ) from exception

        detected_family = CONTROLLER_FAMILIES.get(model)
        if detected_family is None:
            # The library knows the model, this integration does not yet.
            _create_unsupported_controller_issue(hass, entry, model.value)
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="unsupported_controller",
                translation_placeholders={"model_id": str(model.value)},
            )
        family = detected_family
    coordinator = StiebelEltronDataCoordinator(
        hass, entry, create_api(family, unit), model, host
    )

    # A library and integration update can add the model while this repair still
    # exists from an earlier setup attempt.
    ir.async_delete_issue(hass, DOMAIN, _unsupported_controller_issue_id(entry))

    if isinstance(model, ExperimentalControllerModel):
        # The WPM G has no entities from before the unique id scheme and none of
        # the model specific ones the migrations below look for.
        _async_remove_wpm_g_diagnostic_button(hass, entry)
    else:
        # Both have to run before the platforms are set up, so that the entities
        # are added to the registry entries and the device that already carry
        # their new identifiers.
        async_migrate_device_identifier(hass, entry)
        # Before the unique id migration, so that an entity about to be deleted
        # is never planned, never counted as a duplicate, and never reported by
        # the Repair the migration raises for the duplicates it finds.
        async_remove_unsupported_wpmsystem_runtime_sensors(hass, entry, model)
        await async_migrate_unique_ids(hass, entry, model)
        async_remove_legacy_circulation_pump_switch(hass, entry, model)

    entry.runtime_data = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as exception:
        # The coordinator wraps its first update failure without translation
        # metadata. Keep the cause chain and expose a translated setup reason.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="initial_read_failed",
            translation_placeholders={"error": str(exception)},
        ) from exception

    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )


async def async_remove_entry(
    hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
) -> None:
    """Remove repairs that belong to a deleted config entry."""
    ir.async_delete_issue(hass, DOMAIN, _unsupported_controller_issue_id(entry))
    ir.async_delete_issue(hass, DOMAIN, duplicate_entity_issue_id(entry))
