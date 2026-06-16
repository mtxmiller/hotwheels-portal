# Hot Wheels id Portal — MPID Protocol (reverse-engineered)

This document describes the **newer** protocol spoken by current Hot Wheels id
Race Portals, recovered by decompiling the official Mattel app's native library
(`libnative-lib.so` → `mpid-library`, `MpidLib.cpp`) with Ghidra and validated
live against real hardware.

This replaces an earlier `PROTOCOL.md` that was an AI hallucination — both its
`…-000c` "Portal Control" service layout *and* its payload formats were
fabricated and never matched real hardware (confirmed by Android and Windows BLE
scans, and by decrypting live traffic). On real hardware the data is delivered
as an **encrypted Protocol Buffers stream** over the authentication service,
after a key-exchange handshake; the payload formats below were recovered from the
decompiled library and the decrypted byte stream.

The reference implementation is [`hwportal/mpid.py`](hwportal/mpid.py); the
transport auto-detection lives in [`hwportal/portal.py`](hwportal/portal.py).

---

## Summary

| Layer | What it is |
|-------|------------|
| Transport | "MPID" (Mattel PID) — a generic Mattel BLE SDK (`blekit`) used across several toys |
| Key exchange | ECDH on NIST **P-256** (micro-ecc), device authenticated by a signed factory token |
| Session key | 100-round AES-128-CTR stretch of the ECDH secret with the label `"mattel"` |
| Record crypto | **AES-128-CTR** per packet; **CRC-8** header + body integrity |
| Application data | **Protocol Buffers** (car identity, speed/pass events, status heartbeat) |

**Important:** the portal authenticates *itself* to the app (anti-counterfeit),
but it does **not** authenticate the client. The app never sends a certificate —
only an ephemeral ECDH public key. So **no Mattel secret is required** to talk to
the portal; everything needed is in the factory token the portal hands out.

---

## BLE GATT layout

**Device name:** `HWiD`. **Negotiated MTU:** 247.

All custom services use the base UUID `af0a6ec7-XXXX-YYYY-84a0-91559fc6f0de`.
The portal is the **NXP** variant of the Mattel `blekit` SDK
(`MpidConfig.GetNXPConfig`); the SDK also defines NRF / Magic Bullet / Magic Wand
variants on other base UUIDs, none of which use a `…-000c` service.

### Service A — MPID comms `af0a6ec7-0001-000a-…`

| Characteristic | Properties | Role | Notes |
|----------------|------------|------|-------|
| `af0a6ec7-0002-000a-…` | write, indicate | **TX / RX** | Encrypted frames, both directions (write to send; indications to receive) |
| `af0a6ec7-0003-000a-…` | read | **FACTORY** | 136-byte signed manufacturing token |
| `af0a6ec7-0004-000a-…` | write, indicate | **SESSION** | Client writes its public key + salt here |

### Service B — OTA firmware update `af0a6ec7-0001-000b-…`

| Characteristic | Properties | Role |
|----------------|------------|------|
| `af0a6ec7-0002-000b-…` | write, indicate | OTA command |
| `af0a6ec7-0003-000b-…` | write-without-response | OTA data |

Plus the standard `1800`/`1801` GAP/GATT services. **There is no `…-000c`
service.**

---

## The factory token (FACTORY read, 136 bytes, protocol v1)

Read once from `…-0003-000a`. It identifies the portal and carries its public
key, signed by a Mattel manufacturing key.

| Offset | Len | Field |
|--------|-----|-------|
| 0 | 1 | Protocol version (`0x01`) |
| 1 | 24 | Serial (ASCII) — `day[3] year[1] location[2] AP#[10] revision[2] item#[6]` |
| 25 | 33 | **Device public key**, P-256 **compressed** (`0x02`/`0x03` ‖ X) |
| 58 | 5 | Birth time |
| 63 | 2 | Machine number (big-endian) |
| 65 | 3 | **Key ID** (big-endian) — selects the manufacturing key |
| 68 | 64 | ECDSA-P256 signature over bytes `[0:68]` |
| 132 | 4 | **Device salt** (peer salt) |

The app verifies the signature with an embedded manufacturing public key chosen
by Key ID. This is only the *app verifying the portal* — a client does not need
it to connect. Known Key IDs (64-byte uncompressed P-256 keys baked into the app):

| KID | Key | KID | Key |
|-----|-----|-----|-----|
| 9999999 | test (dev) | 5 | pp |
| 8888888 | test #2 | 6 | techmods |
| 1 | fep | 9 | media1 |
| 2 | nxp_text | 10 | pp2 |
| 3 | augmoto | 11 | smartconnect gmn58 |
| 4 | rocketleague | 12 | smartconnect gld09 |

