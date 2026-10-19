"""Buttons for SugarPixel."""

from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SugarPixelCoordinator
from .entity import SugarPixelEntity


@dataclass(frozen=True, kw_only=True)
class SugarPixelButtonDescription(ButtonEntityDescription):
    """Describe a SugarPixel button."""

    alarm: str | None = None
    clear_snoozes: bool = False


SNOOZE_BUTTONS = (
    SugarPixelButtonDescription(
        key="snooze_low",
        translation_key="snooze_low",
        icon="mdi:alarm-snooze",
        alarm="low",
    ),
    SugarPixelButtonDescription(
        key="snooze_high",
        translation_key="snooze_high",
        icon="mdi:alarm-snooze",
        alarm="high",
    ),
    SugarPixelButtonDescription(
        key="snooze_no_data",
        translation_key="snooze_no_data",
        icon="mdi:alarm-snooze",
        alarm="no_data",
    ),
    SugarPixelButtonDescription(
        key="snooze_all",
        translation_key="snooze_all",
        icon="mdi:alarm-multiple",
        alarm="all",
    ),
    SugarPixelButtonDescription(
        key="clear_snoozes",
        translation_key="clear_snoozes",
        icon="mdi:alarm-off",
        clear_snoozes=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SugarPixel action buttons."""
    coordinator: SugarPixelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [SugarPixelRefreshButton(coordinator)]
        + [
            SugarPixelSnoozeButton(coordinator, description)
            for description in SNOOZE_BUTTONS
        ]
    )


class SugarPixelRefreshButton(SugarPixelEntity, ButtonEntity):
    """Request an immediate Bluetooth read."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SugarPixelCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        """Refresh SugarPixel data now."""
        await self.coordinator.async_request_refresh()


class SugarPixelSnoozeButton(SugarPixelEntity, ButtonEntity):
    """Apply or clear a remote snooze."""

    entity_description: SugarPixelButtonDescription

    def __init__(
        self,
        coordinator: SugarPixelCoordinator,
        description: SugarPixelButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the selected snooze action."""
        if self.entity_description.clear_snoozes:
            await self.coordinator.async_clear_snoozes()
            return
        if self.entity_description.alarm is None:
            raise ValueError("Snooze button has no alarm target")
        await self.coordinator.async_set_snooze(
            self.entity_description.alarm,
            self.coordinator.snooze_duration_seconds,
        )
