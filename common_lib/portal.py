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
    CHAR_COMMAND,
    NOTIFY_CHARACTERISTICS,
    CHARACTERISTICS,
)
from .mpid import (
    MpidSession,
    parse_message,
    to_legacy_events,
    DeviceMode,
    cmd_request_device_info,
    cmd_set_led_color,
    cmd_reset_led,
    cmd_set_mode,
    cmd_reset,
    cmd_clear_bonding,
    CHAR_TXRX,
    CHAR_FACTORY,
    CHAR_SESSION,
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
    transport: str = ""


class HotWheelsPortal:
    """
    Main class for interacting with the Hot Wheels id Race Portal.

    Usage:
        async with HotWheelsPortal() as portal:
            info = await portal.get_info()
            print(f"Firmware: {info.firmware_version}")

            portal.on_event(my_callback)
            await portal.start_monitoring()
    """

    def __init__(self, address: str | None = None):
        self.address = address
        self.client: BleakClient | None = None
        self.info: PortalInfo | None = None
        self.events: list[PortalEvent] = []
        self._event_callbacks: list[Callable[[PortalEvent], None]] = []
        self._message_callbacks: list[Callable] = []
        self._connected = False
        self.transport: str = ""
        self._session: MpidSession | None = None
        self.device_info = None           # latest MPID DeviceInfo (battery, mode, ...)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    @staticmethod
    async def scan(timeout: float = 10.0) -> list[tuple[str, str]]:
        """Scan for Hot Wheels portals. Returns (address, name) tuples."""
        portals = []
        devices = await BleakScanner.discover(timeout=timeout)
        for device in devices:
            if device.name and PORTAL_NAME.lower() in device.name.lower():
                portals.append((device.address, device.name))
        if len(portals) == 0:
            print(f"Scanned total of {len(devices)} devices, portal not found.")
        return portals

    async def connect(self) -> bool:
        """Connect to the portal and auto-detect its transport."""
        if self._connected:
            return True

        if self.address is None:
            portals = await self.scan()
            if not portals:
                raise ConnectionError("No Hot Wheels Portal found")
            self.address = portals[0][0]

        self.client = BleakClient(self.address)
        await self.client.connect()
        self._connected = self.client.is_connected

        if self._connected:
            self.transport = self._detect_transport()
            self.info = await self._read_device_info()
            self.info.transport = self.transport

        return self._connected

    def _detect_transport(self) -> str:
        """MPID if the SESSION characteristic is present, else legacy 000c."""
        try:
            if self.client.services.get_characteristic(CHAR_SESSION) is not None:
                return "mpid"
        except Exception:
            pass
        return "legacy"

    async def disconnect(self):
        if self.client and self._connected:
            await self.client.disconnect()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None and self.client.is_connected

    async def _read_device_info(self) -> PortalInfo:
        """Read device info. Legacy reads (000c) are best-effort; on MPID the
        firmware version arrives later via the status heartbeat."""
        info = PortalInfo(address=self.address)
        try:
            info.firmware_version = (await self.client.read_gatt_char(CHAR_FIRMWARE_VERSION)).decode("utf-8")
        except Exception:
            pass
        try:
            info.serial_number = (await self.client.read_gatt_char(CHAR_SERIAL_NUMBER)).decode("utf-8")
        except Exception:
            pass
        try:
            info.device_key = bytes(await self.client.read_gatt_char(CHAR_AUTH_KEY))
        except Exception:
            pass
        return info

    async def get_info(self) -> PortalInfo:
        if self.info is None:
            self.info = await self._read_device_info()
        return self.info

    def on_event(self, callback: Callable[[PortalEvent], None]):
        """Register a low-level PortalEvent callback (works on both transports)."""
        self._event_callbacks.append(callback)

    def on_message(self, callback: Callable):
        self._message_callbacks.append(callback)

    def _dispatch(self, char_uuid: str, data: bytes):
        """Build a PortalEvent for one logical channel and fan out to callbacks."""
        char_info = CHARACTERISTICS.get(char_uuid, {})
        event = PortalEvent(
            timestamp=datetime.now(),
            characteristic=char_uuid,
            char_name=char_info.get("name", "Unknown"),
            data=bytes(data),
        )
        self.events.append(event)
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Event callback error: {e}")

    def _notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Legacy transport: a raw 000c characteristic maps 1:1 to an event."""
        self._dispatch(characteristic.uuid, data)

    def _mpid_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        for payload in self._session.feed(bytes(data)):
            msg = parse_message(payload)
            if msg.info is not None:                       # DeviceInfo heartbeat
                self.device_info = msg.info
                if self.info:
                    if msg.info.semantic_firmware_version:
                        self.info.firmware_version = msg.info.semantic_firmware_version
                    if msg.info.serial_number:
                        self.info.serial_number = msg.info.serial_number
            for cb in self._message_callbacks:
                try:
                    cb(msg)
                except Exception as e:
                    print(f"Message callback error: {e}")
            for char_uuid, edata in to_legacy_events(msg):
                self._dispatch(char_uuid, edata)

    async def start_monitoring(self):
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")

        if self.transport == "mpid":
            await self._start_mpid()
        else:
            await self._start_legacy()

    async def _start_mpid(self):
        self._session = MpidSession()
        await self.client.start_notify(CHAR_TXRX, self._mpid_handler)
        token = bytes(await self.client.read_gatt_char(CHAR_FACTORY))
        session_payload = self._session.start_session(token)
        # The portal serial lives in the FACTORY token, not the heartbeat
        # DeviceInfo (firmware 1.0.9 omits serial_number there).
        if self.info and self._session.token and self._session.token.serial:
            try:
                self.info.serial_number = self._session.token.serial.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                pass
        await self.client.write_gatt_char(CHAR_SESSION, session_payload, response=True)

    async def _start_legacy(self):
        for char_uuid in NOTIFY_CHARACTERISTICS:
            try:
                await self.client.start_notify(char_uuid, self._notification_handler)
            except Exception:
                pass  # not every characteristic supports notifications

    async def stop_monitoring(self):
        if not self.is_connected:
            return
        chars = [CHAR_TXRX] if self.transport == "mpid" else NOTIFY_CHARACTERISTICS
        for char_uuid in chars:
            try:
                await self.client.stop_notify(char_uuid)
            except Exception:
                pass

    async def send_command(self, data: bytes):
        """Send a command to the portal (encrypted on MPID, raw on legacy)."""
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")
        if self.transport == "mpid":
            if self._session is None:
                raise RuntimeError("MPID session not established; call start_monitoring() first")
            await self.client.write_gatt_char(CHAR_TXRX, self._session.encrypt_packet(data), response=True)
        else:
            await self.client.write_gatt_char(CHAR_COMMAND, data)

    # -- high-level commands (MPID; AppToPortal.Command) --------------------
    async def request_device_info(self):
        await self.send_command(cmd_request_device_info())

    async def set_mode(self, mode: DeviceMode):
        await self.send_command(cmd_set_mode(mode))


    async def clear_bonding(self):
        await self.send_command(cmd_clear_bonding())

    async def read_control_register(self) -> bytes:
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")
        return bytes(await self.client.read_gatt_char(CHAR_CONTROL))

    async def write_control_register(self, data: bytes):
        if not self.is_connected:
            raise ConnectionError("Not connected to portal")
        await self.client.write_gatt_char(CHAR_CONTROL, data)

    def get_events(self, characteristic: str | None = None) -> list[PortalEvent]:
        if characteristic is None:
            return self.events.copy()
        return [e for e in self.events if e.characteristic == characteristic]

    def clear_events(self):
        self.events.clear()