> The portal tested here reports **KID 9999999** (the test/development key) and
> firmware version **`1.0.9`** (from the status heartbeat).

---

## Handshake

1. Connect; request MTU 247; enable indications on **TX/RX** and **SESSION**.
2. **Read FACTORY** → 136-byte token; parse the device compressed public key and
   the device salt.
3. Generate an ephemeral P-256 key pair and a random 4-byte **local salt**.
4. **ECDH**: `shared = ECDH(device_pub, our_priv)` → 32-byte X coordinate.
5. **Derive the session key** (see KDF below) → 16-byte AES key.
6. **Write SESSION** = `compressed_pubkey (33) ‖ local_salt (4)` = **37 bytes** to
   `…-0004-000a`. The portal now derives the same session key.
7. Exchange **encrypted packets** on TX/RX (`…-0002-000a`).

### Session key derivation (`mpid_encrypt_context`)

```
secret = ECDH_shared_X                       # 32 bytes
iv     = bytes(16); iv[9:15] = b"mattel"     # 00*9 'm''a''t''t''e''l' 00
for _ in range(100):
    secret = AES128_CTR(key=secret[:16], counter=iv, data=secret[:32])
    iv[4:8] = be32(be32(iv[4:8]) + 1)        # 32-bit big-endian counter at iv[4:8]
session_key = secret[:16]
```

