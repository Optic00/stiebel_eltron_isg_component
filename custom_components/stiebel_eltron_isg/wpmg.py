"""Experimental read-only support for ISG-connected WPM G controllers."""

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import (
    GatewayPathUnavailableError,
    GatewayTargetError,
    ModbusError,
    ModbusExceptionError,
    ModbusProtocolError,
    ModbusUnit,
)
from pystiebeleltron.wpmg import WpmGStiebelEltronAPI

from .const import DOMAIN, ExperimentalControllerModel
from .coordinator import (
    StiebelEltronConfigEntry,
    StiebelEltronConnectionParams,
    StiebelEltronDataCoordinator,
)

WPMG_DIAGNOSTIC_MESSAGE_SPACING = 0.05
WPMG_DIAGNOSTIC_TIMEOUT = 120.0
WPMG_MAX_CONSECUTIVE_COMMUNICATION_ERRORS = 3

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


def _diagnostic_row(documented_reference: int) -> dict[str, Any]:
    """Return address metadata for one primary WPM G input register."""
    primary_address = documented_reference - 30000
    return {
        "documented_reference": documented_reference,
        "primary_address": primary_address,
        "wire_address": primary_address - 1,
    }


def _append_skipped_rows(
    results: list[dict[str, Any]],
    start_index: int,
    reason: str,
) -> None:
    """Record every unattempted register after an aborted scan."""
    timestamp = datetime.now(UTC).isoformat()
    results.extend(
        {
            **_diagnostic_row(documented_reference),
            "status": "skipped",
            "reason": reason,
            "timestamp_utc": timestamp,
        }
        for documented_reference in WPMG_DOCUMENTED_INPUT_REFERENCES[start_index:]
    )


def _update_diagnostic_counts(
    report: dict[str, Any], results: list[dict[str, Any]]
) -> None:
    """Keep report counters consistent with the rows already recorded."""
    report.update({
        "successful_registers": sum(row["status"] == "ok" for row in results),
        "failed_registers": sum(row["status"] == "error" for row in results),
        "skipped_registers": sum(row["status"] == "skipped" for row in results),
    })


def _append_interrupted_row(
    results: list[dict[str, Any]],
    active_index: int | None,
    next_index: int,
    error_type: str,
) -> int:
    """Record a request that started but did not return a Modbus response."""
    if active_index is None:
        return next_index
    results.append({
        **_diagnostic_row(WPMG_DOCUMENTED_INPUT_REFERENCES[active_index]),
        "status": "error",
        "error_type": error_type,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    })
    return active_index + 1


async def _async_read_diagnostic_row(
    unit: ModbusUnit,
    documented_reference: int,
) -> tuple[dict[str, Any], bool]:
    """Read one register and say whether a communication failure occurred."""
    result = _diagnostic_row(documented_reference)
    try:
        values = await unit.read_input_registers(result["wire_address"], 1)
        if len(values) != 1:
            raise ModbusProtocolError(
                "Input-register read returned an unexpected count"
            )
    except ModbusExceptionError as exception:
        communication_error = isinstance(
            exception, (GatewayPathUnavailableError, GatewayTargetError)
        )
        result.update({
            "status": "error",
            "error_type": type(exception).__name__,
            "exception_code": (
                int(exception.exception_code)
                if exception.exception_code is not None
                else None
            ),
        })
    except ModbusError as exception:
        communication_error = True
        result.update({
            "status": "error",
            "error_type": type(exception).__name__,
        })
    else:
        communication_error = False
        raw_value = values[0]
        result.update({
            "status": "ok",
            "raw_u16": raw_value,
            "raw_hex": f"0x{raw_value:04X}",
        })
    result["timestamp_utc"] = datetime.now(UTC).isoformat()
    return result, communication_error


def _finalize_diagnostic_report(
    report: dict[str, Any],
    results: list[dict[str, Any]],
    started_monotonic: float,
    *,
    status: str,
    abort_reason: str | None = None,
) -> None:
    """Complete report metadata without exposing exception messages."""
    report.update({
        "status": status,
        "completed": status == "completed",
        "aborted": status != "completed",
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(monotonic() - started_monotonic, 3),
    })
    _update_diagnostic_counts(report, results)
    if abort_reason is not None:
        report["abort_reason"] = abort_reason


