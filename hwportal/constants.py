"""
Hot Wheels Portal BLE Constants

UUIDs and other constants for the Hot Wheels id Race Portal.
"""

# Portal BLE device name
PORTAL_NAME = "HWiD"

# Base UUID for all Hot Wheels services
BASE_UUID = "af0a6ec7-{}-84a0-91559fc6f0de"

# Service UUIDs
SERVICE_AUTH = "af0a6ec7-0001-000a-84a0-91559fc6f0de"
SERVICE_DATA = "af0a6ec7-0001-000b-84a0-91559fc6f0de"
SERVICE_CONTROL = "af0a6ec7-0001-000c-84a0-91559fc6f0de"

# Service A (Authentication) Characteristics
CHAR_AUTH_COMMAND = "af0a6ec7-0002-000a-84a0-91559fc6f0de"
CHAR_AUTH_KEY = "af0a6ec7-0003-000a-84a0-91559fc6f0de"
CHAR_AUTH_RESPONSE = "af0a6ec7-0004-000a-84a0-91559fc6f0de"

# Service B (Data Transfer) Characteristics
CHAR_DATA_COMMAND = "af0a6ec7-0002-000b-84a0-91559fc6f0de"
CHAR_DATA_FAST = "af0a6ec7-0003-000b-84a0-91559fc6f0de"

# Service C (Control) Characteristics
CHAR_FIRMWARE_VERSION = "af0a6ec7-0002-000c-84a0-91559fc6f0de"
CHAR_SERIAL_NUMBER = "af0a6ec7-0003-000c-84a0-91559fc6f0de"
CHAR_EVENT_1 = "af0a6ec7-0004-000c-84a0-91559fc6f0de"
CHAR_EVENT_2 = "af0a6ec7-0005-000c-84a0-91559fc6f0de"
CHAR_EVENT_3 = "af0a6ec7-0006-000c-84a0-91559fc6f0de"
CHAR_CONTROL = "af0a6ec7-0007-000c-84a0-91559fc6f0de"
CHAR_COMMAND = "af0a6ec7-0008-000c-84a0-91559fc6f0de"

# Characteristic metadata
CHARACTERISTICS = {
    CHAR_AUTH_COMMAND: {"name": "Auth Command", "service": "auth", "props": ["write", "indicate"]},
    CHAR_AUTH_KEY: {"name": "Auth Key", "service": "auth", "props": ["read"]},
    CHAR_AUTH_RESPONSE: {"name": "Auth Response", "service": "auth", "props": ["write", "indicate"]},
    CHAR_DATA_COMMAND: {"name": "Data Command", "service": "data", "props": ["write", "indicate"]},
    CHAR_DATA_FAST: {"name": "Data Fast", "service": "data", "props": ["write-without-response"]},
    CHAR_FIRMWARE_VERSION: {"name": "Firmware Version", "service": "control", "props": ["read"]},
    CHAR_SERIAL_NUMBER: {"name": "Serial Number", "service": "control", "props": ["read", "indicate"]},
    CHAR_EVENT_1: {"name": "Event Channel 1", "service": "control", "props": ["indicate"]},
    CHAR_EVENT_2: {"name": "Event Channel 2", "service": "control", "props": ["indicate"]},
    CHAR_EVENT_3: {"name": "Event Channel 3", "service": "control", "props": ["indicate"]},
    CHAR_CONTROL: {"name": "Control Register", "service": "control", "props": ["write", "read", "indicate"]},
    CHAR_COMMAND: {"name": "Command", "service": "control", "props": ["write", "indicate"]},
}

# Characteristics that can send notifications
NOTIFY_CHARACTERISTICS = [
    CHAR_AUTH_COMMAND,
    CHAR_AUTH_RESPONSE,
    CHAR_DATA_COMMAND,
    CHAR_SERIAL_NUMBER,
    CHAR_EVENT_1,
    CHAR_EVENT_2,
    CHAR_EVENT_3,
    CHAR_CONTROL,
    CHAR_COMMAND,
]

# Characteristics that can be read
READ_CHARACTERISTICS = [
    CHAR_AUTH_KEY,
    CHAR_FIRMWARE_VERSION,
    CHAR_SERIAL_NUMBER,
    CHAR_CONTROL,
]
