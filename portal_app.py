#!/usr/bin/env python3
"""
Hot Wheels Portal Application

A simple CLI application to connect to and monitor the Hot Wheels id Race Portal.
"""

import asyncio
import sys
from datetime import datetime

from common_lib import HotWheelsPortal
from common_lib.constants import (
    CHAR_EVENT_1, CHAR_EVENT_2, CHAR_EVENT_3,
    CHAR_CONTROL, CHAR_SERIAL_NUMBER
)
from common_lib.mpid import decode_car_event, decode_ndef_record, decode_speed_event


def print_header():
    """Print application header."""
    print()
    print("=" * 60)
    print("    HOT WHEELS id PORTAL")
    print("    Community Open Source Tool")
    print("=" * 60)
    print()


# Store current car info for display
current_car = {
    "nfc_uid": None,
    "serial": None,
    "mattel_id": None,
    "name": None,
}


# decode_car_event / decode_ndef_record / decode_speed_event now live in
# common_lib.mpid (single source of truth, shared by all transports + apps).


def decode_control_register(data: bytes) -> dict:
    """Decode Control Register status."""
    if len(data) < 5:
        return {"raw": data.hex()}

    # Pattern: 00 fe 00 fe 00
    # Appears to be status flags or heartbeat
    return {
        "byte0": data[0],
        "byte1": data[1],  # fe = 254, might be sensor status
        "byte2": data[2],
        "byte3": data[3],  # fe = 254
        "byte4": data[4],
        "pattern": "heartbeat/status"
    }


def event_handler(event):
    """Handle portal events."""
    global current_car
    data = event.data

    # Decode based on characteristic
    if event.characteristic == CHAR_EVENT_1:
        # Full NFC NDEF record - car identity
        if len(data) == 0:
            # Car removed
            print(f"\n  <<< CAR REMOVED")
            current_car = {"nfc_uid": None, "serial": None, "mattel_id": None, "name": None}
        else:
            decoded = decode_ndef_record(data)
            if "mattel_id" in decoded:
                current_car["mattel_id"] = decoded["mattel_id"]
                print(f"\n  >>> CAR NFC DATA")
                print(f"      Mattel ID: {decoded['mattel_id'][:40]}...")
                if "signature_len" in decoded:
                    print(f"      Signature: {decoded['signature_len']} bytes")

    elif event.characteristic == CHAR_EVENT_2:
        # Car detection event (NFC UID)
        if len(data) < 7:
            return  # Empty = car removed, handled above
        decoded = decode_car_event(data)
        current_car["nfc_uid"] = decoded.get('nfc_uid')
        print(f"\n  >>> CAR DETECTED")
        print(f"      NFC UID: {decoded.get('nfc_uid', 'unknown')}")

    elif event.characteristic == CHAR_SERIAL_NUMBER:
        # Car serial number
        if len(data) > 0:
            serial = data.decode('utf-8', errors='replace')
            current_car["serial"] = serial
            print(f"      Serial: {serial}")

    elif event.characteristic == CHAR_EVENT_3:
        # Speed/timing event
        decoded = decode_speed_event(data)
        raw = decoded.get('raw_float', 0)
        scaled = decoded.get('scaled_mph', 0)
        print(f"\n  >>> SPEED DATA")
        print(f"      Raw Value: {raw:.4f}")
        print(f"      Scaled (x64): {scaled:.1f} scale-mph")

    elif event.characteristic == CHAR_CONTROL:
        # Control register - decode status
        if len(data) >= 5:
            # Byte 4 seems to indicate car presence: 00=none, 02=car present
            car_present = data[4]
            if car_present == 0x02:
                pass  # Car present, normal
            elif car_present == 0x00 and data.hex() != "00729bfe00":
                pass  # Transitional state
            # Only print unusual patterns
            if data.hex() not in ["00fe00fe00", "00fe00fe02", "00729bfe00"]:
                print(f"\n  >>> CONTROL: {data.hex()}")

    else:
        # Other events
        print(f"\n  >>> EVENT [{event.char_name}]: {data.hex()}")


