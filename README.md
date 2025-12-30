# Hot Wheels Portal

An open-source tool to connect to and interact with the Hot Wheels id Race Portal, restoring functionality after the official app was discontinued.

## Background

The Hot Wheels id system used Bluetooth Low Energy (BLE) to communicate between the Race Portal and mobile devices. The official app was discontinued on January 1, 2024. This project aims to reverse engineer the protocol and provide an open-source alternative.

## Features

- [x] BLE device scanning and discovery
- [x] Connect to Hot Wheels Race Portal
- [x] Read portal info (firmware, serial number)
- [x] Monitor for portal events
- [ ] Read car data via NFC (through portal)
- [ ] View speed and lap statistics
- [ ] Export data

## Requirements

- Python 3.10+
- macOS, Windows, or Linux with BLE support
- Hot Wheels id Race Portal (FXB53)

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/hotwheels-portal.git
cd hotwheels-portal

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Quick Start

```bash
# Activate the virtual environment
source venv/bin/activate

# Run the main application
python portal_app.py
```

The app will:
1. Scan for your Hot Wheels Portal
2. Connect and display device info
3. Monitor for events (car placement, speed, etc.)

### Other Tools

```bash
# Scan for all BLE devices
python scanner.py

# Monitor portal events (detailed output)
python monitor.py
```

### Using as a Library

```python
import asyncio
from hwportal import HotWheelsPortal

async def main():
    async with HotWheelsPortal() as portal:
        info = await portal.get_info()
        print(f"Firmware: {info.firmware_version}")
        print(f"Serial: {info.serial_number}")

        # Monitor events
        portal.on_event(lambda e: print(f"Event: {e}"))
        await portal.start_monitoring()

        # Keep running...
        await asyncio.sleep(60)

asyncio.run(main())
```

## Protocol Documentation

See [PROTOCOL.md](PROTOCOL.md) for detailed documentation of the BLE protocol.

### Quick Reference

| Service | Purpose |
|---------|---------|
| `af0a6ec7-0001-000a-*` | Authentication/Security |
| `af0a6ec7-0001-000b-*` | Data Transfer (NFC?) |
| `af0a6ec7-0001-000c-*` | Portal Control |

**Device Name:** `HWiD`

## Project Structure

```
portal/
├── hwportal/           # Main library
│   ├── __init__.py
│   ├── constants.py    # BLE UUIDs and constants
│   └── portal.py       # HotWheelsPortal class
├── portal_app.py       # Main CLI application
├── scanner.py          # BLE device scanner
├── monitor.py          # Event monitor (detailed)
├── PROTOCOL.md         # Protocol documentation
└── requirements.txt    # Python dependencies
```

## Contributing

Contributions welcome! Areas that need help:

1. **Protocol Analysis** - Help decode event data formats
2. **Car NFC Data** - Document the NFC chip data structure
3. **Speed/Lap Calculation** - Implement the speed measurement logic
4. **GUI** - Build a graphical interface

If you have a Hot Wheels Portal, run the monitor and share your event logs!

## License

MIT License - see LICENSE file for details.

## Disclaimer

This project is not affiliated with Mattel or Hot Wheels. It's a community effort to restore functionality to discontinued hardware.

## Resources

- [Hot Wheels id Wiki](https://hotwheels.fandom.com/wiki/Hot_Wheels_id)
- [Bleak BLE Library](https://github.com/hbldh/bleak)
- [BLE Protocol Guide](https://reverse-engineering-ble-devices.readthedocs.io/)
