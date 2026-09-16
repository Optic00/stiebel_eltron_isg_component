"""Experimental read-only support for ISG-connected WPM G controllers."""

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusError, ModbusUnit
from modbus_connection.model import Component, gauge

from .const import DOMAIN, ExperimentalControllerModel
from .coordinator import (
    StiebelEltronConfigEntry,
    StiebelEltronConnectionParams,
    StiebelEltronDataCoordinator,
)

UNAVAILABLE = 0x8000
WPMG_DIAGNOSTIC_MESSAGE_SPACING = 0.05

# Documented FC04 references for the primary heat pump from chapter 9 of the
# WPM G Modbus manual. Four undocumented gaps are deliberately omitted.
WPMG_DOCUMENTED_INPUT_REFERENCE_RANGES = (
    (36000, 36036),
    (36050, 36055),
    (36100, 36128),
    (37500, 37508),
    (37600, 37604),
    (37650, 37653),
    (37655, 37657),
    (37660, 37661),
    (37663, 37663),
    (37700, 37702),
    (39000, 39063),
)
WPMG_DOCUMENTED_INPUT_REFERENCES = tuple(
    reference
    for first_reference, last_reference in WPMG_DOCUMENTED_INPUT_REFERENCE_RANGES
    for reference in range(first_reference, last_reference + 1)
)


class WpmGSystemValues(Component):
    """Small hardware-backed subset of the WPM G input-register map.

    The manufacturer's chapter 9 uses full references such as 36021 and a
    one-based primary-pump address of 6021. FC04 therefore reads wire address
    6020. The initial hardware capture confirmed this conversion for every
    field below. Temperatures are signed because the matching GENESIS object
    metadata permits negative values; 0x8000 was observed for unavailable
    values on the same controller.
    """

    register_space = "input"
    register_ranges = ((6020, 6024), (6099, 6100))

    brine_inlet_temperature = gauge(6020, 0.01, nan=UNAVAILABLE, unit="°C")
    brine_outlet_temperature = gauge(6021, 0.01, nan=UNAVAILABLE, unit="°C")
    condenser_inlet_temperature = gauge(6023, 0.01, nan=UNAVAILABLE, unit="°C")
    condenser_outlet_temperature = gauge(6024, 0.01, nan=UNAVAILABLE, unit="°C")
    outside_temperature_averaged = gauge(6099, 0.01, nan=UNAVAILABLE, unit="°C")
    dhw_temperature_weighted = gauge(6100, 0.01, nan=UNAVAILABLE, unit="°C")


class WpmGStiebelEltronAPI:
    """Read the bounded experimental WPM G subset from an ISG."""

    def __init__(self, unit: ModbusUnit) -> None:
        """Initialize the read-only system-values component."""
        self._unit = unit
        self.system_values = WpmGSystemValues(unit)

    async def async_update(self) -> None:
        """Read the evidenced input-register blocks."""
        await self.system_values.async_update()

    async def async_run_diagnostic(
        self,
        *,
        message_spacing: float = WPMG_DIAGNOSTIC_MESSAGE_SPACING,
    ) -> dict[str, Any]:
        """Read each documented primary WPM G input register once."""
        started_at = datetime.now(UTC)
        started_monotonic = monotonic()
        results: list[dict[str, Any]] = []
        successful_registers = 0

        for index, documented_reference in enumerate(WPMG_DOCUMENTED_INPUT_REFERENCES):
            primary_address = documented_reference - 30000
            wire_address = primary_address - 1
            result: dict[str, Any] = {
                "documented_reference": documented_reference,
                "primary_address": primary_address,
                "wire_address": wire_address,
            }

            try:
                raw_value = (await self._unit.read_input_registers(wire_address, 1))[0]
            except ModbusError as exception:
                result.update({
                    "status": "error",
                    "error_type": type(exception).__name__,
                })
            else:
                successful_registers += 1
                result.update({
                    "status": "ok",
                    "raw_u16": raw_value,
                    "raw_hex": f"0x{raw_value:04X}",
                })

            result["timestamp_utc"] = datetime.now(UTC).isoformat()
            results.append(result)
            if message_spacing > 0 and index + 1 < len(
                WPMG_DOCUMENTED_INPUT_REFERENCES
            ):
                await asyncio.sleep(message_spacing)

        finished_at = datetime.now(UTC)
        return {
            "report_version": 1,
            "scope": "documented_primary_heat_pump_input_registers",
            "function_code": 4,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(monotonic() - started_monotonic, 3),
            "register_count": len(WPMG_DOCUMENTED_INPUT_REFERENCES),
            "successful_registers": successful_registers,
            "failed_registers": (
                len(WPMG_DOCUMENTED_INPUT_REFERENCES) - successful_registers
            ),
            "registers": results,
        }


class StiebelEltronModbusWpmGDataCoordinator(
    StiebelEltronDataCoordinator[WpmGStiebelEltronAPI]
):
    """Coordinate the experimental read-only WPM G API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: StiebelEltronConfigEntry,
        unit: ModbusUnit,
        host: str,
    ) -> None:
        """Initialize the WPM G coordinator."""
        self._diagnostic_lock = asyncio.Lock()
        self._last_diagnostic_report: dict[str, Any] | None = None
        super().__init__(
            hass,
            entry,
            WpmGStiebelEltronAPI(unit),
            StiebelEltronConnectionParams(
                host=host,
                model=ExperimentalControllerModel.WPM_G,
            ),
        )

    @property
    def diagnostic_report(self) -> dict[str, Any] | None:
        """Return the last in-memory WPM G diagnostic report."""
        return self._last_diagnostic_report

    async def async_run_wpmg_diagnostic(self) -> None:
        """Run one diagnostic without allowing overlapping scans."""
        if self._diagnostic_lock.locked():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="wpmg_diagnostic_in_progress",
            )

        async with self._diagnostic_lock:
            self._last_diagnostic_report = await self._api.async_run_diagnostic()
