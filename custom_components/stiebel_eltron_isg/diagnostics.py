"""Diagnostics support for Stiebel Eltron ISG."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import ExperimentalControllerModel
from .coordinator import StiebelEltronConfigEntry, StiebelEltronDataCoordinator

CONFIG_FIELDS_TO_REDACT: Final[set[str]] = {CONF_HOST}
# async_redact_data also converts ConfigEntry.options from MappingProxyType to
# a plain JSON-safe dict, even while there are no sensitive option fields.
OPTIONS_FIELDS_TO_REDACT: Final[set[str]] = set()
# Audited against pystiebeleltron 0.9.0 to 0.10.1:
# the 706 Modbus fields keep the names and addresses of 0.8.0, only the HK3
# pair moved to another component; 0.9.3 adds the WPM ventilation fields
# (air temperatures, humidity, airflow, stages). None holds a serial, MAC, host or IP;
# controller_identification is the model code. Re-audit this set on dependency
# updates; other ISG interfaces can expose a MAC-based serial number.
DATA_FIELDS_TO_REDACT: Final[set[str]] = set()


def _diagnostics_for_entry(
    entry: StiebelEltronConfigEntry,
) -> dict[str, Any]:
    """Build diagnostics shared by the config entry and device endpoints."""
    coordinator = entry.runtime_data
    data = {str(k): v for k, v in coordinator.get_raw_data().items() if v is not None}

    result: dict[str, Any] = {
        "config_entry": async_redact_data(entry.data, CONFIG_FIELDS_TO_REDACT),
        "options": async_redact_data(entry.options, OPTIONS_FIELDS_TO_REDACT),
        "data": [
            async_redact_data(data, DATA_FIELDS_TO_REDACT),
            {
                "model": coordinator.model.name,
                "model_id": coordinator.model.value,
            },
        ],
    }
    if coordinator.model is ExperimentalControllerModel.WPM_G:
        result["wpmg"] = _wpmg_status(coordinator)
    return result


def _wpmg_status(coordinator: StiebelEltronDataCoordinator) -> dict[str, Any]:
    """Describe the experimental WPM G polling state from the coordinator's cache.

    No Modbus request is made. Of a failed update only the exception class is
    reported, because its text can carry the host or transport details.
    """
    status: dict[str, Any] = {
        "controller_family": coordinator.family.value,
        "last_update_success": coordinator.last_update_success,
        "dropped_optional_components": list(coordinator.dropped_optional_components),
    }
    if not coordinator.last_update_success and coordinator.last_exception is not None:
        error = coordinator.last_exception
        status["last_update_error"] = type(error.__cause__ or error).__name__
    return status


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return _diagnostics_for_entry(entry)


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    config_entry: StiebelEltronConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return entry-scoped diagnostics for its single controller device."""
    return _diagnostics_for_entry(config_entry)
