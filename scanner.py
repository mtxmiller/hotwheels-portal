#!/usr/bin/env python3
"""
Hot Wheels Portal BLE Scanner

Scans for BLE devices to find the Hot Wheels id Race Portal.
Once found, enumerates all services and characteristics.
"""

import asyncio
import sys
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


# Known potential device name patterns for Hot Wheels portal
# "HWiD" is the confirmed BLE name for Hot Wheels id Portal
KNOWN_NAMES = ["hwid", "hot wheels", "hotwheels", "hw", "mattel", "race portal", "portal"]


def is_potential_portal(name: str | None, address: str) -> bool:
    """Check if device might be a Hot Wheels Portal based on name."""
    if name is None:
        return False
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in KNOWN_NAMES)


async def scan_for_devices(duration: float = 10.0) -> list[BLEDevice]:
    """Scan for all BLE devices."""
    print(f"Scanning for BLE devices for {duration} seconds...")
    print("-" * 60)

    devices = await BleakScanner.discover(timeout=duration, return_adv=True)

    found_devices = []
    potential_portals = []

    for device, adv_data in devices.values():
        found_devices.append(device)

        # Print device info
        name = device.name or "Unknown"
        rssi = adv_data.rssi if adv_data else "N/A"
        print(f"  {device.address}: {name} (RSSI: {rssi})")

        # Check if this might be a portal
        if is_potential_portal(device.name, device.address):
            potential_portals.append(device)
            print(f"    ^^^ Potential Hot Wheels Portal!")

    print("-" * 60)
    print(f"Found {len(found_devices)} devices total")

    if potential_portals:
        print(f"\nPotential Hot Wheels Portals found: {len(potential_portals)}")
        for device in potential_portals:
            print(f"  - {device.name} ({device.address})")

    return found_devices


async def enumerate_device_services(device: BLEDevice):
    """Connect to a device and enumerate all services and characteristics."""
    print(f"\nConnecting to {device.name or device.address}...")

    try:
        async with BleakClient(device) as client:
            print(f"Connected: {client.is_connected}")
            print("\nServices and Characteristics:")
            print("=" * 60)

            for service in client.services:
                print(f"\nService: {service.uuid}")
                print(f"  Description: {service.description or 'Unknown'}")

                for char in service.characteristics:
                    props = ", ".join(char.properties)
                    print(f"\n  Characteristic: {char.uuid}")
                    print(f"    Properties: {props}")
                    print(f"    Handle: {char.handle}")

                    # Try to read if readable
                    if "read" in char.properties:
                        try:
                            value = await client.read_gatt_char(char.uuid)
                            print(f"    Value (hex): {value.hex()}")
                            try:
                                print(f"    Value (str): {value.decode('utf-8', errors='replace')}")
                            except:
                                pass
                        except Exception as e:
                            print(f"    Could not read: {e}")

                    # List descriptors
                    for desc in char.descriptors:
                        print(f"    Descriptor: {desc.uuid}")

    except Exception as e:
        print(f"Error connecting to device: {e}")


async def interactive_mode(devices: list[BLEDevice]):
    """Allow user to select a device to explore."""
    if not devices:
        print("No devices found to explore.")
        return

    print("\n" + "=" * 60)
    print("Select a device to explore (enter number) or 'q' to quit:")
    print("=" * 60)

    for i, device in enumerate(devices):
        name = device.name or "Unknown"
        print(f"  {i}: {name} ({device.address})")

    while True:
        try:
            choice = input("\nEnter device number (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                break

            idx = int(choice)
            if 0 <= idx < len(devices):
                await enumerate_device_services(devices[idx])
            else:
                print(f"Please enter a number between 0 and {len(devices) - 1}")
        except ValueError:
            print("Invalid input. Enter a number or 'q'.")
        except KeyboardInterrupt:
            print("\nExiting...")
            break


async def main():
    """Main entry point."""
    print("=" * 60)
    print("Hot Wheels Portal BLE Scanner")
    print("=" * 60)
    print()

    # Check for command line arguments
    if len(sys.argv) > 1:
        # Direct connection mode - user provided device address
        address = sys.argv[1]
        print(f"Attempting to connect directly to: {address}")

        # Create a minimal device object
        device = BLEDevice(address, address, {}, 0)
        await enumerate_device_services(device)
    else:
        # Scan mode
        devices = await scan_for_devices(duration=10.0)

        if devices:
            await interactive_mode(devices)
        else:
            print("\nNo BLE devices found. Make sure:")
            print("  1. Your Hot Wheels Portal is powered on")
            print("  2. Bluetooth is enabled on your Mac")
            print("  3. No other device is connected to the portal")


if __name__ == "__main__":
    asyncio.run(main())
