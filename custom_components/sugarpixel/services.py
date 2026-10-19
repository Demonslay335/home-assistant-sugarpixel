"""Actions for SugarPixel."""

from datetime import timedelta

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .const import (
    ATTR_ALARM,
    ATTR_DURATION,
    DOMAIN,
    SERVICE_CLEAR_SNOOZES,
    SERVICE_SNOOZE,
    SNOOZE_COMMANDS,
)
from .coordinator import SugarPixelCoordinator


def _duration_seconds(value: timedelta) -> int:
    """Validate and convert a duration to whole seconds."""
    seconds = round(value.total_seconds())
    if seconds < 60:
        raise vol.Invalid("Snooze duration must be at least one minute")
    return seconds


SNOOZE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ALARM): vol.In(SNOOZE_COMMANDS),
        vol.Required(ATTR_DURATION): vol.All(cv.time_period, _duration_seconds),
    },
    extra=vol.ALLOW_EXTRA,
)

CLEAR_SNOOZES_SCHEMA = vol.Schema(
    {vol.Required(ATTR_DEVICE_ID): cv.string},
    extra=vol.ALLOW_EXTRA,
)


@callback
def _coordinator_for_device(
    hass: HomeAssistant, device_id: str
) -> SugarPixelCoordinator:
    """Resolve one loaded SugarPixel coordinator from its HA device ID."""
    try:
        _device, entry = service.async_get_device_and_config_entry(
            hass, DOMAIN, device_id
        )
        return hass.data[DOMAIN][entry.entry_id]
    except (KeyError, ValueError) as err:
        raise ServiceValidationError(
            "Select a currently loaded SugarPixel device"
        ) from err


async def async_snooze(call: ServiceCall) -> None:
    """Handle the parameterized snooze action."""
    coordinator = _coordinator_for_device(call.hass, call.data[ATTR_DEVICE_ID])
    await coordinator.async_set_snooze(
        call.data[ATTR_ALARM], call.data[ATTR_DURATION]
    )


async def async_clear_snoozes(call: ServiceCall) -> None:
    """Handle the clear-all action."""
    coordinator = _coordinator_for_device(call.hass, call.data[ATTR_DEVICE_ID])
    await coordinator.async_clear_snoozes()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register SugarPixel actions."""
    hass.services.async_register(
        DOMAIN, SERVICE_SNOOZE, async_snooze, schema=SNOOZE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SNOOZES,
        async_clear_snoozes,
        schema=CLEAR_SNOOZES_SCHEMA,
    )