def make_device_info_handler(portal):
    """Structured-message callback (MPID). Firmware/hardware/battery come from
    the DeviceInfo heartbeat; the serial is sourced from the FACTORY token
    (this firmware omits serial_number from the heartbeat) via portal.info."""
    shown = {"done": False}

    def handler(msg):
        if msg.info is None:
            return
        info = msg.info
        if not shown["done"]:
            shown["done"] = True
            serial = (portal.info.serial_number if portal.info else "") or "(unavailable)"
            print("\n  >>> PORTAL INFO")
            print(f"      Firmware: {info.semantic_firmware_version or info.firmware_version}")
            print(f"      Serial:   {serial}")
            print(f"      Hardware: {info.hardware_version}")
        print(f"      Battery:  {info.battery_level:.0%} "
              f"({info.battery_status.name}, {info.mode.name})")

    return handler


async def main():
    """Main application entry point."""
    print_header()

    # Check for command line arguments
    address = sys.argv[1] if len(sys.argv) > 1 else None

    # Scan for portals
    if address is None:
        print("Scanning for Hot Wheels Portal...")
        portals = await HotWheelsPortal.scan(timeout=20.0)

        if not portals:
            print("\nNo portal found!")
            print("Make sure your Hot Wheels id Race Portal is:")
            print("  1. Powered on (batteries installed)")
            print("  2. Not connected to another device")
            print("  3. Within Bluetooth range")
            return

        print(f"\nFound {len(portals)} portal(s):")
        for i, (addr, name) in enumerate(portals):
            print(f"  [{i}] {name} ({addr})")

        if len(portals) > 1:
            choice = input("\nSelect portal number: ").strip()
            try:
                address = portals[int(choice)][0]
            except (ValueError, IndexError):
                print("Invalid selection")
                return
        else:
            address = portals[0][0]

    # Connect and monitor
    print(f"\nConnecting to portal at {address}...")

    try:
        async with HotWheelsPortal(address) as portal:
            info = await portal.get_info()

            print("\n" + "-" * 60)
            print("PORTAL CONNECTED")
            print("-" * 60)
            print(f"  Address: {info.address}")
            print(f"  Transport: {portal.transport}")

            if portal.transport == "mpid":
                # Firmware/serial are not readable characteristics on MPID; they
                # arrive in the DeviceInfo heartbeat once monitoring starts.
                print("  Firmware: (from heartbeat after connect)")
                print("  Serial:   (from heartbeat after connect)")
            else:
                print(f"  Firmware: {info.firmware_version}")
                print(f"  Serial: {info.serial_number}")
                if info.device_key:
                    key_str = info.device_key[:50].decode("utf-8", errors="replace")
                    print(f"  Device ID: {key_str[:30]}...")

            # Read control register (legacy 000c transport only; absent on MPID)
            try:
                ctrl = await portal.read_control_register()
                print(f"  Control: {ctrl.hex()}")
            except Exception:
                pass

            # Register event handlers
            portal.on_event(event_handler)
            portal.on_message(make_device_info_handler(portal))

            # Start monitoring
            await portal.start_monitoring()

            print("\n" + "-" * 60)
            print("MONITORING FOR EVENTS")
            print("-" * 60)
            print("Now monitoring for portal events.")
            print("Try:")
            print("  - Placing a Hot Wheels id car on the portal")
            print("  - Running a car through the portal")
            print("  - Removing a car from the portal")
            print()
            print("Press Ctrl+C to stop")
            print("-" * 60)

            # Monitor until interrupted
            try:
                while True:
                    await asyncio.sleep(0.1)
            except KeyboardInterrupt:
                print("\n\nStopping...")

            # Stop monitoring
            await portal.stop_monitoring()

            # Summary
            events = portal.get_events()
            print("\n" + "-" * 60)
            print("SESSION SUMMARY")
            print("-" * 60)
            print(f"Total events captured: {len(events)}")

            if events:
                # Group by characteristic
                by_char = {}
                for e in events:
                    by_char.setdefault(e.char_name, []).append(e)

                print("\nEvents by type:")
                for name, char_events in sorted(by_char.items()):
                    print(f"  {name}: {len(char_events)}")

                # Save events to file
                filename = f"portal_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(filename, "w") as f:
                    f.write(f"Hot Wheels Portal Event Log\n")
                    f.write(f"Portal: {info.serial_number}\n")
                    f.write(f"Firmware: {info.firmware_version}\n")
                    f.write(f"=" * 60 + "\n\n")

                    for e in events:
                        f.write(f"{e}\n")
                        f.write(f"  Raw: {list(e.data)}\n\n")

                print(f"\nEvents saved to: {filename}")

    except ConnectionError as e:
        print(f"\nConnection error: {e}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
