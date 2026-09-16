"""Tests for the bounded experimental WPM G register subset."""

import asyncio
import json
from types import SimpleNamespace

from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError
from modbus_connection.mock import MockModbusConnection, ReadEvent
import pytest

from custom_components.stiebel_eltron_isg.const import UNIT_ID
from custom_components.stiebel_eltron_isg.sensor import WPMG_SENSOR_TYPES
from custom_components.stiebel_eltron_isg.wpmg import (
    WPMG_DOCUMENTED_INPUT_REFERENCES,
    StiebelEltronModbusWpmGDataCoordinator,
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


async def test_wpmg_diagnostic_reads_each_documented_input_once() -> None:
    """The one-shot diagnostic uses FC04 only and remains JSON serializable."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    first_wire_address = WPMG_DOCUMENTED_INPUT_REFERENCES[0] - 30001
    unit.input[first_wire_address] = 0xFFFF
    api = WpmGStiebelEltronAPI(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    assert len(WPMG_DOCUMENTED_INPUT_REFERENCES) == 163
    assert unit.read_events == [
        ReadEvent("input", reference - 30001, 1)
        for reference in WPMG_DOCUMENTED_INPUT_REFERENCES
    ]
    assert report["function_code"] == 4
    assert report["register_count"] == 163
    assert report["successful_registers"] == 163
    assert report["failed_registers"] == 0
    assert report["registers"][0] == {
        "documented_reference": 36000,
        "primary_address": 6000,
        "wire_address": 5999,
        "status": "ok",
        "raw_u16": 0xFFFF,
        "raw_hex": "0xFFFF",
        "timestamp_utc": report["registers"][0]["timestamp_utc"],
    }
    json.dumps(report)


async def test_wpmg_diagnostic_records_errors_per_register() -> None:
    """One rejected address must not hide the remaining diagnostic results."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    unit.fail_read(6000, ModbusError("unsupported"), register_type="input")
    api = WpmGStiebelEltronAPI(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    failed = [row for row in report["registers"] if row["status"] == "error"]
    assert failed == [
        {
            "documented_reference": 36001,
            "primary_address": 6001,
            "wire_address": 6000,
            "status": "error",
            "error_type": "ModbusError",
            "timestamp_utc": failed[0]["timestamp_utc"],
        }
    ]
    assert report["successful_registers"] == 162
    assert report["failed_registers"] == 1


async def test_wpmg_diagnostic_rejects_overlapping_runs() -> None:
    """A second button press cannot start another register survey."""
    started = asyncio.Event()
    finish = asyncio.Event()

    async def run_diagnostic() -> dict[str, int]:
        started.set()
        await finish.wait()
        return {"report_version": 1}

    coordinator = StiebelEltronModbusWpmGDataCoordinator.__new__(
        StiebelEltronModbusWpmGDataCoordinator
    )
    coordinator._api = SimpleNamespace(async_run_diagnostic=run_diagnostic)
    coordinator._diagnostic_lock = asyncio.Lock()
    coordinator._last_diagnostic_report = None
    first_run = asyncio.create_task(coordinator.async_run_wpmg_diagnostic())
    await started.wait()

    with pytest.raises(HomeAssistantError) as exception_info:
        await coordinator.async_run_wpmg_diagnostic()

    assert exception_info.value.translation_key == "wpmg_diagnostic_in_progress"
    finish.set()
    await first_run
    assert coordinator.diagnostic_report == {"report_version": 1}
