# SugarPixel for Home Assistant

An unofficial Home Assistant custom integration for local control and monitoring
of SugarPixel devices over Bluetooth.

Each SugarPixel can be bound to a specific local Bluetooth adapter or a
compatible ESPHome Bluetooth proxy. Communication stays local; the integration
does not require SugarPixel account credentials or CGM credentials.

## Features

- Guided six-digit Bluetooth pairing
- Per-device Bluetooth adapter binding
- Local Linux/BlueZ adapters and compatible ESPHome Bluetooth proxies
- Repair or move an existing device through Reconfigure
- Snooze Low, High, No Data, or All alarms
- Selectable snooze duration
- Clear all snoozes
- Current snooze state and remaining time
- Firmware version, firmware availability, build date, setup date, and Wi-Fi state
- Manual Refresh button
- Hourly polling to limit BLE connection churn while detecting changes made
  with the SugarPixel app or physical controls
- Entities that can be used in Home Assistant dashboards, scripts, and
  automations

## What this integration changes

This integration does **not** modify the SugarPixel's alarm thresholds, glucose
settings, display preferences, Wi-Fi configuration, CGM configuration, or other
persistent device settings. Those settings remain managed through the official
SugarPixel app.

The integration only:

- Reads device information and current snooze status
- Activates Low, High, No Data, or All alarm snoozes for a selected duration
- Clears active snoozes
- Creates or repairs the Bluetooth bond used by Home Assistant
- Periodically refreshes the state shown in Home Assistant

## Automations

The exposed entities can be used in Home Assistant automations, scripts,
dashboards, and voice-assistant routines. For example, you can:

- Activate a snooze as part of a bedtime automation
- Clear all snoozes automatically in the morning
- Use the current snooze state as an automation trigger or condition
- Display active snoozes and their remaining time on a dashboard
- Request a manual refresh before evaluating the current snooze state

Use Home Assistant's standard `button.press` action to activate a snooze, clear
snoozes, or request a refresh.

Because the SugarPixel does not push these changes to Home Assistant, changes
made through the official app or physical controls may take up to one hour to
appear automatically. Press the Refresh button when an immediate update is
needed.

## Requirements

- Home Assistant 2026.9 or newer
- A SugarPixel visible to a connectable Home Assistant Bluetooth adapter
- For proxy pairing, an active ESPHome Bluetooth proxy with the companion
  `sugarpixel_pairing` external component and passkey actions installed

## Installation

1. Copy `custom_components/sugarpixel` into `/config/custom_components/` on the
   Home Assistant system.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **SugarPixel** and select the device.
5. Select the Bluetooth adapter that should always handle that SugarPixel.
6. Enter the six-digit code displayed by the SugarPixel when prompted.

Close the SugarPixel phone app before pairing. A phone connected to the device
can prevent Home Assistant from establishing its own BLE connection.

## Normal operation

The integration reads each device:

- During setup or Home Assistant startup
- Once per hour
- Immediately after a Snooze or Clear command
- When the Refresh button is pressed

The one-hour interval is intentional. Frequent BLE connect/read/disconnect
cycles appear capable of leaving SugarPixel firmware 1.83 temporarily unable to
accept new BLE connections. Hourly polling reduces routine sessions by about
92 percent compared with the original five-minute interval.

## Reconfigure and repair

Open the SugarPixel integration entry and select **Reconfigure** to:

- Confirm or change its assigned Bluetooth adapter
- Repair the Bluetooth bond

Changing adapters requires a new bond because bonding keys are stored by the
adapter. Select **Repair Bluetooth bond** only when moving adapters or resolving
an authentication problem. Ordinary timeouts usually do not require deleting
the entry or repairing its bond.

## Troubleshooting

### Recommended recovery order

Start with the least disruptive steps:

1. Force-stop the SugarPixel phone app on any phone that has it installed.
2. Wait for any displayed pairing code to expire, then try Refresh or Reload.
3. Open Reconfigure and confirm the intended adapter is selected.
4. Unplug the affected SugarPixel for 15 seconds, then reconnect it.
5. For a proxy-bound device, restart its ESPHome proxy.
6. Restart Home Assistant Core and allow a couple of minutes for Bluetooth
   advertisements and automatic setup retries to resume.
