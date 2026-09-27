"""Tests for the bounded experimental WPM G register subset."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import (
    GatewayPathUnavailableError,
    GatewayTargetError,
    IllegalDataAddressError,
    ModbusConnectionError,
)
from modbus_connection.mock import MockModbusConnection, ReadEvent
from pystiebeleltron.wpmg import WpmGStiebelEltronAPI, WpmGSystemValues
import pytest

from custom_components.stiebel_eltron_isg.binary_sensor import (
    WPMG_BINARY_SENSOR_TYPES,
    StiebelEltronISGBinarySensor,
)
from custom_components.stiebel_eltron_isg.const import UNIT_ID
from custom_components.stiebel_eltron_isg.sensor import WPMG_SENSOR_TYPES
from custom_components.stiebel_eltron_isg.wpmg import (
    WPMG_DOCUMENTED_INPUT_REFERENCES,
    StiebelEltronModbusWpmGDataCoordinator,
    WpmGDiagnostics,
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
        ReadEvent("input", address, count)
        for address, count in [
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
    writes = []
    unit.on_write(writes.append)
    first_wire_address = WPMG_DOCUMENTED_INPUT_REFERENCES[0] - 30001
    unit.input[first_wire_address] = 0xFFFF
    api = WpmGDiagnostics(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    assert len(WPMG_DOCUMENTED_INPUT_REFERENCES) == 163
    assert unit.read_events == [
        ReadEvent("input", reference - 30001, 1)
        for reference in WPMG_DOCUMENTED_INPUT_REFERENCES
    ]
    assert report["function_code"] == 4
    assert report["status"] == "completed"
    assert report["completed"] is True
    assert report["aborted"] is False
    assert report["register_count"] == 163
    assert report["successful_registers"] == 163
    assert report["failed_registers"] == 0
    assert report["skipped_registers"] == 0
    assert report["registers"][0] == {
        "documented_reference": 36000,
        "primary_address": 6000,
        "wire_address": 5999,
        "status": "ok",
        "raw_u16": 0xFFFF,
        "raw_hex": "0xFFFF",
        "timestamp_utc": report["registers"][0]["timestamp_utc"],
    }
    assert not writes
    json.dumps(report)


async def test_wpmg_diagnostic_records_errors_per_register() -> None:
    """One rejected address must not hide the remaining diagnostic results."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    unit.fail_read(6000, IllegalDataAddressError(), register_type="input")
    api = WpmGDiagnostics(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    failed = [row for row in report["registers"] if row["status"] == "error"]
    assert failed == [
        {
            "documented_reference": 36001,
            "primary_address": 6001,
            "wire_address": 6000,
            "status": "error",
            "error_type": "IllegalDataAddressError",
            "exception_code": 2,
            "timestamp_utc": failed[0]["timestamp_utc"],
        }
    ]
    assert report["status"] == "completed"
    assert report["successful_registers"] == 162
    assert report["failed_registers"] == 1
    assert report["skipped_registers"] == 0


async def test_wpmg_diagnostic_aborts_after_three_communication_errors() -> None:
    """A dead link cannot cause one timeout for every documented register."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    for wire_address in (5999, 6000, 6001):
        unit.fail_read(
            wire_address,
            ModbusConnectionError("connection lost"),
            register_type="input",
        )
    api = WpmGDiagnostics(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    assert unit.read_events == [
        ReadEvent("input", 5999, 1),
        ReadEvent("input", 6000, 1),
        ReadEvent("input", 6001, 1),
    ]
    assert report["status"] == "aborted"
    assert report["completed"] is False
    assert report["aborted"] is True
    assert report["abort_reason"] == "consecutive_communication_errors"
    assert report["successful_registers"] == 0
    assert report["failed_registers"] == 3
    assert report["skipped_registers"] == 160
    assert len(report["registers"]) == 163


@pytest.mark.parametrize(
    "gateway_error",
    [GatewayPathUnavailableError(), GatewayTargetError()],
)
async def test_wpmg_diagnostic_counts_gateway_errors_as_communication_failures(
    gateway_error: Exception,
) -> None:
    """Gateway failures behind the ISG stop the scan after three responses."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    for wire_address in (5999, 6000, 6001):
        unit.fail_read(wire_address, gateway_error, register_type="input")
    api = WpmGDiagnostics(unit)

    report = await api.async_run_diagnostic(message_spacing=0)

    assert report["status"] == "aborted"
    assert report["abort_reason"] == "consecutive_communication_errors"
    assert report["failed_registers"] == 3
    assert report["skipped_registers"] == 160
    assert [row["exception_code"] for row in report["registers"][:3]] == [
        gateway_error.exception_code
    ] * 3


async def test_wpmg_diagnostic_has_an_overall_timeout() -> None:
    """The complete scan remains time-bounded even if one request hangs."""

    async def read_input_registers(_address: int, _count: int) -> list[int]:
        await asyncio.sleep(60)
        return [0]

    api = WpmGDiagnostics(SimpleNamespace(read_input_registers=read_input_registers))

    report = await api.async_run_diagnostic(
        message_spacing=0,
        total_timeout=0.01,
    )

    assert report["status"] == "aborted"
    assert report["abort_reason"] == "overall_timeout"
    assert report["successful_registers"] == 0
    assert report["failed_registers"] == 1
    assert report["skipped_registers"] == 162
    assert report["registers"][0]["error_type"] == "DiagnosticTimeoutError"


async def test_wpmg_diagnostic_retains_partial_report_when_cancelled() -> None:
    """A cancelled coordinator run retains its live and final partial report."""
    second_read_started = asyncio.Event()
    never_finish = asyncio.Event()
    calls = 0

    async def read_input_registers(_address: int, _count: int) -> list[int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [42]
        second_read_started.set()
        await never_finish.wait()
        return [0]

    coordinator = StiebelEltronModbusWpmGDataCoordinator.__new__(
        StiebelEltronModbusWpmGDataCoordinator
    )
    coordinator._diagnostics = WpmGDiagnostics(
        SimpleNamespace(read_input_registers=read_input_registers)
    )
    coordinator._diagnostic_lock = asyncio.Lock()
    coordinator._io_lock = asyncio.Lock()
    coordinator._last_diagnostic_report = None
    task = asyncio.create_task(coordinator.async_run_wpmg_diagnostic())
    await second_read_started.wait()
    report = coordinator.diagnostic_report
    assert report is not None
    assert report["status"] == "running"
    assert report["successful_registers"] == 1
    assert report["failed_registers"] == 0

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert report["status"] == "cancelled"
    assert report["abort_reason"] == "cancelled"
    assert report["successful_registers"] == 1
    assert report["failed_registers"] == 1
    assert report["skipped_registers"] == 161
    assert report["registers"][0]["raw_u16"] == 42
    assert report["registers"][1]["error_type"] == "CancelledError"


async def test_wpmg_diagnostic_retains_partial_report_on_unexpected_error() -> None:
    """An unexpected read failure finalizes the report before propagating."""
    calls = 0

    async def read_input_registers(_address: int, _count: int) -> list[int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [42]
        raise RuntimeError("private transport detail")

    api = WpmGDiagnostics(SimpleNamespace(read_input_registers=read_input_registers))
    report: dict = {}

    with pytest.raises(RuntimeError, match="private transport detail"):
        await api.async_run_diagnostic(message_spacing=0, report=report)

    assert report["status"] == "error"
    assert report["abort_reason"] == "unexpected_error"
    assert report["successful_registers"] == 1
    assert report["failed_registers"] == 1
    assert report["skipped_registers"] == 161
    assert report["registers"][1]["error_type"] == "RuntimeError"
    assert "private transport detail" not in json.dumps(report)


async def test_wpmg_diagnostic_rejects_overlapping_runs() -> None:
    """A second button press cannot start another register survey."""
    started = asyncio.Event()
    finish = asyncio.Event()

    async def run_diagnostic(*, report: dict) -> dict:
        started.set()
        await finish.wait()
        report["report_version"] = 2
        return report

    coordinator = StiebelEltronModbusWpmGDataCoordinator.__new__(
        StiebelEltronModbusWpmGDataCoordinator
    )
    coordinator._diagnostics = SimpleNamespace(async_run_diagnostic=run_diagnostic)
    coordinator._api = SimpleNamespace(retry_failed_registers=Mock())
    coordinator._diagnostic_lock = asyncio.Lock()
    coordinator._io_lock = asyncio.Lock()
    coordinator._last_diagnostic_report = None
    first_run = asyncio.create_task(coordinator.async_run_wpmg_diagnostic())
    await started.wait()

    with pytest.raises(HomeAssistantError) as exception_info:
        await coordinator.async_run_wpmg_diagnostic()

    assert exception_info.value.translation_key == "wpmg_diagnostic_in_progress"
    finish.set()
    await first_run
    assert coordinator.diagnostic_report == {"report_version": 2}
    coordinator._api.retry_failed_registers.assert_called_once_with()


def test_wpmg_entity_units_and_defaults() -> None:
    """Differences avoid absolute-temperature conversion; new fields are opt-in."""
    descriptions = {description.key: description for description in WPMG_SENSOR_TYPES}
    assert len(descriptions) == 55
    assert len(WPMG_BINARY_SENSOR_TYPES) == 94
    assert (
        sum(
            description.entity_registry_enabled_default
            for description in descriptions.values()
        )
        == 6
    )
    assert all(
        not description.entity_registry_enabled_default
        for description in WPMG_BINARY_SENSOR_TYPES
    )
    for key in ("wpmg_superheating", "wpmg_supercooling"):
        assert descriptions[key].native_unit_of_measurement == "K"
        assert descriptions[key].device_class is None
    assert descriptions["wpmg_l1_current"].device_class is SensorDeviceClass.CURRENT
    assert descriptions["wpmg_l1_n_voltage"].device_class is SensorDeviceClass.VOLTAGE
    assert (
        descriptions["wpmg_l1_power_consumption"].device_class
        is SensorDeviceClass.POWER
    )
    assert (
        descriptions["wpmg_pressure_low_pressure_side"].device_class
        is SensorDeviceClass.PRESSURE
    )


@pytest.mark.parametrize(
    ("raw", "available", "state"),
    [
        (0, True, False),
        (1, True, True),
        (2, False, False),
        (0x8000, False, False),
        (0xFFFF, False, False),
    ],
)
async def test_wpmg_invalid_alarm_is_unavailable(raw, available, state) -> None:
    """A non-boolean code must never present a false all-clear to HA."""
    unit = MockModbusConnection().for_unit(UNIT_ID)
    unit.input[8999] = raw
    api = WpmGStiebelEltronAPI(unit)
    await api.async_update()
    description = next(
        item
        for item in WPMG_BINARY_SENSOR_TYPES
        if item.key == "wpmg_level_1_notification"
    )
    entity = StiebelEltronISGBinarySensor.__new__(StiebelEltronISGBinarySensor)
    entity.modbus_register = description.modbus_register
    entity.bit_number = description.bit_number
    entity.coordinator = SimpleNamespace(
        last_update_success=True,
        get_value=lambda accessor: accessor(api),
        has_value=lambda accessor: accessor(api) is not None,
    )
    assert entity.available is available
    assert entity.is_on is state
    entity.coordinator.last_update_success = False
    assert entity.available is False


async def test_wpmg_poll_waits_until_manual_scan_finishes() -> None:
    """Waiting for a scan must not consume the normal API polling deadline."""
    started, finish = asyncio.Event(), asyncio.Event()

    async def scan(*, report):
        started.set()
        await finish.wait()

    coordinator = StiebelEltronModbusWpmGDataCoordinator.__new__(
        StiebelEltronModbusWpmGDataCoordinator
    )
    coordinator._diagnostic_lock = asyncio.Lock()
    coordinator._io_lock = asyncio.Lock()
    coordinator._refresh_generation = 0
    coordinator._api = SimpleNamespace(
        async_update=AsyncMock(), retry_failed_registers=Mock()
    )
    coordinator._diagnostics = SimpleNamespace(async_run_diagnostic=scan)
    scan_task = asyncio.create_task(coordinator.async_run_wpmg_diagnostic())
    await started.wait()
    poll_task = asyncio.create_task(coordinator._async_update_data())
    await asyncio.sleep(0)
    coordinator._api.async_update.assert_not_called()
    finish.set()
    await asyncio.gather(scan_task, poll_task)
    coordinator._api.async_update.assert_awaited_once()
