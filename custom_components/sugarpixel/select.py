"""Snooze duration selection for SugarPixel."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SNOOZE_PRESETS
from .coordinator import SugarPixelCoordinator
from .entity import SugarPixelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the snooze duration selector."""
    coordinator: SugarPixelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SugarPixelSnoozeDurationSelect(coordinator)])


class SugarPixelSnoozeDurationSelect(
    SugarPixelEntity, RestoreEntity, SelectEntity
):
    """Select the duration used by the device-page snooze buttons."""

    _attr_translation_key = "snooze_duration"
    _attr_icon = "mdi:timer-sand"
    _attr_options = list(SNOOZE_PRESETS)

    def __init__(self, coordinator: SugarPixelCoordinator) -> None:
        super().__init__(coordinator, "snooze_duration")
        self._attr_current_option = "15_minutes"

    async def async_added_to_hass(self) -> None:
        """Restore the previously selected preset."""
        await super().async_added_to_hass()
        if (
            (last_state := await self.async_get_last_state()) is not None
            and last_state.state in SNOOZE_PRESETS
        ):
            self._set_option(last_state.state)

    async def async_select_option(self, option: str) -> None:
        """Select a snooze duration preset."""
        self._set_option(option)
        self.async_write_ha_state()

    def _set_option(self, option: str) -> None:
        """Apply a validated preset to the shared coordinator."""
        if option not in SNOOZE_PRESETS:
            raise ValueError(f"Unsupported snooze duration: {option}")
        self._attr_current_option = option
        self.coordinator.snooze_duration_seconds = SNOOZE_PRESETS[option]