7. Use **Repair Bluetooth bond** only if authentication still fails.

Do not delete the integration entry as a first troubleshooting step. Deleting a
Home Assistant entry does not necessarily remove the bond stored by BlueZ or an
ESPHome proxy.

### `Page Timeout` while adding or reconfiguring

Bluetooth connection and pairing can outlast the frontend request timeout,
especially with weak signal strength. The operation may have partially or fully
completed in the background.

- Let any displayed PIN expire before starting another attempt.
- Return to Devices & services and check whether the entry was created.
- If discovery disappeared, use **Add integration → SugarPixel** manually.
- Retry with the phone app force-stopped and the selected adapter near the
  SugarPixel.

### No PIN prompt, followed by an authentication error

The selected adapter may have considered the device already bonded while its
stored keys were missing or unusable.

1. Open Reconfigure.
2. Confirm the correct adapter is selected.
3. Select **Repair Bluetooth bond**.
4. Enter the new code displayed by the SugarPixel.

### `Insufficient authentication` or `Insufficient encryption`

Upgrade to integration v0.7.2 or newer. Proxy connections must restore link
encryption from the stored bond after every reconnect. If the current version
still reports this error, use Reconfigure and repair the bond through the same
adapter that will operate the device.

### `TimeoutError` or `ESP_GATT_CONN_FAIL_ESTABLISH`

These errors occur before SugarPixel commands or authentication complete. Common
causes include another BLE client, weak signal or interference, or the
SugarPixel's BLE subsystem no longer accepting connections.

1. Force-stop the phone app.
2. Power-cycle the SugarPixel for 15 seconds.
3. If applicable, restart the assigned proxy.
4. Reload the integration entry or wait for Home Assistant's automatic retry.

If power-cycling immediately restores the device without repairing its bond,
the failure was likely a temporary SugarPixel BLE lockup rather than lost
pairing data.

### Device is visible but remains `Initializing` or `Unavailable`

The integration performs a real BLE read during setup. Seeing an advertisement
does not guarantee that the SugarPixel will accept a GATT connection.

- Confirm its assigned adapter in Reconfigure.
- Check that the adapter is online and connectable.
- Power-cycle the SugarPixel before repairing or deleting anything.
- After a Home Assistant restart, allow a few minutes for automatic setup
  retries.

### ESPHome proxy checks

In **Settings → Devices & services → Bluetooth**, the proxy should be online and
show available connection capacity. For example, `0/3 connections` means zero
slots are in use and all three are available; it is not an error.

The proxy must have:

- `bluetooth_proxy` with active connections enabled
- The companion `sugarpixel_pairing` external component
- ESPHome API actions whose names include
  `sugarpixel_submit_passkey` and `sugarpixel_reject_passkey`

If local reads work but proxy writes fail, update to v0.7.2 or newer. If proxy
bond repair disconnects and then reports that the device is not connected,
update to v0.7.3 or newer.

## Collecting useful logs

For a local-adapter failure, collect the SugarPixel integration error from
**Settings → System → Logs**.

For a proxy failure, collect both:

- The Home Assistant SugarPixel error
- The ESPHome proxy log covering the same attempt

Useful details include the integration version, selected adapter, RSSI, whether
a PIN appeared, whether the phone app was closed, and whether power-cycling the
SugarPixel restored connectivity.

## BLE protocol

The integration communicates over Nordic UART Service. It subscribes to the TX
notification characteristic and sends JSON requests or commands through the RX
write characteristic.

No vendor application package, firmware, CGM credential, or account token is
included in this project.

## Disclaimer

SugarPixel is a registered trademark of CustomTypeOne LLC. This independent,
unofficial project is not affiliated with, endorsed by, or supported by
CustomTypeOne LLC.

---

*This project was developed with assistance from OpenAI's ChatGPT and Codex,
including help with coding, debugging, and documentation.*