class WpmGDiagnostics:
    """Run an explicit diagnostic independently of normal library polling."""

    def __init__(self, unit: ModbusUnit) -> None:
        """Retain the ISG unit for the bounded FC04 scan."""
        self._unit = unit

    async def async_run_diagnostic(
        self,
        *,
        message_spacing: float = WPMG_DIAGNOSTIC_MESSAGE_SPACING,
        total_timeout: float = WPMG_DIAGNOSTIC_TIMEOUT,
        report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read each documented primary WPM G input register once."""
        started_at = datetime.now(UTC)
        started_monotonic = monotonic()
        results: list[dict[str, Any]] = []
        report = {} if report is None else report
        report.clear()
        report.update({
            "report_version": 2,
            "scope": "documented_primary_heat_pump_input_registers",
            "function_code": 4,
            "started_at": started_at.isoformat(),
            "status": "running",
            "completed": False,
            "aborted": False,
            "register_count": len(WPMG_DOCUMENTED_INPUT_REFERENCES),
            "successful_registers": 0,
            "failed_registers": 0,
            "skipped_registers": 0,
            "registers": results,
        })
        next_index = 0
        active_index: int | None = None
        abort_reason: str | None = None
        consecutive_communication_errors = 0

        try:
            async with asyncio.timeout(total_timeout):
                for index, documented_reference in enumerate(
                    WPMG_DOCUMENTED_INPUT_REFERENCES
                ):
                    active_index = index
                    result, communication_error = await _async_read_diagnostic_row(
                        self._unit, documented_reference
                    )
                    active_index = None
                    if communication_error:
                        consecutive_communication_errors += 1
                    else:
                        consecutive_communication_errors = 0
                    results.append(result)
                    next_index = index + 1
                    _update_diagnostic_counts(report, results)
                    if (
                        consecutive_communication_errors
                        >= WPMG_MAX_CONSECUTIVE_COMMUNICATION_ERRORS
                    ):
                        abort_reason = "consecutive_communication_errors"
                        break
                    if message_spacing > 0 and next_index < len(
                        WPMG_DOCUMENTED_INPUT_REFERENCES
                    ):
                        await asyncio.sleep(message_spacing)
        except TimeoutError:
            abort_reason = "overall_timeout"
            next_index = _append_interrupted_row(
                results, active_index, next_index, "DiagnosticTimeoutError"
            )
        except asyncio.CancelledError:
            next_index = _append_interrupted_row(
                results, active_index, next_index, "CancelledError"
            )
            _append_skipped_rows(results, next_index, "cancelled")
            _finalize_diagnostic_report(
                report,
                results,
                started_monotonic,
                status="cancelled",
                abort_reason="cancelled",
            )
            raise
        except Exception as exception:
            next_index = _append_interrupted_row(
                results, active_index, next_index, type(exception).__name__
            )
            _append_skipped_rows(results, next_index, "unexpected_error")
            _finalize_diagnostic_report(
                report,
                results,
                started_monotonic,
                status="error",
                abort_reason="unexpected_error",
            )
            raise

        if abort_reason is not None:
            _append_skipped_rows(results, next_index, abort_reason)
        _finalize_diagnostic_report(
            report,
            results,
            started_monotonic,
            status="aborted" if abort_reason is not None else "completed",
            abort_reason=abort_reason,
        )
        return report


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
        self._diagnostics = WpmGDiagnostics(unit)
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

    @property
    def polling_report(self) -> dict[str, Any]:
        """Expose normal-poll failures alongside the independent full scan."""
        return self._api.polling_report

    async def async_run_wpmg_diagnostic(self) -> None:
        """Run one diagnostic without allowing overlapping scans."""
        if self._diagnostic_lock.locked():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="wpmg_diagnostic_in_progress",
            )

        async with self._diagnostic_lock:
            report: dict[str, Any] = {}
            self._last_diagnostic_report = report
            await self._diagnostics.async_run_diagnostic(report=report)
            self._api.retry_failed_registers()
