#!/usr/bin/env python3
"""
Hot Wheels Portal Event Monitor

Connects to the portal and monitors all indicate characteristics
for events (car detection, speed, laps, etc.)
"""

import asyncio
import sys
from datetime import datetime
from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic


# Portal device name
PORTAL_NAME = "HWiD"

# Service and characteristic UUIDs
SERVICE_A = "af0a6ec7-0001-000a-84a0-91559fc6f0de"
SERVICE_B = "af0a6ec7-0001-000b-84a0-91559fc6f0de"
SERVICE_C = "af0a6ec7-0001-000c-84a0-91559fc6f0de"

# Characteristics that support indications (event notifications)
INDICATE_CHARS = {
    "af0a6ec7-0002-000a-84a0-91559fc6f0de": "Auth Command Response",
    "af0a6ec7-0004-000a-84a0-91559fc6f0de": "Auth Response",
    "af0a6ec7-0002-000b-84a0-91559fc6f0de": "Data Transfer Response",
    "af0a6ec7-0003-000c-84a0-91559fc6f0de": "Serial/Status",
    "af0a6ec7-0004-000c-84a0-91559fc6f0de": "Event Channel 1",
    "af0a6ec7-0005-000c-84a0-91559fc6f0de": "Event Channel 2",
    "af0a6ec7-0006-000c-84a0-91559fc6f0de": "Event Channel 3",
    "af0a6ec7-0007-000c-84a0-91559fc6f0de": "Control Register",
    "af0a6ec7-0008-000c-84a0-91559fc6f0de": "Command Response",
}

# Readable characteristics
READ_CHARS = {
    "af0a6ec7-0003-000a-84a0-91559fc6f0de": "Device Key",
    "af0a6ec7-0002-000c-84a0-91559fc6f0de": "Firmware Version",
    "af0a6ec7-0003-000c-84a0-91559fc6f0de": "Serial Number",
    "af0a6ec7-0007-000c-84a0-91559fc6f0de": "Control Register",
}


class PortalMonitor:
    def __init__(self):
        self.client = None
        self.event_log = []

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handle incoming notifications/indications from the portal."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        char_name = INDICATE_CHARS.get(characteristic.uuid, "Unknown")

        # Log the event
        event = {
            "timestamp": timestamp,
            "characteristic": characteristic.uuid,
            "name": char_name,
            "handle": characteristic.handle,
            "data_hex": data.hex(),
            "data_raw": bytes(data),
        }
        self.event_log.append(event)

        # Print the event
        print(f"\n{'='*60}")
        print(f"[{timestamp}] EVENT on {char_name}")
        print(f"  Characteristic: {characteristic.uuid}")
        print(f"  Handle: {characteristic.handle}")
        print(f"  Data (hex): {data.hex()}")
        print(f"  Data (bytes): {list(data)}")

        # Try to decode as string
        try:
            decoded = data.decode("utf-8", errors="strict")
            if decoded.isprintable():
                print(f"  Data (str): {decoded}")
        except:
            pass

        # Analyze known patterns
        self.analyze_event(char_name, data)

    def analyze_event(self, char_name: str, data: bytearray):
        """Attempt to analyze the event data."""
        if len(data) == 0:
            print("  Analysis: Empty data")
            return

        # Event channels might have specific formats
        if "Event Channel" in char_name:
            if len(data) >= 1:
                event_type = data[0]
                print(f"  Analysis: Event type byte = {event_type:02x}")

                # Guess at event types
                if event_type == 0x01:
                    print("  Possible: Car detected/placed")
                elif event_type == 0x02:
                    print("  Possible: Car removed")
                elif event_type == 0x03:
                    print("  Possible: Speed/lap data")

            if len(data) >= 4:
                # Look for potential numeric values (little-endian)
                value = int.from_bytes(data[1:5] if len(data) >= 5 else data[1:], "little")
                print(f"  Possible value (LE): {value}")

    async def find_portal(self) -> str | None:
        """Scan for the Hot Wheels portal."""
        print("Scanning for Hot Wheels Portal...")
        devices = await BleakScanner.discover(timeout=10.0)

        for device in devices:
            if device.name and PORTAL_NAME.lower() in device.name.lower():
                print(f"Found portal: {device.name} ({device.address})")
                return device.address

        return None

    async def read_device_info(self, client: BleakClient):
        """Read and display device information."""
        print("\n" + "=" * 60)
        print("DEVICE INFORMATION")
        print("=" * 60)

        for uuid, name in READ_CHARS.items():
            try:
                value = await client.read_gatt_char(uuid)
                print(f"\n{name}:")
                print(f"  UUID: {uuid}")
                print(f"  Hex: {value.hex()}")
                try:
                    decoded = value.decode("utf-8", errors="strict")
                    if decoded.isprintable():
                        print(f"  String: {decoded}")
                except:
                    print(f"  Bytes: {list(value)}")
            except Exception as e:
                print(f"\n{name}: Error reading - {e}")

    async def subscribe_to_events(self, client: BleakClient):
        """Subscribe to all indication characteristics."""
        print("\n" + "=" * 60)
        print("SUBSCRIBING TO EVENT NOTIFICATIONS")
        print("=" * 60)

        for uuid, name in INDICATE_CHARS.items():
            try:
                await client.start_notify(uuid, self.notification_handler)
                print(f"  Subscribed: {name}")
            except Exception as e:
                print(f"  Failed to subscribe to {name}: {e}")

    async def run(self, address: str | None = None):
        """Main monitoring loop."""
        # Find or use provided address
        if address is None:
            address = await self.find_portal()
            if address is None:
                print("Portal not found. Make sure it's powered on.")
                return

        print(f"\nConnecting to portal at {address}...")

        try:
            async with BleakClient(address) as client:
                self.client = client
                print(f"Connected: {client.is_connected}")

                # Read device info
                await self.read_device_info(client)

                # Subscribe to events
                await self.subscribe_to_events(client)

                print("\n" + "=" * 60)
                print("MONITORING FOR EVENTS")
                print("Place cars on portal, run them through, etc.")
                print("Press Ctrl+C to stop")
                print("=" * 60)

                # Keep running until interrupted
                try:
                    while True:
                        await asyncio.sleep(0.1)
                except KeyboardInterrupt:
                    print("\n\nStopping monitor...")

                # Show summary
                self.print_summary()

        except Exception as e:
            print(f"Error: {e}")

    def print_summary(self):
        """Print summary of captured events."""
        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Total events captured: {len(self.event_log)}")

        if self.event_log:
            print("\nEvents by characteristic:")
            char_counts = {}
            for event in self.event_log:
                name = event["name"]
                char_counts[name] = char_counts.get(name, 0) + 1

            for name, count in sorted(char_counts.items()):
                print(f"  {name}: {count}")

            # Save to file
            filename = f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            with open(filename, "w") as f:
                for event in self.event_log:
                    f.write(f"{event['timestamp']} | {event['name']} | {event['data_hex']}\n")
            print(f"\nEvents saved to: {filename}")


async def main():
    address = sys.argv[1] if len(sys.argv) > 1 else None

    monitor = PortalMonitor()
    await monitor.run(address)


if __name__ == "__main__":
    asyncio.run(main())
