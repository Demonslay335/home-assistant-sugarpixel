"""Sensors for SugarPixel."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SugarPixelCoordinator
from .entity import SugarPixelEntity


@dataclass(frozen=True, kw_only=True)
class SugarPixelSensorDescription(SensorEntityDescription):
    source_key: str


DESCRIPTIONS = (
    SugarPixelSensorDescription(key="low_snooze_remaining", translation_key="low_snooze_remaining", source_key="snoozeLowFor", device_class=SensorDeviceClass.TIMESTAMP),
    SugarPixelSensorDescription(key="high_snooze_remaining", translation_key="high_snooze_remaining", source_key="snoozeHighFor", device_class=SensorDeviceClass.TIMESTAMP),
    SugarPixelSensorDescription(key="no_data_snooze_remaining", translation_key="no_data_snooze_remaining", source_key="snoozeOldFor", device_class=SensorDeviceClass.TIMESTAMP),
    SugarPixelSensorDescription(key="wifi_state", translation_key="wifi_state", source_key="wiState", entity_category=EntityCategory.DIAGNOSTIC),
    SugarPixelSensorDescription(key="firmware_version", translation_key="firmware_version", source_key="fwVersion", entity_category=EntityCategory.DIAGNOSTIC),
    SugarPixelSensorDescription(key="setup_date", translation_key="setup_date", source_key="setupDate", device_class=SensorDeviceClass.DATE, entity_category=EntityCategory.DIAGNOSTIC),
    SugarPixelSensorDescription(key="last_read", translation_key="last_read", source_key="last_read", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SugarPixelCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SugarPixelSensor(coordinator, description) for description in DESCRIPTIONS)


class SugarPixelSensor(SugarPixelEntity, SensorEntity):
    entity_description: SugarPixelSensorDescription

    def __init__(self, coordinator: SugarPixelCoordinator, description: SugarPixelSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.coordinator.data.get(self.entity_description.source_key)
        if self.entity_description.source_key in {
            "snoozeLowFor",
            "snoozeHighFor",
            "snoozeOldFor",
        }:
            return _snoozed_until(value, self.coordinator.data.get("last_read"))
        if self.entity_description.source_key == "setupDate":
            return _as_date(value)
        return value


def _snoozed_until(value: Any, last_read: Any) -> datetime | None:
    """Convert remaining seconds at read time into an absolute timestamp."""
    try:
        remaining = max(0, int(float(value)))
    except (TypeError, ValueError):
        return None
    if remaining == 0 or not isinstance(last_read, datetime):
        return None
    return last_read + timedelta(seconds=remaining)


def _as_timestamp(value: Any) -> datetime | None:
    """Convert a SugarPixel Unix timestamp to a timezone-aware datetime."""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    if timestamp > 100_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    """Convert a SugarPixel Unix timestamp to a calendar date."""
    timestamp = _as_timestamp(value)
    return timestamp.date() if timestamp is not None else None
