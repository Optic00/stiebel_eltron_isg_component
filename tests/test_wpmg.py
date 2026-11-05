"""Tests for the experimental, read-only WPM G support."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.json import ExtendedJSONEncoder
from modbus_connection import IllegalDataAddressError, ModbusConnectionError
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
from pystiebeleltron.wpmg import (
    WpmGAlarms,
    WpmGStiebelEltronAPI,
    WpmGSystemState,
    WpmGSystemValues,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stiebel_eltron_isg import _platforms_for_entry
from custom_components.stiebel_eltron_isg.binary_sensor import WPMG_BINARY_SENSOR_TYPES
from custom_components.stiebel_eltron_isg.const import (
    CONF_CONTROLLER_TYPE,
    CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
    DOMAIN,
    UNIT_ID,
    WPMG_RUN_DIAGNOSTIC,
    ExperimentalControllerModel,
)
from custom_components.stiebel_eltron_isg.coordinator import (
    ControllerFamily,
    coordinator_display_name,
    create_api,
)
from custom_components.stiebel_eltron_isg.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.stiebel_eltron_isg.entity import build_unique_id
from custom_components.stiebel_eltron_isg.sensor import WPMG_SENSOR_TYPES
from custom_components.stiebel_eltron_isg.wpmg_entities import (
    WPMG_MEASUREMENTS,
    WPMG_STATUSES,
)

CAPTURE = Path(__file__).parent / "fixtures" / "wpmg_primary_capture.json"
ALARM_REGISTERS = range(8999, 9063)
STATE_REGISTERS = range(7499, 7700)
DEFAULT_ENABLED_KEYS = {
    "wpmg_outside_temperature_averaged",
    "wpmg_dhw_temperature_weighted",
    "wpmg_brine_inlet_temperature",
    "wpmg_brine_outlet_temperature",
    "wpmg_condenser_inlet_temperature",
    "wpmg_condenser_outlet_temperature",
}
# The eleven FC04 reads of one poll, in the order the library issues them.
POLL_PLAN = [
    (6000, 34),
    (6099, 21),
    (6123, 5),
    (7499, 9),
    (7599, 5),
    (7649, 4),
    (7654, 3),
    (7659, 2),
    (7662, 1),
    (7699, 1),
    (8999, 64),
]


def _capture() -> dict[str, Any]:
    """Return the public alpha 3 poll: raw words with their decoded values."""
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def _load_capture(unit: MockModbusUnit) -> None:
    """Make the unit answer with the captured registers."""
    unit.input.update({address: raw for address, _, raw, _ in _capture()["rows"]})


def _wpm_g_entry(**extra: Any) -> MockConfigEntry:
    """Return an entry as the config flow stores an explicit WPM G choice."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Stiebel Eltron",
        data={
            CONF_HOST: "private-isg.example.internal",
            CONF_PORT: 502,
            CONF_CONTROLLER_TYPE: CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
            **extra,
        },
        entry_id="wpmg_entry",
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up and let its entities settle."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, domain: str, entry: MockConfigEntry, key: str):
    """Return the entity id of an entry's entity, or None."""
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, build_unique_id(entry, key)
    )


def _refuse(unit: MockModbusUnit, registers: range) -> None:
    """Make the controller refuse every read that touches ``registers``."""
    for address in range(registers.start - 200, registers.stop):
        unit.fail_read(address, IllegalDataAddressError(), register_type="input")


