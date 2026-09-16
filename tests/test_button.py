"""Tests for the button platform."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from modbus_connection import ModbusError
from modbus_connection.mock import MockModbusConnection
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stiebel_eltron_isg.button import StiebelEltronISGButtonEntity
from custom_components.stiebel_eltron_isg.const import (
    CONF_CONTROLLER_TYPE,
    CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
    DOMAIN,
    RESET_HEATPUMP,
    UNIT_ID,
    WPMG_RUN_DIAGNOSTIC,
)
from custom_components.stiebel_eltron_isg.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.stiebel_eltron_isg.entity import build_unique_id


@pytest.mark.parametrize("last_update_success", [True, False])
def test_reset_button_availability_follows_coordinator(
    last_update_success: bool,
) -> None:
    """The reset action must not be offered while the device is unavailable."""
    entity = StiebelEltronISGButtonEntity.__new__(StiebelEltronISGButtonEntity)
    entity.coordinator = SimpleNamespace(last_update_success=last_update_success)

    assert entity.available is last_update_success


async def test_reset_button_becomes_unavailable_after_failed_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wpm_api: MagicMock,
) -> None:
    """A failed coordinator refresh is reflected in the HA entity state."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "button",
        DOMAIN,
        build_unique_id(mock_config_entry, RESET_HEATPUMP),
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    mock_wpm_api.async_update.side_effect = ModbusError("update failed")
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_wpmg_diagnostic_button_stores_completed_report(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """The WPM G button runs the real FC04 scan and exports its report."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Stiebel Eltron WPM G",
        data={
            CONF_HOST: "1.1.1.1",
            CONF_PORT: 502,
            CONF_CONTROLLER_TYPE: CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    unit = mock_modbus_connection.for_unit(UNIT_ID)
    unit.read_events.clear()
    writes = []
    unit.on_write(writes.append)
    api = entry.runtime_data._api
    real_diagnostic = api.async_run_diagnostic

    async def run_diagnostic(*, report: dict) -> dict:
        return await real_diagnostic(message_spacing=0, report=report)

    diagnostic = AsyncMock(side_effect=run_diagnostic)
    api.async_run_diagnostic = diagnostic
    entity_id = er.async_get(hass).async_get_entity_id(
        "button",
        DOMAIN,
        build_unique_id(entry, WPMG_RUN_DIAGNOSTIC),
    )
    assert entity_id is not None

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    diagnostic.assert_awaited_once()
    report = entry.runtime_data.diagnostic_report
    assert report is not None
    assert report["status"] == "completed"
    assert report["register_count"] == 163
    assert len(unit.read_events) == 163
    assert all(event.register_type == "input" for event in unit.read_events)
    assert not writes
    exported = await async_get_config_entry_diagnostics(hass, entry)
    assert exported["wpmg_diagnostic"] == report


async def test_wpmg_second_button_press_is_rejected_in_service_path(
    hass: HomeAssistant,
) -> None:
    """HA's button service must not queue a second full diagnostic run."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Stiebel Eltron WPM G",
        data={
            CONF_HOST: "1.1.1.1",
            CONF_PORT: 502,
            CONF_CONTROLLER_TYPE: CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    started = asyncio.Event()
    finish = asyncio.Event()

    async def run_diagnostic(*, report: dict) -> dict:
        started.set()
        await finish.wait()
        report["report_version"] = 2
        return report

    diagnostic = AsyncMock(side_effect=run_diagnostic)
    entry.runtime_data._api.async_run_diagnostic = diagnostic
    entity_id = er.async_get(hass).async_get_entity_id(
        "button",
        DOMAIN,
        build_unique_id(entry, WPMG_RUN_DIAGNOSTIC),
    )
    assert entity_id is not None
    service_data = {ATTR_ENTITY_ID: entity_id}
    first_press = asyncio.create_task(
        hass.services.async_call("button", "press", service_data, blocking=True)
    )
    await started.wait()

    with pytest.raises(HomeAssistantError) as exception_info:
        await hass.services.async_call(
            "button",
            "press",
            service_data,
            blocking=True,
        )

    assert exception_info.value.translation_key == "wpmg_diagnostic_in_progress"
    finish.set()
    await first_press
    assert diagnostic.await_count == 1
