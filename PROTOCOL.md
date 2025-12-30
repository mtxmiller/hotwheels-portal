# Hot Wheels id Portal BLE Protocol

**Device Name:** HWiD
**Manufacturer:** Mattel
**Firmware:** 1.2.5

## BLE Services Overview

The portal exposes 3 custom services, all using the base UUID `af0a6ec7-xxxx-xxxx-84a0-91559fc6f0de`.

---

## Service A: Authentication (`af0a6ec7-0001-000a-...`)

| Characteristic | Properties | Purpose |
|----------------|------------|---------|
| 0002-000a | write, indicate | Command channel |
| 0003-000a | read | Device key/certificate (148 bytes) |
| 0004-000a | write, indicate | Response channel |

---

## Service B: Data Transfer (`af0a6ec7-0001-000b-...`)

| Characteristic | Properties | Purpose |
|----------------|------------|---------|
| 0002-000b | write, indicate | Bulk data commands |
| 0003-000b | write-without-response | Fast data transfer |

---

## Service C: Portal Control (`af0a6ec7-0001-000c-...`)

| Characteristic | Properties | Purpose |
|----------------|------------|---------|
| 0002-000c | read | Firmware version |
| 0003-000c | read, indicate | **Car Serial Number** (changes per car!) |
| 0004-000c | indicate | **Event Channel 1: NFC NDEF Record** |
| 0005-000c | indicate | **Event Channel 2: Car Detection (NFC UID)** |
| 0006-000c | indicate | **Event Channel 3: Speed Data** |
| 0007-000c | write, read, indicate | Control register |
| 0008-000c | write, indicate | Command channel |

---

## Event Data Formats

### Event Channel 1 (0004-000c): NFC NDEF Record

Contains the full NFC tag data from the car in NDEF format.

**Structure:**
```
91 01 28 55 02 [URI payload] [signature]
│  │  │  │  │
│  │  │  │  └─ URI prefix: 02 = "https://www."
│  │  │  └──── Type: 'U' (URI record)
│  │  └─────── Payload length: 0x28 = 40 bytes
│  └────────── Type length: 1
└───────────── NDEF header (TNF=1, SR=1, MB=1)
```

**URI Format:** `https://www.pid.mattel/[base64-encoded-car-id]`

**Car ID Structure (base64 decoded):**
```
Offset  Size  Description
0       2     Version (01 00)
2       4     Car Type/Model ID
6       4     Flags/Metadata
10+     var   Additional data
-6      6     NFC UID (last 6 bytes)
```

### Event Channel 2 (0005-000c): Car Detection

Sent when a car is placed on or removed from the portal.

**Format:** `04 [6-byte NFC UID]`

| Byte | Value | Meaning |
|------|-------|---------|
| 0 | 0x04 | Event type: Car detected |
| 1-6 | UID | 6-byte NFC UID |

**Empty data** = Car removed

**Example:** `04 6c c4 5a 2b 64 81` → NFC UID: `6C:C4:5A:2B:64:81`

### Event Channel 3 (0006-000c): Speed Data

Contains speed/timing measurements as IEEE 754 float32.

**Format:** 4 bytes, little-endian float

**Examples:**
| Hex | Float Value | Meaning |
|-----|-------------|---------|
| `b01c143e` | 0.1446 | Slow/stationary |
| `ae388c3f` | 1.0955 | Medium speed |
| `abaaca3f` | 1.5833 | Fast |

The raw float may represent:
- Speed in m/s (multiply by 64 for "scale speed")
- Time in seconds for sensor passage

### Serial Number (0003-000c): Car Serial

Changes to show the **current car's serial number** when a car is detected.

**Format:** ASCII string (e.g., "1102032557")

**Empty data** = Car removed

---

## Control Register (0007-000c)

**Format:** 5 bytes

| Pattern | Meaning |
|---------|---------|
| `00 fe 00 fe 00` | Idle/heartbeat |
| `00 fe 00 fe 02` | Car present |
| `00 72 9b fe 00` | Transitional state |

---

## Car Database

| NFC UID | Serial | Mattel ID |
|---------|--------|-----------|
| `4A:8F:52:88:5D:81` | 1102032557 | `AQBBr66t...` |
| `AC:BC:82:20:5C:80` | 1101783036 | `AQBBq9_8...` |
| `75:E9:5A:61:62:80` | 1101783096 | `AQBBq-A4...` |

---

## Protocol Flow

1. **Connect** to device named "HWiD"
2. **Subscribe** to indicate characteristics (0004-0008)
3. **Car Placed:**
   - Control register → `00 fe 00 fe 02`
   - Serial Number → Car's serial (ASCII)
   - Event Channel 2 → `04` + NFC UID
   - Event Channel 1 → Full NDEF record
4. **Car Moved Through Portal:**
   - Event Channel 3 → Speed float
5. **Car Removed:**
   - Event Channel 1 → empty
   - Event Channel 2 → empty
   - Serial Number → empty
   - Control register → `00 72 9b fe 00`
