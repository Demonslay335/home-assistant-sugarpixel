"""Firmware update status for SugarPixel."""

from typing import Any

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SugarPixelCoordinator
from .entity import SugarPixelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up firmware update status."""
    coordinator: SugarPixelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SugarPixelFirmwareUpdate(coordinator)])


class SugarPixelFirmwareUpdate(SugarPixelEntity, UpdateEntity):
    """Represent the installed and latest available firmware versions."""

    _attr_translation_key = "firmware"
    _attr_title = "SugarPixel firmware"
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: SugarPixelCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    @property
    def installed_version(self) -> str | None:
        value = self.coordinator.data.get("fwVersion")
        return str(value) if value is not None else None

    @property
    def latest_version(self) -> str | None:
        return self.coordinator.data.get("latestFirmwareVersion")

    @property
    def release_summary(self) -> str | None:
        return self.coordinator.data.get("latestFirmwareReleaseNotes")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "latest_release_date": self.coordinator.data.get(
                "latestFirmwareReleaseDate"
            )
        }
