"""Button platform for stiebel_eltron_isg."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import RESET_HEATPUMP, WPMG_RUN_DIAGNOSTIC, ExperimentalControllerModel
from .coordinator import AnyStiebelEltronDataCoordinator, StiebelEltronConfigEntry
from .entity import StiebelEltronISGEntity
from .wpmg import StiebelEltronModbusWpmGDataCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class StiebelEltronISGButtonDescriptionMixin:
    """Mixin to describe aStiebel Eltron ISG button."""

    press_action: Callable[[AnyStiebelEltronDataCoordinator], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class StiebelEltronISGButtonDescription(
    ButtonEntityDescription,
    StiebelEltronISGButtonDescriptionMixin,
):
    """Stiebel Eltron ISG button description."""


BUTTONS = [
    StiebelEltronISGButtonDescription(
        key=RESET_HEATPUMP,
        translation_key=RESET_HEATPUMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        press_action=lambda coordinator: coordinator.async_reset_heatpump(),
    ),
]


async def _async_run_wpmg_diagnostic(
    coordinator: AnyStiebelEltronDataCoordinator,
) -> None:
    """Run the WPM G diagnostic on its model-specific coordinator."""
    if not isinstance(coordinator, StiebelEltronModbusWpmGDataCoordinator):
        raise TypeError("WPM G diagnostics require the WPM G coordinator")
    await coordinator.async_run_wpmg_diagnostic()


WPMG_BUTTONS = [
    StiebelEltronISGButtonDescription(
        key=WPMG_RUN_DIAGNOSTIC,
        translation_key=WPMG_RUN_DIAGNOSTIC,
        entity_category=EntityCategory.DIAGNOSTIC,
        press_action=_async_run_wpmg_diagnostic,
    ),
]


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: StiebelEltronConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = entry.runtime_data

    descriptions = (
        WPMG_BUTTONS
        if coordinator.model is ExperimentalControllerModel.WPM_G
        else BUTTONS
    )
    async_add_devices(
        StiebelEltronISGButtonEntity(coordinator, entry, description)
        for description in descriptions
    )


class StiebelEltronISGButtonEntity(StiebelEltronISGEntity, ButtonEntity):
    """stiebel_eltron_isg button class."""

    entity_description: StiebelEltronISGButtonDescription

    def __init__(
        self,
        coordinator: AnyStiebelEltronDataCoordinator,
        config_entry: StiebelEltronConfigEntry,
        description: StiebelEltronISGButtonDescription,
    ) -> None:
        """Initialize the button."""
        self.entity_description = description
        super().__init__(coordinator, config_entry)

    async def async_press(self) -> None:
        """Trigger the button action."""
        await self.entity_description.press_action(self.coordinator)

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added.

        This only applies when first added to the entity registry.
        """
        return True  # The button should be enabled by default as it doesn't rely on specific data from the coordinator

    @property
    def available(self) -> bool:
        """Follow connectivity without requiring a data field like other entities."""
        return self.coordinator.last_update_success
