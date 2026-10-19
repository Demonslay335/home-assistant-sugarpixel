"""Config flow for SugarPixel."""

import re
from typing import Any

import voluptuous as vol
from bleak import BleakError
from dbus_fast import DBusError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .adapter import SugarPixelAdapter, adapter_for_source, adapters_for_address
from .const import CONF_ADAPTER_SOURCE, CONF_REPAIR, DOMAIN
from .pairing import (
    BlueZPairingSession,
    ESPHomeProxyPairingSession,
    SugarPixelPairingError,
    create_pairing_session,
)


def _unique_id(address: str) -> str:
    return address.replace(":", "").lower()


class SugarPixelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a SugarPixel config flow."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        self._discovery_info: bluetooth.BluetoothServiceInfoBleak | None = None
        self._pairing: BlueZPairingSession | ESPHomeProxyPairingSession | None = None
        self._adapter_source: str | None = None
        self._force_repair = False

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(_unique_id(discovery_info.address))
        self._abort_if_unique_id_configured()

        if not discovery_info.connectable:
            return self.async_abort(reason="not_connectable")

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "SugarPixel",
            "address": discovery_info.address,
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered SugarPixel."""
        if self._discovery_info is None:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            return await self.async_step_adapter()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._discovery_info.name or "SugarPixel",
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow manual selection from currently visible SugarPixels."""
        discovered = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(self.hass)
            if info.connectable and (info.name or "").startswith("SugarPixel")
        }

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(_unique_id(address))
            self._abort_if_unique_id_configured()
            info = discovered.get(address)
            if info is None:
                return self.async_abort(reason="no_devices_found")
            self._discovery_info = info
            return await self.async_step_adapter()

        if not discovered:
            return self.async_abort(reason="no_devices_found")

        options = {
            address: f"{info.name or 'SugarPixel'} ({address})"
            for address, info in discovered.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
        )

    async def async_step_adapter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the adapter or proxy that will own the SugarPixel bond."""
        if self._discovery_info is None:
            return self.async_abort(reason="no_devices_found")

        adapters = adapters_for_address(self.hass, self._discovery_info.address)
        if not adapters:
            return self.async_abort(reason="no_supported_adapters")

        if user_input is not None:
            selected = user_input[CONF_ADAPTER_SOURCE]
            if not any(adapter.source == selected for adapter in adapters):
                return self.async_show_form(
                    step_id="adapter",
                    data_schema=_adapter_schema(adapters),
                    errors={"base": "adapter_unavailable"},
                )
            self._adapter_source = selected
            return await self.async_step_pair()

        if len(adapters) == 1:
            self._adapter_source = adapters[0].source
            return await self.async_step_pair()

        return self.async_show_form(
            step_id="adapter",
            data_schema=_adapter_schema(adapters),
            description_placeholders={
                "name": self._discovery_info.name or "SugarPixel"
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change or repair the local adapter assigned to a SugarPixel."""
        entry = self._get_reconfigure_entry()
        address = entry.data[CONF_ADDRESS]
        adapters = adapters_for_address(self.hass, address)
        if not adapters:
            return self.async_abort(reason="no_supported_adapters")

        current = entry.data.get(
            CONF_ADAPTER_SOURCE,
            entry.options.get(CONF_ADAPTER_SOURCE),
        )
        if user_input is not None:
            selected = user_input[CONF_ADAPTER_SOURCE]
            if not any(adapter.source == selected for adapter in adapters):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_reconfigure_schema(adapters, current),
                    errors={"base": "adapter_unavailable"},
                    description_placeholders={"name": entry.title},
                )

            self._adapter_source = selected
            self._force_repair = selected != current or user_input.get(
                CONF_REPAIR, False
            )
            if self._force_repair:
                return await self.async_step_reconfigure_pair()
            return self.async_update_reload_and_abort(
                entry,
                data_updates={CONF_ADAPTER_SOURCE: selected},
                options={},
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(adapters, current),
            description_placeholders={"name": entry.title},
        )

    async def async_step_reconfigure_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a fresh bond on the selected adapter while reconfiguring."""
        entry = self._get_reconfigure_entry()
        if self._adapter_source is None:
            return await self.async_step_reconfigure()

        errors: dict[str, str] = {}
        if self._pairing is None:
            self._pairing = create_pairing_session(
                self.hass,
                entry.data[CONF_ADDRESS],
                self._adapter_source,
                force_repair=self._force_repair,
            )
            try:
                await self._pairing.async_start()
                passkey_requested = await self._pairing.async_wait_for_passkey_request()
            except (BleakError, DBusError, SugarPixelPairingError, OSError) as err:
                await self._pairing.async_close()
                self._pairing = None
                return self.async_abort(
                    reason="pairing_start_failed",
                    description_placeholders={"error": str(err)},
                )
            if not passkey_requested:
                await self._pairing.async_close()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_ADAPTER_SOURCE: self._adapter_source},
                    options={},
                )

        if user_input is not None:
            passkey = str(user_input.get("passkey", "")).strip()
            if re.fullmatch(r"\d{6}", passkey) is None:
                errors["passkey"] = "invalid_passkey"
            else:
                try:
                    await self._pairing.async_submit_passkey(int(passkey))
                    await self._pairing.async_finish()
                except (SugarPixelPairingError, ValueError) as err:
                    errors["base"] = "pairing_failed"
                    self.context["pairing_error"] = str(err)
                else:
                    await self._pairing.async_close()
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_ADAPTER_SOURCE: self._adapter_source},
                        options={},
                    )

        return self.async_show_form(
            step_id="reconfigure_pair",
            data_schema=vol.Schema({vol.Required("passkey"): str}),
            errors=errors,
            description_placeholders={
                "name": entry.title,
                "error": self.context.get("pairing_error", ""),
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair using the code displayed on SugarPixel."""
        if self._discovery_info is None:
            return self.async_abort(reason="no_devices_found")
        if self._adapter_source is None:
            return await self.async_step_adapter()

        errors: dict[str, str] = {}
        if self._pairing is None:
            # A proxy owns its Bluetooth bonds independently of BlueZ. Always
            # replace that bond when creating a new config entry: an ESP32 may
            # otherwise report a stale retained bond as paired without ever
            # asking SugarPixel for its current one-time passkey.
            adapter = adapter_for_source(
                self.hass,
                self._discovery_info.address,
                self._adapter_source,
            )
            self._pairing = create_pairing_session(
                self.hass,
                self._discovery_info.address,
                self._adapter_source,
                force_repair=bool(adapter and adapter.is_proxy),
            )
            try:
                await self._pairing.async_start()
                passkey_requested = await self._pairing.async_wait_for_passkey_request()
            except (BleakError, DBusError, SugarPixelPairingError, OSError) as err:
                await self._pairing.async_close()
                self._pairing = None
                return self.async_abort(
                    reason="pairing_start_failed",
                    description_placeholders={"error": str(err)},
                )
            if not passkey_requested:
                await self._pairing.async_close()
                name = self._discovery_info.name or "SugarPixel"
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ADDRESS: self._discovery_info.address,
                        CONF_NAME: name,
                        CONF_ADAPTER_SOURCE: self._adapter_source,
                    },
                )

        if user_input is not None:
            passkey = str(user_input.get("passkey", "")).strip()
            if re.fullmatch(r"\d{6}", passkey) is None:
                errors["passkey"] = "invalid_passkey"
                return self.async_show_form(
                    step_id="pair",
                    data_schema=vol.Schema({vol.Required("passkey"): str}),
                    errors=errors,
                    description_placeholders={
                        "name": self._discovery_info.name or "SugarPixel",
                        "error": self.context.get("pairing_error", ""),
                    },
                )
            try:
                await self._pairing.async_submit_passkey(int(passkey))
                await self._pairing.async_finish()
            except (SugarPixelPairingError, ValueError) as err:
                errors["base"] = "pairing_failed"
                self.context["pairing_error"] = str(err)
            else:
                await self._pairing.async_close()
                name = self._discovery_info.name or "SugarPixel"
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ADDRESS: self._discovery_info.address,
                        CONF_NAME: name,
                        CONF_ADAPTER_SOURCE: self._adapter_source,
                    },
                )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required("passkey"): str}),
            errors=errors,
            description_placeholders={
                "name": self._discovery_info.name or "SugarPixel",
                "error": self.context.get("pairing_error", ""),
            },
        )


def _adapter_schema(
    adapters: list[SugarPixelAdapter], default: str | None = None
) -> vol.Schema:
    """Build an adapter selector schema."""
    choices = {adapter.source: adapter.label for adapter in adapters}
    selected = default if default in choices else adapters[0].source
    return vol.Schema(
        {vol.Required(CONF_ADAPTER_SOURCE, default=selected): vol.In(choices)}
    )


def _reconfigure_schema(
    adapters: list[SugarPixelAdapter], current: str | None
) -> vol.Schema:
    """Build the adapter reconfiguration schema."""
    base = _adapter_schema(adapters, current).schema
    base[vol.Optional(CONF_REPAIR, default=False)] = bool
    return vol.Schema(base)
