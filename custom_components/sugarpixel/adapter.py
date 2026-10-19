"""Bluetooth adapter selection helpers for SugarPixel."""

import logging
from dataclasses import dataclass
from typing import Any

from bleak import BleakError
from bleak_retry_connector import device_source
from habluetooth import HaBleakClientWrapper
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class SugarPixelBoundBleakClient(HaBleakClientWrapper):
    """HA Bluetooth client restricted to one selected adapter or proxy."""

    def __init__(self, address_or_ble_device: Any, *args: Any, **kwargs: Any) -> None:
        self._adapter_source = str(kwargs.pop("adapter_source"))
        self._sugarpixel_address = (
            address_or_ble_device.address
            if hasattr(address_or_ble_device, "address")
            else str(address_or_ble_device)
        )
        super().__init__(address_or_ble_device, *args, **kwargs)

    def _async_get_best_available_backend_and_device(self, manager: Any) -> Any:
        candidates = sorted(
            manager.async_scanner_devices_by_address(self._sugarpixel_address, True),
            key=lambda candidate: candidate.advertisement.rssi,
            reverse=True,
        )
        for candidate in candidates:
            if candidate.scanner.source.upper() != self._adapter_source.upper():
                continue
            backend = self._async_get_backend_for_ble_device(
                manager, candidate.scanner, candidate.ble_device
            )
            if backend is not None:
                _LOGGER.debug(
                    "Using bound Bluetooth path %s [%s] for %s (RSSI %s)",
                    candidate.scanner.name,
                    candidate.scanner.source,
                    self._sugarpixel_address,
                    candidate.advertisement.rssi,
                )
                return backend
        raise BleakError(
            f"{self._sugarpixel_address}: not currently visible to assigned "
            f"Bluetooth adapter {self._adapter_source}"
        )


@dataclass(frozen=True)
class SugarPixelAdapter:
    """A Bluetooth adapter currently seeing a SugarPixel."""

    source: str
    name: str
    rssi: int
    ble_device: Any
    is_proxy: bool
    passkey_service: str | None = None

    @property
    def label(self) -> str:
        """Return a user-friendly adapter label."""
        identity = (
            self.name
            if self.source.lower() in self.name.lower()
            else f"{self.name} ({self.source})"
        )
        kind = "ESPHome proxy" if self.is_proxy else "local adapter"
        return f"{identity} — {kind}, RSSI {self.rssi} dBm"


def adapters_for_address(hass: HomeAssistant, address: str) -> list[SugarPixelAdapter]:
    """Return supported adapters seeing an address, strongest first.

    Local BlueZ adapters support interactive pairing directly. ESPHome proxies
    are included only when their SugarPixel passkey action is registered.
    """
    adapters: dict[str, SugarPixelAdapter] = {}
    for candidate in bluetooth.async_scanner_devices_by_address(
        hass, address, connectable=True
    ):
        proxy_source = device_source(candidate.ble_device)
        passkey_service = (
            esphome_passkey_service_for_source(hass, candidate.scanner.source)
            if proxy_source
            else None
        )
        if proxy_source and passkey_service is None:
            continue
        source = candidate.scanner.source
        adapter = SugarPixelAdapter(
            source=source,
            name=candidate.scanner.name,
            rssi=candidate.advertisement.rssi,
            ble_device=candidate.ble_device,
            is_proxy=bool(proxy_source),
            passkey_service=passkey_service,
        )
        previous = adapters.get(source)
        if previous is None or adapter.rssi > previous.rssi:
            adapters[source] = adapter
    return sorted(adapters.values(), key=lambda adapter: adapter.rssi, reverse=True)


def device_for_source(hass: HomeAssistant, address: str, source: str) -> Any | None:
    """Return the BLEDevice for an address on one selected adapter."""
    source_upper = source.upper()
    for adapter in adapters_for_address(hass, address):
        if adapter.source.upper() == source_upper:
            return adapter.ble_device
    return None


def adapter_for_source(
    hass: HomeAssistant, address: str, source: str
) -> SugarPixelAdapter | None:
    """Return adapter metadata for one address/source pair."""
    source_upper = source.upper()
    return next(
        (
            adapter
            for adapter in adapters_for_address(hass, address)
            if adapter.source.upper() == source_upper
        ),
        None,
    )


def esphome_passkey_service_for_source(hass: HomeAssistant, source: str) -> str | None:
    """Return the registered ESPHome passkey action for a proxy source."""
    source_upper = source.upper()
    for bluetooth_entry in hass.config_entries.async_entries("bluetooth"):
        if (bluetooth_entry.unique_id or "").upper() != source_upper:
            continue
        if bluetooth_entry.data.get("source_domain") != "esphome":
            continue
        source_entry_id = bluetooth_entry.data.get("source_config_entry_id")
        if not source_entry_id:
            continue
        esphome_entry = hass.config_entries.async_get_entry(source_entry_id)
        if esphome_entry is None:
            continue
        runtime_data = getattr(esphome_entry, "runtime_data", None)
        device_info = getattr(runtime_data, "device_info", None)
        if device_info is None:
            continue
        service = f"{device_info.name.replace('-', '_')}_sugarpixel_submit_passkey"
        if hass.services.has_service("esphome", service):
            return service
    return None
