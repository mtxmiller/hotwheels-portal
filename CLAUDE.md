# CLAUDE.md - Hot Wheels Portal Project Guide

## Project Overview

This is an open-source reverse-engineering project to restore functionality to the Hot Wheels id Race Portal after Mattel discontinued the official app on January 1, 2024. The project uses Python with Bluetooth Low Energy (BLE) to communicate with the portal hardware.

## Tech Stack

- **Python 3.10+** - Main language
- **Bleak** - Cross-platform BLE library (macOS/Windows/Linux)
- **Rich** - Terminal UI library for dashboards and game modes
- **asyncio** - Async/await for BLE communication

## Project Structure

```
portal/
├── hwportal/              # Core library
│   ├── __init__.py        # Package exports
│   ├── constants.py       # BLE UUIDs and protocol constants
│   └── portal.py          # HotWheelsPortal class
├── dashboard.py           # Live speedometer dashboard
├── race_mode.py           # Lap race game with leaderboard
├── portal_app.py          # Detailed event monitor
├── scanner.py             # BLE device scanner
├── monitor.py             # Raw event monitor
├── PROTOCOL.md            # BLE protocol documentation
└── requirements.txt       # Python dependencies
```

## Key Files

### hwportal/portal.py
Main `HotWheelsPortal` class - async context manager for connecting to portal:
```python
async with HotWheelsPortal() as portal:
    info = await portal.get_info()
    portal.on_event(callback)
    await portal.start_monitoring()
```

### hwportal/constants.py
All BLE UUIDs and characteristic definitions. Key ones:
- `CHAR_EVENT_1` - NFC NDEF data (car identity)
- `CHAR_EVENT_2` - Car detection (NFC UID)
- `CHAR_EVENT_3` - Speed data (IEEE 754 float32)
- `CHAR_SERIAL_NUMBER` - Changes to show current car's serial

### dashboard.py
Rich-based live dashboard with:
- Visual speedometer gauge (color zones, needle)
- Car info panel
- Recent passes history
- Special effects (flames 🔥 at 100+ mph)

### race_mode.py
Game mode with states: MENU → NAME_ENTRY → SETUP → COUNTDOWN → RACING → FINISHED → LEADERBOARD

## BLE Protocol Quick Reference

**Device Name:** `HWiD`

**Services:**
- `af0a6ec7-0001-000a-*` - Authentication
- `af0a6ec7-0001-000b-*` - Data transfer
- `af0a6ec7-0001-000c-*` - Portal control (main service)

**Event Data Formats:**
- **Car Detection:** `04` + 6-byte NFC UID
- **Speed:** 4-byte little-endian float32 (multiply by 64 for "scale mph")
- **Serial Number:** ASCII string (e.g., "1102032557")

See PROTOCOL.md for full documentation.

## Development Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run apps
python dashboard.py      # Live speedometer
python race_mode.py      # Lap race game
python portal_app.py     # Event monitor
python scanner.py        # Find BLE devices
```

## Issue Tracking

Using `bd` (beads) for issue tracking:
```bash
bd list                  # Show all issues
bd create "title" -t feature -p 1  # Create issue
bd close hwportal-xxx    # Close issue
```

## Code Style

- Use async/await for all BLE operations
- Rich library for terminal UI (Panel, Layout, Table, Text)
- Dataclasses for structured data (CarStats, RaceResult, PortalInfo)
- Type hints throughout

## Testing

No formal test suite yet. Manual testing with physical portal:
```bash
python -c "from hwportal import HotWheelsPortal; ..."
```

## Common Patterns

### Event handling
```python
def handle_event(event):
    if event.characteristic == CHAR_EVENT_3:
        speed = struct.unpack('<f', event.data[:4])[0] * 64
```

### Rich UI panels
```python
def create_panel(self) -> Panel:
    text = Text()
    text.append("Title\n", style="bold")
    return Panel(Align.center(text), title="Panel", border_style="green")
```

### Game state machine
```python
class GameState(Enum):
    MENU = auto()
    RACING = auto()
    FINISHED = auto()

if self.state == GameState.MENU:
    # handle menu
```

## Known Limitations

- Terminal input requires Unix (macOS/Linux) for raw mode
- BLE connection can be flaky - may need to retry
- Speed values are relative (not calibrated to real units)
- No persistent storage yet (results lost on exit)

## Future Features (see bd list)

- Persistent car database (JSON storage)
- Car name lookup from Mattel ID
- Achievement system
- Car collection/garage view
