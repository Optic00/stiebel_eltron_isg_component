"""Tests for the bounded experimental WPM G register subset."""

from modbus_connection.mock import MockModbusConnection, ReadEvent

from custom_components.stiebel_eltron_isg.const import UNIT_ID
from custom_components.stiebel_eltron_isg.sensor import WPMG_SENSOR_TYPES
from custom_components.stiebel_eltron_isg.wpmg import (
    WpmGStiebelEltronAPI,
    WpmGSystemValues,
)


async def test_wpmg_decodes_hardware_backed_input_registers() -> None:
    """FC04 wire addresses, signed scaling and unavailable values stay exact."""
    connection = MockModbusConnection()
    unit = connection.for_unit(UNIT_ID)
    unit.input.update({
        6020: 0xFF9C,
        6021: 2720,
        6022: 2971,
        6023: 0x8000,
        6024: 2938,
        6099: 1500,
        6100: 5562,
    })
    api = WpmGStiebelEltronAPI(unit)

    await api.async_update()

    assert api.system_values.brine_inlet_temperature == -1.0
    assert api.system_values.brine_outlet_temperature == 27.2
    assert api.system_values.condenser_inlet_temperature is None
    assert api.system_values.condenser_outlet_temperature == 29.38
    assert api.system_values.outside_temperature_averaged == 15.0
    assert api.system_values.dhw_temperature_weighted == 55.62
    assert unit.read_events == [
        ReadEvent("input", 6020, 5),
        ReadEvent("input", 6099, 2),
    ]


def test_wpmg_surface_is_read_only_and_matches_sensor_accessors() -> None:
    """The alpha contains no writable field and every sensor accessor resolves."""
    api = WpmGStiebelEltronAPI(MockModbusConnection().for_unit(UNIT_ID))

    assert all(
        not field.writable for field in WpmGSystemValues.declared_fields.values()
    )
    assert all(
        description.modbus_register(api) is None for description in WPMG_SENSOR_TYPES
    )
