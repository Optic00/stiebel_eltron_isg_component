"""Experimental read-only support for ISG-connected WPM G controllers."""

from homeassistant.core import HomeAssistant
from modbus_connection import ModbusUnit
from modbus_connection.model import Component, gauge

from .const import ExperimentalControllerModel
from .coordinator import (
    StiebelEltronConfigEntry,
    StiebelEltronConnectionParams,
    StiebelEltronDataCoordinator,
)

UNAVAILABLE = 0x8000


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
        self.system_values = WpmGSystemValues(unit)

    async def async_update(self) -> None:
        """Read the evidenced input-register blocks."""
        await self.system_values.async_update()


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
        super().__init__(
            hass,
            entry,
            WpmGStiebelEltronAPI(unit),
            StiebelEltronConnectionParams(
                host=host,
                model=ExperimentalControllerModel.WPM_G,
            ),
        )
