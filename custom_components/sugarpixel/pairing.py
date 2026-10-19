"""Interactive BlueZ pairing for SugarPixel."""

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from dbus_fast import BusType, DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method
from homeassistant.core import HomeAssistant

from .adapter import (
    SugarPixelBoundBleakClient,
    adapter_for_source,
    device_for_source,
)

_LOGGER = logging.getLogger(__name__)

BLUEZ = "org.bluez"
AGENT_MANAGER_PATH = "/org/bluez"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
AGENT_PATH = "/com/customtypeone/sugarpixel/agent"


class SugarPixelPairingError(Exception):
    """Raised when interactive pairing fails."""


class _PasskeyAgent(ServiceInterface):
    """BlueZ Agent1 implementation that accepts a user-supplied passkey."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")
        self.passkey: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.requested = asyncio.Event()
        self.confirmation_value: int | None = None

    def submit(self, value: int) -> None:
        """Submit the code displayed by SugarPixel."""
        if not self.passkey.done():
            self.passkey.set_result(value)

    async def _get_passkey(self) -> int:
        self.requested.set()
        try:
            return await self.passkey
        except asyncio.CancelledError as err:
            raise DBusError("org.bluez.Error.Canceled", "Pairing canceled") from err

    @method()
    def Release(self) -> "":
        return None

    @method()
    async def RequestPinCode(self, device: "o") -> "s":
        del device
        return f"{await self._get_passkey():06d}"

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s") -> "":
        del device, pincode
        return None

    @method()
    async def RequestPasskey(self, device: "o") -> "u":
        del device
        return await self._get_passkey()

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q") -> "":
        del device, passkey, entered
        return None

    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u") -> "":
        del device
        self.confirmation_value = passkey
        submitted = await self._get_passkey()
        if submitted != passkey:
            raise DBusError(
                "org.bluez.Error.Rejected",
                "The submitted code did not match the pairing request",
            )
        return None

    @method()
    async def RequestAuthorization(self, device: "o") -> "":
        del device
        return None

    @method()
    async def AuthorizeService(self, device: "o", uuid: "s") -> "":
        del device, uuid
        return None

    @method()
    def Cancel(self) -> "":
        if not self.passkey.done():
            self.passkey.cancel()
        return None


class BlueZPairingSession:
    """Own one interactive pairing attempt on a local BlueZ adapter."""

    def __init__(
        self, address: str, adapter_source: str, *, force_repair: bool = False
    ) -> None:
        self.address = address.upper()
        self.adapter_source = adapter_source.upper()
        self.force_repair = force_repair
        self.agent = _PasskeyAgent()
        self.bus: MessageBus | None = None
        self.manager: Any = None
        self.task: asyncio.Task[None] | None = None
        self._registered = False

    async def async_start(self) -> None:
        """Register the pairing agent and begin pairing in the background."""
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self.bus.export(AGENT_PATH, self.agent)

        intro = await self.bus.introspect(BLUEZ, AGENT_MANAGER_PATH)
        manager_obj = self.bus.get_proxy_object(BLUEZ, AGENT_MANAGER_PATH, intro)
        self.manager = manager_obj.get_interface(AGENT_MANAGER_IFACE)
        await self.manager.call_register_agent(AGENT_PATH, "KeyboardOnly")
        self._registered = True

        adapter_path = await self._async_find_adapter_path()
        device_path = await self._async_find_device_path(adapter_path)
        if self.force_repair:
            await self._async_remove_bond(adapter_path, device_path)
            device_path = await self._async_wait_for_device_path(adapter_path)
        self.task = asyncio.create_task(self._async_pair(device_path))

    async def _async_managed_objects(self) -> dict[str, Any]:
        """Return BlueZ managed objects."""
        assert self.bus is not None
        intro = await self.bus.introspect(BLUEZ, "/")
        root = self.bus.get_proxy_object(BLUEZ, "/", intro)
        manager = root.get_interface(OBJECT_MANAGER_IFACE)
        return await manager.call_get_managed_objects()

    async def _async_find_adapter_path(self) -> str:
        """Find the BlueZ adapter matching the selected HA scanner source."""
        objects = await self._async_managed_objects()
        for path, interfaces in objects.items():
            properties = interfaces.get(ADAPTER_IFACE)
            if (
                properties
                and properties.get("Address")
                and properties["Address"].value.upper() == self.adapter_source
            ):
                return path
        raise SugarPixelPairingError(
            f"Local Bluetooth adapter {self.adapter_source} was not found in BlueZ"
        )

    async def _async_find_device_path(self, adapter_path: str) -> str:
        """Find the SugarPixel beneath the selected BlueZ adapter."""
        objects = await self._async_managed_objects()
        for path, interfaces in objects.items():
            properties = interfaces.get(DEVICE_IFACE)
            if (
                path.startswith(f"{adapter_path}/")
                and properties
                and properties.get("Address")
                and properties["Address"].value.upper() == self.address
            ):
                return path
        raise SugarPixelPairingError(
            f"The SugarPixel is not visible to local adapter {self.adapter_source}"
        )

    async def _async_remove_bond(self, adapter_path: str, device_path: str) -> None:
        """Remove the selected adapter's existing SugarPixel bond."""
        assert self.bus is not None
        intro = await self.bus.introspect(BLUEZ, adapter_path)
        adapter_obj = self.bus.get_proxy_object(BLUEZ, adapter_path, intro)
        adapter = adapter_obj.get_interface(ADAPTER_IFACE)
        try:
            await adapter.call_remove_device(device_path)
        except DBusError as err:
            if err.type != "org.bluez.Error.DoesNotExist":
                raise SugarPixelPairingError(
                    f"Could not remove the existing Bluetooth bond: {err}"
                ) from err

    async def _async_wait_for_device_path(self, adapter_path: str) -> str:
        """Wait for BlueZ discovery to recreate a removed device object."""
        for _attempt in range(30):
            try:
                return await self._async_find_device_path(adapter_path)
            except SugarPixelPairingError:
                await asyncio.sleep(0.25)
        raise SugarPixelPairingError(
            "Removed the old bond, but the SugarPixel was not rediscovered. "
            "Make sure it is advertising and try again."
        )

    async def _async_pair(self, device_path: str) -> None:
        assert self.bus is not None
        try:
            intro = await self.bus.introspect(BLUEZ, device_path)
            device_obj = self.bus.get_proxy_object(BLUEZ, device_path, intro)
            device = device_obj.get_interface(DEVICE_IFACE)
            await device.call_pair()
        except DBusError as err:
            if err.type == "org.bluez.Error.AlreadyExists":
                return
            raise SugarPixelPairingError(str(err)) from err

    async def async_submit_passkey(self, value: int) -> None:
        """Answer the pending BlueZ passkey request."""
        self.agent.submit(value)

    async def async_finish(self) -> None:
        """Wait for pairing to complete."""
        if self.task is None:
            raise SugarPixelPairingError("Pairing did not start")
        try:
            async with asyncio.timeout(20):
                await self.task
        except TimeoutError as err:
            raise SugarPixelPairingError(
                "Timed out completing Bluetooth pairing"
            ) from err

    async def async_wait_for_passkey_request(self) -> bool:
        """Wait until BlueZ asks the agent for a code.

        Return False when Pair completes successfully without requesting one,
        which means BlueZ already has a usable bond for this device.
        """
        if self.task is None:
            raise SugarPixelPairingError("Pairing did not start")

        requested_task = asyncio.create_task(self.agent.requested.wait())
        try:
            done, _pending = await asyncio.wait(
                {requested_task, self.task},
                timeout=8,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if requested_task in done and self.agent.requested.is_set():
                return True
            if self.task in done:
                await self.task
                return False
            raise SugarPixelPairingError(
                "The Pi 5 connected, but SugarPixel did not request a pairing code"
            )
        finally:
            if not requested_task.done():
                requested_task.cancel()
                try:
                    await requested_task
                except asyncio.CancelledError:
                    pass

    async def async_close(self) -> None:
        """Unregister the agent and close D-Bus resources."""
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        if self._registered and self.manager is not None:
            try:
                await self.manager.call_unregister_agent(AGENT_PATH)
            except DBusError:
                pass
        if self.bus is not None:
            self.bus.unexport(AGENT_PATH)
            self.bus.disconnect()


class ESPHomeProxyPairingSession:
    """Own one interactive pairing attempt through an ESPHome proxy."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        adapter_source: str,
        *,
        force_repair: bool = False,
    ) -> None:
        self.hass = hass
        self.address = address.upper()
        self.adapter_source = adapter_source.upper()
        self.force_repair = force_repair
        self.client: BleakClient | None = None
        self.task: asyncio.Task[None] | None = None
        self.passkey_service: str | None = None

    async def async_start(self) -> None:
        """Connect through the selected proxy and begin pairing."""
        adapter = adapter_for_source(self.hass, self.address, self.adapter_source)
        if adapter is None or not adapter.is_proxy:
            raise SugarPixelPairingError(
                f"ESPHome proxy {self.adapter_source} can no longer see the SugarPixel"
            )
        if adapter.passkey_service is None:
            raise SugarPixelPairingError(
                "The selected ESPHome proxy does not expose the SugarPixel "
                "passkey action"
            )
        self.passkey_service = adapter.passkey_service

        await self._async_connect(adapter.ble_device, adapter.name)

        if self.force_repair:
            try:
                assert self.client is not None
                await self.client.unpair()
            except Exception as err:
                # ESPHome reports an error when there was no bond to remove.
                # That is harmless for a fresh pairing attempt; continuing is
                # also safe because the no-passkey case below is rejected.
                _LOGGER.debug(
                    "Proxy bond removal for %s returned %s; continuing with pairing",
                    self.address,
                    err,
                )

            # ESPHome disconnects the active BLE link while removing a bond.
            # Pairing must run on a newly established connection; reusing the
            # old Bleak client produces "device is not connected".
            if self.client.is_connected:
                await self.client.disconnect()
            self.client = None
            await asyncio.sleep(0.5)
            ble_device = device_for_source(
                self.hass, self.address, self.adapter_source
            ) or adapter.ble_device
            await self._async_connect(ble_device, adapter.name)

        assert self.client is not None
        self.task = asyncio.create_task(self.client.pair())

    async def _async_connect(self, ble_device: Any, adapter_name: str) -> None:
        """Establish a pairing connection through the selected proxy."""
        self.client = await establish_connection(
            SugarPixelBoundBleakClient,
            ble_device,
            f"SugarPixel pairing through {adapter_name}",
            max_attempts=3,
            ble_device_callback=lambda: device_for_source(
                self.hass, self.address, self.adapter_source
            ),
            adapter_source=self.adapter_source,
        )

    async def async_wait_for_passkey_request(self) -> bool:
        """Allow the proxy time to request a passkey from SugarPixel."""
        if self.task is None:
            raise SugarPixelPairingError("Pairing did not start")

        # ESPHome does not currently relay PASSKEY_REQ back over its Bluetooth
        # proxy API. Our firmware bridge receives it locally; a short grace
        # period lets the SugarPixel render its code before HA shows the form.
        done, _pending = await asyncio.wait({self.task}, timeout=1.5)
        if self.task in done:
            await self.task
            if self.force_repair:
                raise SugarPixelPairingError(
                    "The proxy completed pairing without requesting a new code. "
                    "Select the ESPHome proxy explicitly and try Repair again."
                )
            return False
        return True

    async def async_submit_passkey(self, value: int) -> None:
        """Send the displayed code to the proxy-side passkey bridge."""
        if self.passkey_service is None:
            raise SugarPixelPairingError("The proxy passkey action is unavailable")
        try:
            await self.hass.services.async_call(
                "esphome",
                self.passkey_service,
                {"address": self.address, "passkey": value},
                blocking=True,
            )
        except Exception as err:
            raise SugarPixelPairingError(
                f"Could not send the passkey to the ESPHome proxy: {err}"
            ) from err

    async def async_finish(self) -> None:
        """Wait for the proxy to report pairing success."""
        if self.task is None:
            raise SugarPixelPairingError("Pairing did not start")
        try:
            async with asyncio.timeout(20):
                await self.task
        except TimeoutError as err:
            raise SugarPixelPairingError(
                "Timed out completing Bluetooth pairing through the proxy"
            ) from err
        except Exception as err:
            raise SugarPixelPairingError(str(err)) from err

    async def async_close(self) -> None:
        """Cancel unfinished work and release the proxy connection slot."""
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        if self.client is not None and self.client.is_connected:
            try:
                await self.client.disconnect()
            except Exception:
                pass


def create_pairing_session(
    hass: HomeAssistant,
    address: str,
    adapter_source: str,
    *,
    force_repair: bool = False,
) -> BlueZPairingSession | ESPHomeProxyPairingSession:
    """Create a pairing implementation for the selected connection path."""
    adapter = adapter_for_source(hass, address, adapter_source)
    if adapter is None:
        raise SugarPixelPairingError(
            f"Bluetooth adapter {adapter_source} can no longer see the SugarPixel"
        )
    if adapter.is_proxy:
        return ESPHomeProxyPairingSession(
            hass,
            address,
            adapter_source,
            force_repair=force_repair,
        )
    return BlueZPairingSession(address, adapter_source, force_repair=force_repair)
