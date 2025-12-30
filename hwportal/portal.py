"""
Hot Wheels Portal Connection Handler

Main class for connecting to and interacting with the portal.
"""

import asyncio
from typing import Callable
from datetime import datetime
from dataclasses import dataclass, field

from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .constants import (
    PORTAL_NAME,
    CHAR_FIRMWARE_VERSION,
    CHAR_SERIAL_NUMBER,
    CHAR_AUTH_KEY,
    CHAR_CONTROL,
    CHAR_EVENT_1,
    CHAR_EVENT_2,
    CHAR_EVENT_3,
    CHAR_COMMAND,
    NOTIFY_CHARACTERISTICS,
    CHARACTERISTICS,
)


@dataclass
class PortalEvent:
    """Represents an event from the portal."""
    timestamp: datetime
    characteristic: str
    char_name: str
    data: bytes

    @property
    def data_hex(self) -> str:
        return self.data.hex()

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S.%f')[:-3]}] {self.char_name}: {self.data_hex}"


@dataclass
class PortalInfo:
    """Portal device information."""
    address: str
    firmware_version: str = ""
    serial_number: str = ""
    device_key: bytes = field(default_factory=bytes)


class HotWheelsPortal:
    """
    Main class for interacting with the Hot Wheels id Race Portal.

    Usage:
        async with HotWheelsPortal() as portal:
            info = await portal.get_info()
            print(f"Firmware: {info.firmware_version}")

            # Subscribe to events
            portal.on_event = my_callback
            await portal.start_monitoring()
    """

    def __init__(self, address: str | None = None):
        """
        Initialize the portal connection.

        Args:
            address: BLE device address. If None, will scan for portal.
        """
        self.address = address
        self.client: BleakClient | None = None
        self.info: PortalInfo | None = None
        self.events: list[PortalEvent] = []
        self._event_callbacks: list[Callable[[PortalEvent], None]] = []
        self._connected = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    @staticmethod
    async def scan(timeout: float = 10.0) -> list[tuple[str, str]]:
        """
        Scan for Hot Wheels portals.

        Returns:
            List of (address, name) tuples for found portals.
        """
        portals = []
        devices = await BleakScanner.discover(timeout=timeout)

        for device in devices:
            if device.name and PORTAL_NAME.lower() in device.name.lower():
                portals.append((device.address, device.name))

        return portals

    async def connect(self) -> bool:
        """Connect to the portal."""
        if self._connected:
            return True

        # Find portal if address not provided
        if self.address is None:
            portals = await self.scan()
            if not portals:
                raise ConnectionError("No Hot Wheels Portal found")
            self.address = portals[0][0]

        # Connect
        self.client = BleakClient(self.address)
        await self.client.connect()
        self._connected = self.client.is_connected

        if self._connected:
            # Read device info
            self.info = await self._read_device_info()

        return self._connected

    async def disconnect(self):
        """Disconnect from the portal."""
        if self.client and self._connected:
            await self.client.disconnect()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None and self.client.is_connected

    async def _read_device_info(self) -> PortalInfo:
        """Read device information from the portal."""
        info = PortalInfo(address=self.address)

        try:
            fw_bytes = await self.client.read_gatt_char(CHAR_FIRMWARE_VERSION)
            info.firmware_version = fw_bytes.decode("utf-8")
        except Exception:
            pass

        try:
            sn_bytes = await self.client.read_gatt_char(CHAR_SERIAL_NUMBER)
            info.serial_number = sn_bytes.decode("utf-8")
        except Exception:
            pass

        try:
            info.device_key = bytes(await self.client.read_gatt_char(CHAR_AUTH_KEY))
        except Exception:
            pass

        return info

    async def get_info(self) -> PortalInfo:
        """Get portal device information."""
        if self.info is None:
            self.info = await self._read_device_info()
        return self.info

    def on_event(self, callback: Callable[[PortalEvent], None]):
        """Register an event callback."""
        self._event_callbacks.append(callback)

    def _notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Internal handler for BLE notifications."""
        char_info = CHARACTERISTICS.get(characteristic.uuid, {})
        char_name = char_info.get("name", "Unknown")

        event = PortalEvent(
            timestamp=datetime.now(),
            characteristic=characteristic.uuid,
            char_name=char_name,
            data=bytes(data),
        )

        self.events.append(event)

        # Call registered callbacks
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Event callback error: {e}")

    async def start_monitoring(self):
        """Start monitoring for portal events."""
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")

        for char_uuid in NOTIFY_CHARACTERISTICS:
            try:
                await self.client.start_notify(char_uuid, self._notification_handler)
            except Exception:
                pass  # Some characteristics may not support notifications

    async def stop_monitoring(self):
        """Stop monitoring for portal events."""
        if not self.is_connected:
            return

        for char_uuid in NOTIFY_CHARACTERISTICS:
            try:
                await self.client.stop_notify(char_uuid)
            except Exception:
                pass

    async def read_control_register(self) -> bytes:
        """Read the control register value."""
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")

        return bytes(await self.client.read_gatt_char(CHAR_CONTROL))

    async def write_control_register(self, data: bytes):
        """Write to the control register."""
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")

        await self.client.write_gatt_char(CHAR_CONTROL, data)

    async def send_command(self, data: bytes):
        """Send a command to the portal."""
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")

        await self.client.write_gatt_char(CHAR_COMMAND, data)

    def get_events(self, characteristic: str | None = None) -> list[PortalEvent]:
        """
        Get captured events, optionally filtered by characteristic.

        Args:
            characteristic: UUID to filter by, or None for all events.
        """
        if characteristic is None:
            return self.events.copy()

        return [e for e in self.events if e.characteristic == characteristic]

    def clear_events(self):
        """Clear the event log."""
        self.events.clear()
