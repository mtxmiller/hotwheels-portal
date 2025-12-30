#!/usr/bin/env python3
"""
Hot Wheels Portal Application

A simple CLI application to connect to and monitor the Hot Wheels id Race Portal.
"""

import asyncio
import base64
import struct
import sys
from datetime import datetime

from hwportal import HotWheelsPortal
from hwportal.constants import (
    CHAR_EVENT_1, CHAR_EVENT_2, CHAR_EVENT_3,
    CHAR_CONTROL, CHAR_SERIAL_NUMBER
)


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


def decode_car_event(data: bytes) -> dict:
    """Decode Event Channel 2 - Car detection (NFC UID)."""
    if len(data) < 7:
        return {"raw": data.hex()}

    event_type = data[0]
    nfc_uid = data[1:7].hex().upper()

    # Format NFC UID nicely
    nfc_formatted = ":".join(nfc_uid[i:i+2] for i in range(0, len(nfc_uid), 2))

    return {
        "event_type": event_type,
        "nfc_uid": nfc_formatted,
        "type_name": "Car Detected" if event_type == 0x04 else f"Unknown (0x{event_type:02x})"
    }


def decode_ndef_record(data: bytes) -> dict:
    """Decode Event Channel 1 - Full NFC NDEF record with car identity."""
    if len(data) < 10:
        return {"raw": data.hex()} if data else {"empty": True}

    result = {}

    # NDEF record structure:
    # Byte 0: Header (TNF + flags)
    # Byte 1: Type length
    # Byte 2: Payload length (if SR flag set)
    # Byte 3: Type
    # Byte 4+: Payload

    header = data[0]
    type_len = data[1]
    payload_len = data[2]
    record_type = data[3:3+type_len]

    # Check if it's a URI record (type = 'U' = 0x55)
    if record_type == b'U':
        # URI prefix code
        uri_prefix_code = data[4]
        uri_prefixes = {
            0x00: "",
            0x01: "http://www.",
            0x02: "https://www.",
            0x03: "http://",
            0x04: "https://",
        }
        prefix = uri_prefixes.get(uri_prefix_code, "")

        # URI content (rest of payload minus the prefix byte)
        uri_content = data[5:4+payload_len].decode('utf-8', errors='replace')
        full_uri = prefix + uri_content

        result["uri"] = full_uri

        # Parse Mattel car ID from URI
        if "pid.mattel/" in full_uri:
            # Extract the base64 part after pid.mattel/
            parts = full_uri.split("pid.mattel/")
            if len(parts) > 1:
                mattel_id = parts[1]
                result["mattel_id"] = mattel_id

                # Try to decode the base64 to see what's inside
                try:
                    # The ID might be URL-safe base64
                    decoded = base64.urlsafe_b64decode(mattel_id + "==")
                    result["mattel_id_decoded"] = decoded.hex()
                except:
                    pass

    # There's additional data after the URI record (signature/crypto data)
    ndef_end = 4 + payload_len
    if len(data) > ndef_end:
        extra_data = data[ndef_end:]
        result["signature"] = extra_data.hex()
        result["signature_len"] = len(extra_data)

    return result


def decode_speed_event(data: bytes) -> dict:
    """Decode Event Channel 3 - Speed/timing data (IEEE 754 float)."""
    if len(data) < 4:
        return {"raw": data.hex()}

    # Decode as little-endian float32
    speed_float = struct.unpack('<f', data[:4])[0]

    # Hot Wheels id uses 1:64 scale, so real speed would be scaled
    # The float might be in m/s or some internal unit
    scale_speed_mph = speed_float * 64  # Scale up for "real" speed

    return {
        "raw_float": speed_float,
        "scaled_mph": scale_speed_mph,
    }


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


async def main():
    """Main application entry point."""
    print_header()

    # Check for command line arguments
    address = sys.argv[1] if len(sys.argv) > 1 else None

    # Scan for portals
    if address is None:
        print("Scanning for Hot Wheels Portal...")
        portals = await HotWheelsPortal.scan(timeout=10.0)

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
            print(f"  Firmware: {info.firmware_version}")
            print(f"  Serial: {info.serial_number}")

            if info.device_key:
                # Parse the device key - it starts with device info
                key_str = info.device_key[:50].decode("utf-8", errors="replace")
                print(f"  Device ID: {key_str[:30]}...")

            # Read control register
            ctrl = await portal.read_control_register()
            print(f"  Control: {ctrl.hex()}")

            # Register event handler
            portal.on_event(event_handler)

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
