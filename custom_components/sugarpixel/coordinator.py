"""Bluetooth polling for SugarPixel."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .adapter import (
    SugarPixelBoundBleakClient,
    adapter_for_source,
    adapters_for_address,
    device_for_source,
)
from .const import (
    CONF_ADAPTER_SOURCE,
    FIRMWARE_CHECK_INTERVAL,
    FIRMWARE_VERSIONS_URL,
    NUS_NOTIFY_UUID,
    NUS_WRITE_UUID,
    READ_KEYS,
    RESPONSE_TIMEOUT,
    SNOOZE_COMMANDS,
    SNOOZE_KEYS,
    SNOOZE_PRESETS,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class SugarPixelCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read settings from one SugarPixel over Nordic UART BLE."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.address: str = entry.data[CONF_ADDRESS]
        self.device_name: str = entry.data.get(CONF_NAME, "SugarPixel")
        self.adapter_source: str | None = entry.data.get(
            CONF_ADAPTER_SOURCE, entry.options.get(CONF_ADAPTER_SOURCE)
        )
        self._firmware_info: dict[str, Any] = {}
        self._firmware_last_checked: datetime | None = None
        self._connection_lock = asyncio.Lock()
        self.snooze_duration_seconds = SNOOZE_PRESETS["15_minutes"]
        super().__init__(
            hass,
            _LOGGER,
            name=f"{self.device_name} Bluetooth",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._connection_lock:
            return await self._async_read_data_locked()

    async def _async_read_data_locked(self) -> dict[str, Any]:
        """Read device data while the caller owns the connection lock."""
        if self.adapter_source is None:
            adapters = adapters_for_address(self.hass, self.address)
            if adapters:
                self.adapter_source = adapters[0].source
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_ADAPTER_SOURCE: self.adapter_source,
                    },
                )

        ble_device = (
            device_for_source(self.hass, self.address, self.adapter_source)
            if self.adapter_source is not None
            else None
        )
        if ble_device is None:
            raise UpdateFailed(
                f"{self.device_name} is not currently visible to its assigned "
                f"Bluetooth adapter ({self.adapter_source or 'not selected'})"
            )

        values: dict[str, Any] = {}
        received = asyncio.Event()

        def notification_handler(_characteristic: Any, payload: bytearray) -> None:
            try:
                decoded = payload.decode("utf-8").strip()
                response = json.loads(decoded.replace("nan", "-1"))
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                _LOGGER.debug(
                    "Ignoring unreadable SugarPixel response %r: %s", payload, err
                )
                return

            if not isinstance(response, dict):
                return
            values.update(response)
            if all(key in values for key in READ_KEYS):
                received.set()

        client: BleakClient | None = None
        try:
            client = await establish_connection(
                SugarPixelBoundBleakClient,
                ble_device,
                self.device_name,
                max_attempts=3,
                ble_device_callback=lambda: device_for_source(
                    self.hass, self.address, self.adapter_source
                ),
                adapter_source=self.adapter_source,
            )
            await self._async_secure_proxy_connection(client)
            await client.start_notify(NUS_NOTIFY_UUID, notification_handler)

            for key in READ_KEYS:
                # Match the app's exact on-wire form: {"get": "settingName"}.
                command = json.dumps({"get": key}).encode()
                await client.write_gatt_char(NUS_WRITE_UUID, command, response=True)
                await asyncio.sleep(0.08)

            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    await received.wait()
            except TimeoutError:
                missing = [key for key in READ_KEYS if key not in values]
                _LOGGER.debug("Timed out waiting for SugarPixel keys: %s", missing)

            if not any(key in values for key in SNOOZE_KEYS):
                raise UpdateFailed(
                    "SugarPixel connected but returned no snooze information"
                )

            for key in SNOOZE_KEYS:
                values[key] = _seconds(values.get(key, 0))
            values["last_read"] = datetime.now(UTC)
            await self._async_update_firmware_info()
            values.update(self._firmware_info)
            return values
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Bluetooth read failed: {err}") from err
        finally:
            if client is not None and client.is_connected:
                try:
                    await client.stop_notify(NUS_NOTIFY_UUID)
                except Exception:  # Device may already have disconnected.
                    pass
                await client.disconnect()

    async def async_set_snooze(self, alarm: str, duration_seconds: int) -> None:
        """Set a remote snooze and immediately confirm it by reading it back."""
        command = SNOOZE_COMMANDS.get(alarm)
        if command is None:
            raise ValueError(f"Unknown SugarPixel alarm target: {alarm}")
        if duration_seconds <= 0:
            raise ValueError("Snooze duration must be greater than zero")
        await self._async_write_and_confirm(
            [{command: str(duration_seconds)}], expected_alarm=alarm
        )

    async def async_clear_snoozes(self) -> None:
        """Clear all remote snoozes and immediately confirm the result."""
        # Firmware 1.83 acknowledges clearSnooze but does not always clear the
        # counters. Follow the app command with explicit zeroes for each type.
        await self._async_write_and_confirm(
            [
                {"command": "clearSnooze"},
                {"snoozeLow": "0"},
                {"snoozeHigh": "0"},
                {"snoozeOld": "0"},
            ],
            clearing=True,
        )

    async def _async_write_and_confirm(
        self,
        payloads: list[dict[str, str]],
        *,
        expected_alarm: str | None = None,
        clearing: bool = False,
    ) -> None:
        """Write commands, read back the state, and verify the requested result."""
        async with self._connection_lock:
            ble_device = self._assigned_ble_device()
            client: BleakClient | None = None
            try:
                client = await establish_connection(
                    SugarPixelBoundBleakClient,
                    ble_device,
                    self.device_name,
                    max_attempts=3,
                    ble_device_callback=lambda: self._assigned_ble_device(),
                    adapter_source=self.adapter_source,
                )
                await self._async_secure_proxy_connection(client)
                await _async_acquire_write_mtu(client)
                for payload in payloads:
                    command = json.dumps(payload).encode()
                    await client.write_gatt_char(NUS_WRITE_UUID, command, response=True)
                    await asyncio.sleep(0.08)
            except Exception as err:
                raise UpdateFailed(f"Bluetooth write failed: {err}") from err
            finally:
                if client is not None and client.is_connected:
                    await client.disconnect()

            # Use the proven read path as confirmation. Keeping the lock held
            # prevents a poll or another action from interleaving with it.
            await asyncio.sleep(0.25)
            values = await self._async_read_data_locked()
            self.async_set_updated_data(values)

            if clearing and any(
                _seconds(values.get(key, 0)) > 0 for key in SNOOZE_KEYS
            ):
                raise UpdateFailed(
                    "Clear command was sent, but SugarPixel still reports an active snooze"
                )

            if expected_alarm is not None:
                expected_keys = {
                    "low": ("snoozeLowFor",),
                    "high": ("snoozeHighFor",),
                    "no_data": ("snoozeOldFor",),
                    "all": tuple(SNOOZE_KEYS),
                }[expected_alarm]
                if any(_seconds(values.get(key, 0)) <= 0 for key in expected_keys):
                    raise UpdateFailed(
                        "Snooze command was sent, but SugarPixel did not confirm it"
                    )

    def _assigned_ble_device(self) -> Any:
        """Return the device on the bound adapter or raise a useful error."""
        if self.adapter_source is None:
            raise UpdateFailed("No local Bluetooth adapter is assigned")
        ble_device = device_for_source(self.hass, self.address, self.adapter_source)
        if ble_device is None:
            raise UpdateFailed(
                f"{self.device_name} is not visible to assigned adapter "
                f"{self.adapter_source}"
            )
        return ble_device

    async def _async_secure_proxy_connection(self, client: BleakClient) -> None:
        """Restore encryption from the proxy's stored bond after reconnecting."""
        if self.adapter_source is None:
            return
        adapter = adapter_for_source(
            self.hass,
            self.address,
            self.adapter_source,
        )
        if adapter is not None and adapter.is_proxy:
            # ESPHome retains the bond keys, but unlike BlueZ it does not
            # automatically encrypt every new link. Pair on each connection;
            # with an existing bond this performs encryption without a PIN.
            await client.pair()

    async def _async_update_firmware_info(self) -> None:
        """Refresh the vendor firmware catalog independently of BLE status."""
        now = datetime.now(UTC)
        if (
            self._firmware_last_checked is not None
            and now - self._firmware_last_checked < FIRMWARE_CHECK_INTERVAL
        ):
            return

        self._firmware_last_checked = now
        try:
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(10):
                response = await session.get(
                    FIRMWARE_VERSIONS_URL,
                    params={"c": int(now.timestamp() * 1000)},
                )
                response.raise_for_status()
                catalog = await response.json(content_type=None)
            releases = [
                release
                for release in catalog
                if isinstance(release, dict)
                and not release.get("beta", False)
                and isinstance(release.get("version"), (int, float))
            ]
            if releases:
                latest = max(releases, key=lambda release: float(release["version"]))
                self._firmware_info = {
                    "latestFirmwareVersion": str(latest["version"]),
                    "latestFirmwareReleaseNotes": latest.get("releasenotes"),
                    "latestFirmwareReleaseDate": latest.get("releasedate"),
                }
        except Exception as err:
            _LOGGER.debug("Unable to check SugarPixel firmware catalog: %s", err)


async def _async_acquire_write_mtu(client: BleakClient) -> None:
    """Negotiate a larger BlueZ MTU, as the SugarPixel app does."""
    backend = getattr(client, "_backend", None)
    acquire_mtu = getattr(backend, "_acquire_mtu", None)
    if acquire_mtu is None:
        _LOGGER.debug("Bluetooth backend does not expose explicit MTU negotiation")
        return

    try:
        await acquire_mtu()
        _LOGGER.debug("Negotiated SugarPixel Bluetooth MTU %s", client.mtu_size)
    except Exception as err:
        # Other backends may negotiate automatically. Let the write proceed so
        # this BlueZ-specific optimization does not prevent them from working.
        _LOGGER.debug("Could not explicitly negotiate SugarPixel MTU: %s", err)


def _seconds(value: Any) -> int:
    """Coerce a SugarPixel snooze value to non-negative seconds."""
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0
