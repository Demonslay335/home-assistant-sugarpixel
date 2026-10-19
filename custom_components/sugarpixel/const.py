"""Constants for SugarPixel."""

from datetime import timedelta

DOMAIN = "sugarpixel"
PLATFORMS = ["binary_sensor", "button", "select", "sensor", "update"]

CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_ADAPTER_SOURCE = "adapter_source"
CONF_REPAIR = "repair"

SERVICE_SNOOZE = "snooze"
SERVICE_CLEAR_SNOOZES = "clear_snoozes"
ATTR_ALARM = "alarm"
ATTR_DURATION = "duration"

SNOOZE_COMMANDS = {
    "low": "snoozeLow",
    "high": "snoozeHigh",
    "no_data": "snoozeOld",
    "all": "snoozeAll",
}

SNOOZE_PRESETS = {
    "15_minutes": 15 * 60,
    "30_minutes": 30 * 60,
    "1_hour": 60 * 60,
    "2_hours": 2 * 60 * 60,
    "6_hours": 6 * 60 * 60,
    "12_hours": 12 * 60 * 60,
}

NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

SNOOZE_KEYS = ("snoozeLowFor", "snoozeHighFor", "snoozeOldFor")
INFO_KEYS = ("spName", "fwVersion", "wiState", "setupDate")
READ_KEYS = SNOOZE_KEYS + INFO_KEYS

# Limit routine BLE connect/read/disconnect cycles while keeping externally
# initiated snoozes and device state reasonably current in Home Assistant.
UPDATE_INTERVAL = timedelta(hours=1)
RESPONSE_TIMEOUT = 8

FIRMWARE_VERSIONS_URL = "https://www.customtypeone.com/sugarpixelfirmwarejson"
FIRMWARE_CHECK_INTERVAL = timedelta(hours=6)