"""Binary sensors for SugarPixel snoozes."""

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SugarPixelCoordinator
from .entity import SugarPixelEntity


@dataclass(frozen=True, kw_only=True)
class SugarPixelBinaryDescription(BinarySensorEntityDescription):
    source_key: str


DESCRIPTIONS = (
    SugarPixelBinaryDescription(key="low_snoozed", translation_key="low_snoozed", source_key="snoozeLowFor"),
    SugarPixelBinaryDescription(key="high_snoozed", translation_key="high_snoozed", source_key="snoozeHighFor"),
    SugarPixelBinaryDescription(key="no_data_snoozed", translation_key="no_data_snoozed", source_key="snoozeOldFor"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SugarPixelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SugarPixelBinarySensor(coordinator, description) for description in DESCRIPTIONS)


class SugarPixelBinarySensor(SugarPixelEntity, BinarySensorEntity):
    entity_description: SugarPixelBinaryDescription

    def __init__(self, coordinator: SugarPixelCoordinator, description: SugarPixelBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get(self.entity_description.source_key, 0) > 0

