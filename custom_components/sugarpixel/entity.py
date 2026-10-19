"""Base entity for SugarPixel."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SugarPixelCoordinator


class SugarPixelEntity(CoordinatorEntity[SugarPixelCoordinator]):
    """Base SugarPixel entity."""

    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Keep the last good reading visible after a transient BLE failure."""
        return self.coordinator.data is not None

    def __init__(self, coordinator: SugarPixelCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address.replace(':', '').lower()}_{key}"
        firmware = coordinator.data.get("fwVersion") if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={("bluetooth", coordinator.address)},
            name=coordinator.device_name,
            manufacturer="CustomTypeOne",
            model="SugarPixel",
            sw_version=str(firmware) if firmware is not None else None,
        )
