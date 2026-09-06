"""Run the shipped blueprint through Home Assistant's actual automation engine."""

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
import pytest

BLUEPRINT_PATH = (
    Path(__file__).parent.parent / "blueprints/automation/heat_pump_fault.yaml"
)


@pytest.mark.parametrize("custom_action", [False, True])
async def test_fault_blueprint_only_notifies_for_active_fault(hass, custom_action):
    blueprint = Blueprint(
        load_yaml(str(BLUEPRINT_PATH)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    inputs = {"fault_sensor": "binary_sensor.heat_pump_fault"}
    calls = []

    async def capture(call):
        calls.append(call.data)

    hass.services.async_register("test", "notify", capture)
    if custom_action:
        inputs["notification_action"] = [
            {"action": "test.notify", "data": {"message": "fault"}}
        ]
    else:
        hass.services.async_register("persistent_notification", "create", capture)
    configured = BlueprintInputs(blueprint, {"use_blueprint": {"input": inputs}})
    configured.validate()
    config = configured.async_substitute()
    config["id"] = "test_fault_blueprint"
    hass.states.async_set("binary_sensor.heat_pump_fault", "off")
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    for state in ("unknown", "unavailable", "off"):
        hass.states.async_set("binary_sensor.heat_pump_fault", state)
        await hass.async_block_till_done()
    assert calls == []
    hass.states.async_set("binary_sensor.heat_pump_fault", "on")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "fault" in calls[0]["message"].lower()
    hass.states.async_set(
        "binary_sensor.heat_pump_fault", "on", {"friendly_name": "Updated name"}
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    hass.states.async_set("binary_sensor.heat_pump_fault", "off")
    await hass.async_block_till_done()
    assert len(calls) == 1
