# Hot Wheels Portal 🏎️

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)](https://github.com/mtxmiller/hotwheels-portal)

**Bring your Hot Wheels id Race Portal back to life!**

An open-source tool to connect to the Hot Wheels id Race Portal after Mattel discontinued the official app on January 1, 2024. We reverse-engineered the Bluetooth protocol so you can track speeds, lap times, and build your car collection again.

## What It Does

- **Detect cars** - Reads NFC UID and serial number when you place a car on the portal
- **Track speed** - Measures speed as cars pass through (in "scale mph")
- **Count laps** - Tracks lap times and calculates best/average times
- **Live dashboard** - Beautiful terminal UI with real-time stats
- **Multi-car support** - Tracks stats for each car individually

## Live Dashboard

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃            🏎️  HOT WHEELS PORTAL DASHBOARD  🏎️                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━ 🚗 Current Car ━━━━━━━┓┏━━━━━━━ 📊 Recent Passes ━━━━━━┓
┃ NFC UID:  4A:8F:52:88:5D:81  ┃┃ #    Time     Speed    Lap    ┃
┃ Serial:   1102032557         ┃┃ 12   12:01:03  94.5 mph  4.2s ┃
┃ Laps:     5                  ┃┃ 11   12:00:58  50.5 mph  5.1s ┃
┃                              ┃┃ 10   12:00:52  46.9 mph  4.8s ┃
┃ ████████████████░░░░ 94.5 mph┃┃ 9    12:00:45  88.2 mph  3.9s ┃
┃ Best Speed: 94.5 mph         ┃┃ 8    12:00:38  72.1 mph  4.5s ┃
┃ Best Lap:   3.9s             ┃┃                               ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Status: Pass #12  │  Session: 5m 23s  │  Cars Seen: 3        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

## Quick Start

```bash
# Clone the repo
git clone https://github.com/mtxmiller/hotwheels-portal.git
cd hotwheels-portal

# Set up Python environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run the dashboard
python dashboard.py
```

## Requirements

- **Python 3.10+**
- **macOS, Windows, or Linux** with Bluetooth Low Energy support
- **Hot Wheels id Race Portal** (Model FXB53)
- **Hot Wheels id cars** (with NFC chips)

## Available Tools

| Command | Description |
|---------|-------------|
| `python dashboard.py` | Live dashboard with speed & lap tracking |
| `python portal_app.py` | Detailed event monitor with car data |
| `python scanner.py` | Scan for BLE devices |
| `python monitor.py` | Raw event monitor for debugging |

## Using as a Library

```python
import asyncio
from hwportal import HotWheelsPortal

async def main():
    async with HotWheelsPortal() as portal:
        info = await portal.get_info()
        print(f"Firmware: {info.firmware_version}")
        print(f"Serial: {info.serial_number}")

        # Get notified of events
        portal.on_event(lambda e: print(f"Event: {e}"))
        await portal.start_monitoring()

        await asyncio.sleep(60)

asyncio.run(main())
```

## Protocol Documentation

We've fully reverse-engineered the BLE protocol! See [PROTOCOL.md](PROTOCOL.md) for details.

**Key discoveries:**
- Device advertises as `HWiD`
- 3 BLE services for auth, data transfer, and control
- Car detection via NFC UID (6 bytes)
- Speed data as IEEE 754 float32
- Full NDEF records with Mattel car IDs

## Project Structure

```
hotwheels-portal/
├── hwportal/           # Python library
│   ├── __init__.py
│   ├── constants.py    # BLE UUIDs
│   └── portal.py       # HotWheelsPortal class
├── dashboard.py        # Live terminal dashboard
├── portal_app.py       # Event monitor app
├── scanner.py          # BLE scanner
├── monitor.py          # Raw event monitor
├── PROTOCOL.md         # Protocol documentation
└── requirements.txt
```

## Roadmap

- [x] BLE connection and event monitoring
- [x] Car detection (NFC UID, serial)
- [x] Speed tracking
- [x] Live dashboard
- [ ] Persistent car database
- [ ] Race mode with countdown
- [ ] Car collection/garage view
- [ ] Achievement system
- [ ] Car name lookup from Mattel ID

## Contributing

We'd love your help! Here's how:

1. **Got a Portal?** Run the tools and share interesting findings
2. **Know BLE/NFC?** Help decode remaining protocol mysteries
3. **Want features?** Check the issues and submit PRs

```bash
# Run the monitor and capture events
python monitor.py > my_events.log
```

## Why This Exists

Mattel discontinued the Hot Wheels id app on January 1, 2024, leaving thousands of Race Portals as paperweights. This project aims to restore functionality through reverse engineering, letting Hot Wheels fans continue to enjoy their hardware.

## Support the Project

If this project helped bring your Hot Wheels Portal back to life, consider supporting development:

- ⭐ **Star this repository**
- 💖 **[Sponsor on GitHub](https://github.com/sponsors/mtxmiller)**
- 🐛 **Report issues** and suggest features

[![Sponsor](https://img.shields.io/github/sponsors/mtxmiller?style=for-the-badge&logo=github&label=Sponsor)](https://github.com/sponsors/mtxmiller)

### PayPal Donations

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/ncp/payment/WWXW56JQE4GR4)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Disclaimer

This project is not affiliated with Mattel or Hot Wheels. It's a community effort to restore functionality to discontinued hardware. Hot Wheels is a trademark of Mattel, Inc.

## Resources

- [Hot Wheels id Wiki](https://hotwheels.fandom.com/wiki/Hot_Wheels_id)
- [Bleak BLE Library](https://github.com/hbldh/bleak)
- [Rich Terminal Library](https://github.com/Textualize/rich)