async def test_capture_decodes_with_the_real_library(
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """Every captured word decodes to the value published with it, read-only."""
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    _load_capture(unit)
    writes: list[Any] = []
    unit.on_write(writes.append)
    api = create_api(ControllerFamily.WPM_G, unit)
    assert isinstance(api, WpmGStiebelEltronAPI)

    await api.async_update()

    assert [(event.address, event.count) for event in unit.read_events] == POLL_PLAN
    assert {event.register_type for event in unit.read_events} == {"input"}
    assert not writes
    assert api.dropped_optional_components == ()
    for _, field, _, expected in _capture()["rows"]:
        component, name = field.split(".", 1)
        actual = getattr(getattr(api, component), name)
        if expected is None or isinstance(expected, bool):
            assert actual is expected, field
        else:
            assert actual == pytest.approx(expected), field


def test_catalogue_covers_exactly_the_library_fields() -> None:
    """A field the library adds or drops has to be added or dropped here."""
    library = {
        (component, name)
        for component, model in (
            ("system_values", WpmGSystemValues),
            ("system_state", WpmGSystemState),
            ("alarms", WpmGAlarms),
        )
        for name in model.declared_fields
    }
    catalogue = {(component, name) for component, name, _ in WPMG_MEASUREMENTS} | set(
        WPMG_STATUSES
    )

    assert catalogue == library
    assert len(WPMG_SENSOR_TYPES) == 55
    assert len(WPMG_BINARY_SENSOR_TYPES) == 94
    assert all(
        not field.writable
        for model in (WpmGSystemValues, WpmGSystemState, WpmGAlarms)
        for field in model.declared_fields.values()
    )


def test_entity_units_and_defaults() -> None:
    """Six temperatures are on by default, differences are not temperatures."""
    sensors = {description.key: description for description in WPMG_SENSOR_TYPES}

    assert {
        key
        for key, description in sensors.items()
        if description.entity_registry_enabled_default
    } == DEFAULT_ENABLED_KEYS
    assert not any(
        description.entity_registry_enabled_default
        for description in WPMG_BINARY_SENSOR_TYPES
    )
    for key in ("wpmg_superheating", "wpmg_supercooling"):
        assert sensors[key].native_unit_of_measurement == "K"
        assert sensors[key].device_class is None
    assert sensors["wpmg_l1_current"].device_class is SensorDeviceClass.CURRENT
    assert sensors["wpmg_l1_n_voltage"].device_class is SensorDeviceClass.VOLTAGE
    assert sensors["wpmg_l1_power_consumption"].device_class is SensorDeviceClass.POWER
    assert (
        sensors["wpmg_pressure_low_pressure_side"].device_class
        is SensorDeviceClass.PRESSURE
    )


def test_family_naming_and_platforms() -> None:
    """The model keeps the names alpha 3 gave the device."""
    model = ExperimentalControllerModel.WPM_G

    assert model.name == "WPM_G"
    assert model.value == CONTROLLER_TYPE_WPM_G_EXPERIMENTAL
    assert coordinator_display_name(model) == "Stiebel Eltron WPM G (experimental)"
    assert [str(platform) for platform in _platforms_for_entry(_wpm_g_entry())] == [
        "sensor",
        "binary_sensor",
    ]


async def test_setup_is_read_only_and_skips_model_detection(
    hass: HomeAssistant,
    mock_get_controller_model: MagicMock,
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """WPM G loads two platforms, never reads the model and never writes."""
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    _load_capture(unit)
    writes: list[Any] = []
    unit.on_write(writes.append)
    entry = _wpm_g_entry()

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    mock_get_controller_model.assert_not_called()
    assert not writes
    assert {event.register_type for event in unit.read_events} == {"input"}
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {entity.domain for entity in entities} == {"sensor", "binary_sensor"}
    assert {entity.unique_id for entity in entities} == {
        build_unique_id(entry, description.key)
        for description in [*WPMG_SENSOR_TYPES, *WPMG_BINARY_SENSOR_TYPES]
    }
    enabled = {entity.unique_id for entity in entities if not entity.disabled}
    assert enabled == {build_unique_id(entry, key) for key in DEFAULT_ENABLED_KEYS}
    condenser_inlet = hass.states.get(
        _entity_id(hass, "sensor", entry, "wpmg_condenser_inlet_temperature")
    )
    assert condenser_inlet is not None
    assert float(condenser_inlet.state) == pytest.approx(
        next(
            expected
            for _, field, _, expected in _capture()["rows"]
            if field == "system_values.condenser_inlet_temperature"
        )
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    assert device.model == "WPM_G"
    assert device.name == "Stiebel Eltron WPM G (experimental)"


async def test_reset_is_refused_for_wpm_g(
    hass: HomeAssistant, mock_modbus_connection: MockModbusConnection
) -> None:
    """The reset path of the other families must not reach a WPM G."""
    _load_capture(mock_modbus_connection.for_unit(UNIT_ID))
    entry = _wpm_g_entry()
    await _setup(hass, entry)

    with pytest.raises(HomeAssistantError) as exception_info:
        await entry.runtime_data.async_reset_heatpump()

    assert exception_info.value.translation_key == "write_unsupported"


# The refused registers, the dropped component, an entity of it and one of a
# block that is still served.
_REFUSED_BLOCKS = [
    (
        ALARM_REGISTERS,
        "WpmGAlarms",
        "wpmg_level_1_notification",
        "wpmg_heat_pump_off",
    ),
    (
        STATE_REGISTERS,
        "WpmGSystemState",
        "wpmg_control_signal_compressor",
        "wpmg_level_1_notification",
    ),
]


@pytest.mark.parametrize("block", _REFUSED_BLOCKS)
async def test_block_the_controller_never_served_is_unavailable_not_off(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    block: tuple[range, str, str, str],
) -> None:
    """A refused optional block must never read as "off" or "no alarm"."""
    refused, dropped, block_key, served_key = block
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    _load_capture(unit)
    for address in refused:
        unit.input.pop(address, None)
    _refuse(unit, refused)
    entry = _wpm_g_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Opt-in entities the user enabled.
    for key in (block_key, served_key):
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            build_unique_id(entry, key),
            config_entry=entry,
            suggested_object_id=key,
        )

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.dropped_optional_components == (dropped,)
    unserved = hass.states.get(_entity_id(hass, "binary_sensor", entry, block_key))
    assert unserved is not None
    assert unserved.state == STATE_UNAVAILABLE
    # The block that is served keeps answering.
    served = hass.states.get(_entity_id(hass, "binary_sensor", entry, served_key))
    assert served is not None
    assert served.state in ("on", "off")


async def test_failed_update_makes_every_entity_unavailable(
    hass: HomeAssistant, mock_modbus_connection: MockModbusConnection
) -> None:
    """A lost connection must not keep presenting cached values as current."""
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    _load_capture(unit)
    entry = _wpm_g_entry()
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "sensor", entry, "wpmg_brine_inlet_temperature")
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    unit.fail_read(6000, ModbusConnectionError("lost"), register_type="input")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_alpha_3_entry_upgrades_in_place(
    hass: HomeAssistant,
    mock_get_controller_model: MagicMock,
    mock_modbus_connection_class: MagicMock,
) -> None:
    """An entry from the alpha 3 builds keeps its entities and loses its button."""

    def new_connection(*_args: Any, **_kwargs: Any) -> MockModbusConnection:
        # Unloading closes a connection for good, so a reload needs a new one.
        connection = MockModbusConnection()
        _load_capture(connection.for_unit(UNIT_ID))
        return connection

    mock_modbus_connection_class.side_effect = new_connection
    entry = _wpm_g_entry()
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Stiebel Eltron WPM G (experimental)",
        manufacturer="Stiebel Eltron",
        model="WPM_G",
    )
    registry = er.async_get(hass)

    def stored(domain: str, key: str, **kwargs: Any) -> er.RegistryEntry:
        return registry.async_get_or_create(
            domain,
            DOMAIN,
            build_unique_id(entry, key),
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"stiebel_eltron_wpm_g_experimental_{key}",
            **kwargs,
        )

    kept_default = stored("sensor", "wpmg_brine_inlet_temperature")
    # Disabled by the user although it is on by default.
    disabled_by_user = stored(
        "sensor",
        "wpmg_condenser_outlet_temperature",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    # Enabled by the user although it is opt-in.
    enabled_by_user = stored("sensor", "wpmg_pressure_high_pressure_side")
    enabled_alarm = stored("binary_sensor", "wpmg_level_2_notification")
    untouched_opt_in = stored(
        "binary_sensor",
        "wpmg_heat_pump_off",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    button = stored("button", WPMG_RUN_DIAGNOSTIC)
    assert registry.async_get(button.entity_id) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_get_controller_model.assert_not_called()
    assert entry.state is ConfigEntryState.LOADED
    assert registry.async_get(button.entity_id) is None
    assert hass.states.get(button.entity_id) is None
    assert (
        len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 1
    )
    for before in (
        kept_default,
        disabled_by_user,
        enabled_by_user,
        enabled_alarm,
        untouched_opt_in,
    ):
        after = registry.async_get(before.entity_id)
        assert after is not None
        assert after.unique_id == before.unique_id
        assert after.disabled_by == before.disabled_by
        assert after.device_id == device.id
    assert hass.states.get(kept_default.entity_id).state != STATE_UNAVAILABLE
    assert hass.states.get(enabled_by_user.entity_id) is not None
    assert hass.states.get(enabled_alarm.entity_id).state == "off"
    assert hass.states.get(disabled_by_user.entity_id) is None
    assert hass.states.get(untouched_opt_in.entity_id) is None
    assert not [
        entity
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.domain == "button"
    ]

    # Reload, reconfigure and unload keep working on the upgraded entry.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(kept_default.entity_id).state != STATE_UNAVAILABLE

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "other.example.internal", CONF_PORT: 502}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_HOST] == "other.example.internal"
    assert entry.data[CONF_CONTROLLER_TYPE] == CONTROLLER_TYPE_WPM_G_EXPERIMENTAL

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(kept_default.entity_id).state != STATE_UNAVAILABLE
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_are_cached_redacted_and_leak_no_error_text(
    hass: HomeAssistant, mock_modbus_connection: MockModbusConnection
) -> None:
    """Diagnostics read the cache, redact the host and name only the error class."""
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    _load_capture(unit)
    for address in ALARM_REGISTERS:
        unit.input.pop(address, None)
    _refuse(unit, ALARM_REGISTERS)
    entry = _wpm_g_entry()
    await _setup(hass, entry)
    reads_before = len(unit.read_events)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert len(unit.read_events) == reads_before
    assert diagnostics == await async_get_device_diagnostics(hass, entry, MagicMock())
    assert diagnostics["config_entry"][CONF_HOST] == "**REDACTED**"
    assert diagnostics["config_entry"][CONF_CONTROLLER_TYPE] == (
        CONTROLLER_TYPE_WPM_G_EXPERIMENTAL
    )
    values, model = diagnostics["data"]
    assert model == {"model": "WPM_G", "model_id": CONTROLLER_TYPE_WPM_G_EXPERIMENTAL}
    assert values["outside_temperature_averaged"] == "19.49 °C"
    assert values["level_1_notification"] == "—"
    assert diagnostics["wpmg"] == {
        "controller_family": "wpm_g",
        "last_update_success": True,
        "dropped_optional_components": ["WpmGAlarms"],
    }

    unit.fail_read(
        6000, ModbusConnectionError("secret-detail 192.0.2.7"), register_type="input"
    )
    await entry.runtime_data.async_refresh()
    failed = await async_get_config_entry_diagnostics(hass, entry)

    assert failed["wpmg"]["last_update_success"] is False
    assert failed["wpmg"]["last_update_error"] == "ModbusConnectionError"
    downloaded = json.dumps(failed, cls=ExtendedJSONEncoder)
    assert "secret-detail" not in downloaded
    assert "192.0.2.7" not in downloaded
    assert "private-isg.example.internal" not in downloaded
    assert len(unit.read_events) >= reads_before
