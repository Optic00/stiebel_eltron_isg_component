"""Config flow for the STIEBEL ELTRON integration."""

from dataclasses import dataclass
import logging
from typing import Any, override

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from modbus_connection import ModbusError, ModbusTcpParams
from pystiebeleltron import (
    StiebelEltronModbusError,
    UnknownControllerModelError,
    get_controller_model,
)
from pystiebeleltron.wpmg import WpmGStiebelEltronAPI
import voluptuous as vol

from .const import (
    CONF_CONTROLLER_TYPE,
    CONTROLLER_TYPE_AUTO,
    CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
    DEFAULT_PORT,
    DOMAIN,
    UNIT_ID,
)

_LOGGER = logging.getLogger(__name__)

CONTROLLER_TYPE_OPTIONS: list[SelectOptionDict] = [
    {
        "value": CONTROLLER_TYPE_AUTO,
        "label": "Automatic detection",
    },
    {
        "value": CONTROLLER_TYPE_WPM_G_EXPERIMENTAL,
        "label": "WPM G (experimental, read-only)",
    },
]

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): TextSelector(),
    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
        NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
        vol.Coerce(int),
    ),
    vol.Optional(CONF_CONTROLLER_TYPE, default=CONTROLLER_TYPE_AUTO): SelectSelector(
        SelectSelectorConfig(
            options=CONTROLLER_TYPE_OPTIONS,
            mode=SelectSelectorMode.DROPDOWN,
        )
    ),
})


@dataclass(frozen=True)
class ControllerCheckResult:
    """Result of validating a controller during a config flow."""

    error: str | None = None
    description_placeholders: dict[str, str] | None = None


async def check_controller_model(
    hass: HomeAssistant,
    host: str,
    port: int,
    controller_type: str = CONTROLLER_TYPE_AUTO,
) -> ControllerCheckResult:
    """Check automatic detection or the explicitly selected WPM G subset."""
    try:
        async with async_get_temporary_unit(
            hass,
            ModbusTcpParams(host=host, port=port),
            UNIT_ID,
        ) as unit:
            if controller_type == CONTROLLER_TYPE_WPM_G_EXPERIMENTAL:
                # This only verifies that the evidenced WPM G blocks can be
                # read. It is deliberately not automatic model detection.
                await WpmGStiebelEltronAPI(unit).async_update()
            else:
                await get_controller_model(unit)
    except UnknownControllerModelError as exception:
        _LOGGER.debug("Unsupported controller model %s", exception.model_id)
        return ControllerCheckResult(
            "unsupported_controller",
            {"model_id": str(exception.model_id)},
        )
    except HomeAssistantError:
        _LOGGER.debug(
            "Conflicting Home Assistant Modbus connection settings", exc_info=True
        )
        return ControllerCheckResult("link_conflict")
    except (
        StiebelEltronModbusError,
        ModbusError,
    ):
        _LOGGER.debug("Cannot connect to Stiebel Eltron device", exc_info=True)
        return ControllerCheckResult("cannot_connect")
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return ControllerCheckResult("unknown")
    return ControllerCheckResult()


class StiebelEltronConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for STIEBEL ELTRON."""

    VERSION = 1

    _discovered_host: str

    @override
    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle DHCP discovery."""
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._async_abort_entries_match({CONF_HOST: discovery_info.ip})

        check_result = await check_controller_model(
            self.hass, discovery_info.ip, DEFAULT_PORT
        )
        if check_result.error is not None:
            return self.async_abort(
                reason=check_result.error,
                description_placeholders=check_result.description_placeholders,
            )

        self._discovered_host = discovery_info.ip
        self.context["title_placeholders"] = {CONF_HOST: discovery_info.ip}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to confirm adding the discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title="Stiebel Eltron",
                data={CONF_HOST: self._discovered_host, CONF_PORT: DEFAULT_PORT},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={CONF_HOST: self._discovered_host},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] | None = None
        if user_input is not None:
            self._async_abort_entries_match({
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
            })
            check_result = await check_controller_model(
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input.get(CONF_CONTROLLER_TYPE, CONTROLLER_TYPE_AUTO),
            )
            if check_result.error is not None:
                errors["base"] = check_result.error
                description_placeholders = check_result.description_placeholders
            else:
                return self.async_create_entry(title="Stiebel Eltron", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow."""
        config_entry = self._get_reconfigure_entry()

        controller_type = config_entry.data.get(
            CONF_CONTROLLER_TYPE, CONTROLLER_TYPE_AUTO
        )
        reconfigure_schema = vol.Schema({
            key: value
            for key, value in STEP_USER_DATA_SCHEMA.schema.items()
            if key.schema != CONF_CONTROLLER_TYPE
        })

        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] | None = None
        if user_input is not None:
            self._async_abort_entries_match({
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
            })
            check_result = await check_controller_model(
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                controller_type,
            )
            if check_result.error is not None:
                errors["base"] = check_result.error
                description_placeholders = check_result.description_placeholders
            else:
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_CONTROLLER_TYPE: controller_type,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                reconfigure_schema,
                user_input if user_input is not None else config_entry.data,
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