AES-128-CTR here is the tiny-AES variant: a 16-byte counter block incremented as
a 128-bit big-endian integer (identical to `cryptography`'s CTR mode).

---

## Encrypted packet framing

Built by `mpid_make_packet_generic`; parsed/reassembled by `mpid_buffer_put`.

```
 +---------- 8-byte header ----------+ +------- body (length bytes) -------+
 | 7E | counter(BE32) | length(BE16) | crc8 | <payload …> | crc8(payload) |
 +----+---------------+--------------+------+-------------+----------------+
   0     1..4             5..6          7        8 …            8+len-1
```

- **preamble** `0x7E`
- **counter** — uint32 big-endian; incremented per transmitted packet (first sent = 1)
- **length** — uint16 big-endian = `len(payload) + 1` (or `0` for an empty packet)
- **header crc8** = `crc8(header[0:7])`
- **body** = `payload ‖ crc8(payload)` (so body length = `length`)

### Body encryption (once a session is established)

The body is encrypted in place with **AES-128-CTR** using the session key and a
16-byte IV built from the packet counter and the two salts:

```
iv = counter(BE32) ‖ saltA(4) ‖ saltB(4) ‖ 00 00 00 00
   TX (we send):     saltA = local_salt, saltB = peer_salt
   RX (we receive):  saltA = peer_salt,  saltB = local_salt
```

Both endpoints compute the same IV for a given packet because each side's
"local" salt is the other's "peer" salt.

### CRC-8

Polynomial **`0x07`**, init **`0xFF`**, MSB-first, **no** input/output reflection,
**no** final XOR. Table-driven: `crc = table[crc ^ byte]`.

### Receive / reassembly

Scan the indication byte stream for `0x7E`, collect the 8-byte header and validate
its CRC, read `length` body bytes, decrypt, then verify `crc8(body[:-1]) ==
body[-1]` and deliver `body[:-1]` as the application payload.

---

## Application layer — Protocol Buffers (`MCPP.HWiD`)

Each decrypted payload is a Protocol Buffers message. The **complete schema is
authoritative**, not inferred: it was recovered from the FileDescriptor the app
embeds in its Unity IL2CPP metadata (`global-metadata.dat`, via
`tools/decode_descriptor.py`) and is committed as [`HWiD.proto`](HWiD.proto). The
Python model is in [`hwportal/mpid.py`](hwportal/mpid.py) (`parse_message`).

Portal → app messages are `PortalToApp`; app → portal are `AppToPortal`. (There
are also `PortalToAccessory` / `AccessoryToPortal` for the accessory ecosystem.)

### `PortalToApp` (what the portal sends)

| Field | Type | Meaning |
|-------|------|---------|
| `1` | uint32 | `timestamp_ms` (≈ ms uptime) |
| `2` | `Event` | car / speed / gate / accessory event |
| `3` | `DeviceInfo` | status heartbeat (~every 7 s) |
| `4` | `CommandResponse` | ack to a command we sent |
| `5` | bytes | `accessory_message` |

### `Event` (field 2)

`type` (field 1) is an `EventType` enum:

| # | EventType | Notes |
|---|-----------|-------|
| 0 | UnknownEventType | |
| 1 | LowBatteryEvent | |
| 2 | CarOnPortalEvent | car placed — carries `car_info` |
| 3 | CarOffPortalEvent | car removed |
| 4 | CarDriveByEvent | pass — carries `speed_measurement` |
| 5 | CarHistory | carries `offline_race_sessions` (stored offline races) |
| 6 | AccessoryAttachedEvent | with `accessory_id` |
| 7 | AccessoryDetachedEvent | |
| 8 | AccessoryIdentifiedEvent | |
| 9–12 | InfraredGate{A,B}{Blocked,Unblocked} | raw beam-break of the two IR gates |

Event fields: `1 type`, `2 car_info` (`CarInfo`), `3 speed_measurement`
(`SpeedMeasurement`), `4 measurement_history` (repeated, **deprecated**),
`5 offline_race_sessions` (repeated `OfflineRaceSession`), `6 accessory_id`.

**`CarInfo`:** `1 tag_uid` (bytes; `0x04` + 6-byte NFC UID) · `2 signature_status`
(bool) · `3 car_ndef_data` (bytes; NDEF URI record) · `4 signature` (64 bytes) ·
`5 publickey`.

**`SpeedMeasurement`:** `1 timestamp_ms` · `2 speed` (float32, ×64 = scale mph) ·
`3 t_ir1_in` · `4 t_ir1_out` · `5 t_ir2_in` · `6 t_ir2_out` (int32 enter/exit
timestamps of the two IR gates — the raw timing the speed is derived from) ·
`7 estimated_car_count`.


**`OfflineRaceSession`:** `1 time_played` · `2 top_speed` (float32) · `3 scan_count`.

### `DeviceInfo` (field 3 — the heartbeat)

| # | Field | Notes |
|---|-------|-------|
| 1 | firmware_version (uint32) | **deprecated**; use `semantic_firmware_version` |
| 2 | hardware_version (uint32) | |
| 3 | battery_level (float) | 0.0–1.0 |
| 4 | mode (`DeviceMode`) | 0 Unknown · 1 Fast · 2 Normal · 3 Test |
| 5 | boot_timestamp_sec (uint32) | uptime |
| 6 | serial_number (string) | **NOTE: omitted by fw 1.0.9** — see below |
| 7 | battery_status (`BatteryStatus`) | 0 Unknown · 1 NotCharging · 2 Charging · 3 Full · 4 Problem |
| 8 | q_value (uint32) | battery fuel-gauge raw |
| 9 | i_value (uint32) | battery fuel-gauge raw |
| 10 | semantic_firmware_version (string) | e.g. `"1.0.9"` |
| 11 | accessory_attached (bool) | |

> **Serial caveat (verified):** firmware 1.0.9 does **not** include field 6 in its
> heartbeat (observed fields: 1,2,3,4,5,7,8,9,10). The portal serial is instead
> taken from the FACTORY token (the `1989os…` string); `portal.py` backfills
> `info.serial_number` from the token during the handshake.

### Payload formats (within the bytes fields above)

- **NFC UID:** `0x04` + 6 bytes → `AA:BB:CC:DD:EE:FF`.
- **NDEF URI record:** `91 01 28 55 02` + ASCII → `https://www.pid.mattel/<base64 car id>`.
  The base64 is the Mattel car ID.
- **Speed:** little-endian float32; multiply by **64** for "1:64 scale mph".

### Verified live examples

| Capture | Decodes to |
|---------|-----------|
| heartbeat | `DeviceInfo`: v`1.0.9`, battery `1.0` (NotCharging), mode Normal, hw `7` |
| 133-byte packet | `CarOnPortalEvent`: UID `2A:7E:A2:F1:62:80`, Mattel ID `AQBBrl5bAAAGAF0TKZcEKn6i8WKA`, 64-byte signature |
| 19-byte packet | `CarOffPortalEvent` (car removed) |
| 53-byte packet | `CarDriveByEvent`: speed `0.595` → `38.08` scale-mph, gates ir1 `[-26240, 87376]` ir2 `[165344, 258944]` |

---

## Crypto primitives (from the native lib)

All built from public, open-source code — only the composition was proprietary:

- **micro-ecc (`uECC`)** — secp256r1 (P-256) ECDH + ECDSA, compressed-point decompress
- **tiny-AES-c** — AES-128 (CTR used for the session and records)
- **SHA-256 + HMAC-SHA256** — used in token verification
- **CRC-8** (poly `0x07`)

---

## Reproducing / tooling

Live tools:

- `python mpid_monitor.py` — handshake against the portal and print decoded events.
- `python portal_app.py` / `python dashboard.py` / `python race_mode.py` — go through
  `HotWheelsPortal`, which auto-detects the MPID transport and emits the same event
  stream as the legacy path.
