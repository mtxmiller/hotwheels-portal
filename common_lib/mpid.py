"""
The current actual hotwheels protocol implementation
"""

import base64
import os
import struct
from dataclasses import dataclass, field
from enum import IntEnum

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .constants import CHAR_EVENT_1, CHAR_EVENT_2, CHAR_EVENT_3

PORTAL_NAME = "HWiD"

# MPID GATT characteristics (NXP config from MpidConfig.GetNXPConfig)
CHAR_TXRX = "af0a6ec7-0002-000a-84a0-91559fc6f0de"
CHAR_FACTORY = "af0a6ec7-0003-000a-84a0-91559fc6f0de"
CHAR_SESSION = "af0a6ec7-0004-000a-84a0-91559fc6f0de"

PREAMBLE = 0x7E
KDF_ROUNDS = 100
KDF_LABEL = b"mattel"


# ---------------------------------------------------------------------------
# CRC-8 (poly 0x07, init 0xFF, MSB-first) -- matches crc8_calc / crc8_table
# ---------------------------------------------------------------------------
def _build_crc8_table(poly: int) -> list[int]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
        table.append(c)
    return table


_CRC8_TABLE = _build_crc8_table(0x07)


def crc8(data: bytes, crc: int = 0xFF) -> int:
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc


# ---------------------------------------------------------------------------
# AES-128-CTR primitive (tiny-AES semantics: full 16-byte counter block,
# 128-bit big-endian increment -- which is exactly what cryptography's CTR does)
# ---------------------------------------------------------------------------
def aes128_ctr(key16: bytes, iv16: bytes, data: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key16), modes.CTR(iv16)).encryptor()
    return enc.update(data) + enc.finalize()


class MpidTokenError(ValueError):
    pass


class MpidToken:
    LENGTH = 136

    def __init__(self, raw: bytes):
        if len(raw) < self.LENGTH:
            raise MpidTokenError(f"token too short: {len(raw)} (< {self.LENGTH})")
        self.raw = bytes(raw[: self.LENGTH])
        if self.raw[0] != 1:
            raise MpidTokenError(f"unsupported protocol version {self.raw[0]}")
        self.serial = self.raw[1:25]
        self.compressed_public_key = self.raw[25:58]   # 33 bytes, 0x02/0x03 || X
        self.birth_time = self.raw[58:63]
        self.machine = struct.unpack(">H", self.raw[63:65])[0]
        self.key_id = int.from_bytes(self.raw[65:68], "big")
        self.signature = self.raw[68:132]
        self.salt = self.raw[132:136]                  # device (peer) salt

    def __repr__(self):
        return (f"MpidToken(serial={self.serial.decode('latin1')!r}, "
                f"kid={self.key_id}, machine={self.machine}, salt={self.salt.hex()})")


class MpidSession:
    def __init__(self, private_key: ec.EllipticCurvePrivateKey | None = None,
                 local_salt: bytes | None = None):
        self._priv = private_key or ec.generate_private_key(ec.SECP256R1())
        self.local_salt = local_salt or os.urandom(4)
        if len(self.local_salt) != 4:
            raise ValueError("local_salt must be 4 bytes")
        self.session_key: bytes | None = None
        self.peer_salt: bytes | None = None
        self.encrypted = False
        self._tx_counter = 0
        # rx reassembly state
        self._buf = bytearray()
        self._state = "READY"
        self._plen = 0

    @property
    def compressed_public_key(self) -> bytes:
        return self._priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)

    # -- handshake ----------------------------------------------------------
    def start_session(self, factory_token: bytes) -> bytes:
        token = MpidToken(factory_token)
        self.peer_salt = token.salt

        device_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), token.compressed_public_key)
        shared = self._priv.exchange(ec.ECDH(), device_pub)   # 32-byte X coord

        self.session_key = self._derive_key(shared)
        self.encrypted = True
        self._tx_counter = 0
        self.token = token
        return self.compressed_public_key + self.local_salt   # 33 + 4 = 37 bytes

    @staticmethod
    def _derive_key(shared: bytes) -> bytes:
        secret = bytearray(shared[:32])
        iv = bytearray(16)
        iv[9:15] = KDF_LABEL                       # iv = 00*9 'mattel' 00
        for _ in range(KDF_ROUNDS):
            secret = bytearray(aes128_ctr(bytes(secret[:16]), bytes(iv), bytes(secret)))
            ctr = (int.from_bytes(iv[4:8], "big") + 1) & 0xFFFFFFFF   # BE32 at iv[4:8]
            iv[4:8] = ctr.to_bytes(4, "big")
        return bytes(secret[:16])

    # -- framing ------------------------------------------------------------
    def _make_iv(self, counter: int, salt_a: bytes, salt_b: bytes) -> bytes:
        return struct.pack(">I", counter) + salt_a + salt_b + b"\x00\x00\x00\x00"

    def encrypt_packet(self, payload: bytes) -> bytes:
        if len(payload) > 0x1FF:
            raise ValueError("payload too long (max 511)")
        self._tx_counter = (self._tx_counter + 1) & 0xFFFFFFFF
        counter = self._tx_counter
        plen = (len(payload) + 1) if payload else 0

        header = bytearray(8)
        header[0] = PREAMBLE
        struct.pack_into(">I", header, 1, counter)
        struct.pack_into(">H", header, 5, plen)
        header[7] = crc8(header[:7])

        if not payload:
            return bytes(header)

        body = bytearray(payload) + bytes([crc8(payload)])
        if self.encrypted:
            iv = self._make_iv(counter, self.local_salt, self.peer_salt)  # TX: local, peer
            body = bytearray(aes128_ctr(self.session_key, iv, bytes(body)))
        return bytes(header) + bytes(body)

    def feed(self, data: bytes) -> list[bytes]:
        out = []
        for b in data:
            payload = self._feed_byte(b)
            if payload is not None:
                out.append(payload)
        return out

    def _reset_rx(self):
        self._buf.clear()
        self._state = "READY"
        self._plen = 0

    def _feed_byte(self, b: int):
        if self._state == "READY":
            if b == PREAMBLE:
                self._buf = bytearray([b])
                self._state = "GOT_PREAMBLE"
            return None

        self._buf.append(b)

        if self._state == "GOT_PREAMBLE":
            if len(self._buf) >= 8:
                if crc8(self._buf[:7]) != self._buf[7]:
                    self._reset_rx()                       # bad header -> resync
                    return None
                self._plen = struct.unpack_from(">H", self._buf, 5)[0]
                if self._plen == 0:
                    self._reset_rx()
                    return b""                              # empty packet
                self._state = "GOT_HEADER"
            return None

        if self._state == "GOT_HEADER":
            if len(self._buf) >= self._plen + 8:
                body = bytearray(self._buf[8:8 + self._plen])
                counter = struct.unpack_from(">I", self._buf, 1)[0]
                if self.encrypted:
                    iv = self._make_iv(counter, self.peer_salt, self.local_salt)  # RX: peer, local
                    body = bytearray(aes128_ctr(self.session_key, iv, bytes(body)))
                self._reset_rx()
                if crc8(body[:-1]) != body[-1]:
                    return None                             # bad body crc -> drop
                return bytes(body[:-1])
            return None

        self._reset_rx()
        return None


# ---------------------------------------------------------------------------
# Application-payload decoders (shared by all transports / apps -- single
# source of truth, previously duplicated across the app scripts)
# ---------------------------------------------------------------------------
SPEED_SCALE = 64  # raw float32 -> "1:64 scale mph"

# Empirically calibrated gate-speed constant.  The portal derives a pass speed
# from the two IR gates' *leading-edge* (beam-break) timestamps:
#
#     raw_speed = GATE_SPEED_CONSTANT / (t_ir2_in - t_ir1_in)
#
# The constant was recovered by solving the portal's own reported
# SpeedMeasurement.speed against its t_ir1_in / t_ir2_in across captured passes
# -- two independent drive-bys agree to <0.01% (0.595039*191584 = 113999.9 and
# 0.4063*280562 = 113992.3).  It folds the physical gate separation and the
# firmware tick period into a single factor, so the result is in the same "raw
# speed" units as SpeedMeasurement.speed (multiply by SPEED_SCALE for 1:64
# scale mph).  Trailing edges (t_*_out) do NOT fit the same constant, which is
# consistent with cars accelerating between the gates.
#
# This lets us compute a speed for *non-chipped* cars: the portal can't emit a
# tag-bearing CarDriveByEvent for them, but if we can observe the two gate
# beam-break timestamps (raw IR-gate events, or a tag-less SpeedMeasurement),
# the same formula applies.
GATE_SPEED_CONSTANT = 114000.0


def speed_from_gates(t_ir1_in: int, t_ir2_in: int) -> float | None:
    dt = t_ir2_in - t_ir1_in
    if dt == 0:
        return None
    return GATE_SPEED_CONSTANT / dt


_URI_PREFIXES = {
    0x00: "", 0x01: "http://www.", 0x02: "https://www.",
    0x03: "http://", 0x04: "https://",
}


def format_uid(data: bytes) -> str:
    uid = data[1:7] if len(data) >= 7 else data
    return ":".join(f"{b:02X}" for b in uid)


def decode_speed(data: bytes) -> float | None:
    """Raw little-endian float32 speed from a 4+ byte payload (None if too short)."""
    if len(data) < 4:
        return None
    return struct.unpack("<f", data[:4])[0]


def decode_speed_mph(data: bytes) -> float | None:
    """Speed scaled to '1:64 scale mph' (raw float32 * 64)."""
    raw = decode_speed(data)
    return None if raw is None else raw * SPEED_SCALE


def decode_car_event(data: bytes) -> dict:
    """Decode a car-detection payload (0x04 + 6-byte NFC UID)."""
    if len(data) < 7:
        return {"raw": data.hex()}
    return {
        "event_type": data[0],
        "nfc_uid": format_uid(data),
        "type_name": "Car Detected" if data[0] == 0x04 else f"Unknown (0x{data[0]:02x})",
    }


def decode_speed_event(data: bytes) -> dict:
    """Decode a speed/timing payload (IEEE-754 float32, little-endian)."""
    raw = decode_speed(data)
    if raw is None:
        return {"raw": data.hex()}
    return {"raw_float": raw, "scaled_mph": raw * SPEED_SCALE}


def decode_ndef_record(data: bytes) -> dict:

    if len(data) < 10:
        return {"raw": data.hex()} if data else {"empty": True}

    type_len = data[1]
    payload_len = data[2]
    record_type = data[3:3 + type_len]
    result: dict = {}

    if record_type == b"U":
        prefix = _URI_PREFIXES.get(data[4], "")
        uri_content = data[5:4 + payload_len].decode("utf-8", errors="replace")
        full_uri = prefix + uri_content
        result["uri"] = full_uri
        if "pid.mattel/" in full_uri:
            mattel_id = full_uri.split("pid.mattel/", 1)[1]
            result["mattel_id"] = mattel_id
            try:
                result["mattel_id_decoded"] = base64.urlsafe_b64decode(mattel_id + "==").hex()
            except Exception:
                pass

    ndef_end = 4 + payload_len
    if len(data) > ndef_end:
        sig = data[ndef_end:]
        result["signature"] = sig.hex()
        result["signature_len"] = len(sig)
    return result


# ---------------------------------------------------------------------------
# Protobuf (the decrypted MPID application layer) -> legacy channel events
# ---------------------------------------------------------------------------
def _pb_varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _pb_fields(data: bytes) -> dict:

    out: dict = {}
    i, n = 0, len(data)
    try:
        while i < n:
            tag, i = _pb_varint(data, i)
            field, wire = tag >> 3, tag & 7
            if wire == 0:
                v, i = _pb_varint(data, i)
            elif wire == 2:
                ln, i = _pb_varint(data, i)
                v = data[i:i + ln]
                i += ln
            elif wire == 5:
                v = data[i:i + 4]
                i += 4
            elif wire == 1:
                v = data[i:i + 8]
                i += 8
            else:
                break
            out.setdefault(field, []).append(v)
    except IndexError:
        pass
    return out


def _pb_first(fields: dict, num: int):
    vals = fields.get(num)
    return vals[0] if vals else None


def parse_payload(payload: bytes) -> dict:

    msg = parse_message(payload)
    version = msg.info.semantic_firmware_version if (msg.info and msg.info.semantic_firmware_version) else None
    return {"events": to_legacy_events(msg), "version": version}


# ---------------------------------------------------------------------------
# Structured application model (MCPP.HWiD protobuf -- see HWiD.proto)
# ---------------------------------------------------------------------------
class EventType(IntEnum):
    UNKNOWN = 0
    LOW_BATTERY = 1
    CAR_ON_PORTAL = 2
    CAR_OFF_PORTAL = 3
    CAR_DRIVE_BY = 4
    CAR_HISTORY = 5
    ACCESSORY_ATTACHED = 6
    ACCESSORY_DETACHED = 7
    ACCESSORY_IDENTIFIED = 8
    IR_GATE_A_BLOCKED = 9
    IR_GATE_B_BLOCKED = 10
    IR_GATE_A_UNBLOCKED = 11
    IR_GATE_B_UNBLOCKED = 12


class DeviceMode(IntEnum):
    UNKNOWN = 0
    FAST = 1
    NORMAL = 2
    TEST = 3


class BatteryStatus(IntEnum):
    UNKNOWN = 0
    NOT_CHARGING = 1
    CHARGING = 2
    FULL = 3
    PROBLEM = 4


def _enum(cls, value):
    try:
        return cls(value)
    except ValueError:
        return cls(0)


def _f32(b) -> float:
    return struct.unpack("<f", b)[0] if isinstance(b, (bytes, bytearray)) and len(b) == 4 else 0.0


def _s32(v) -> int:
    """Interpret a protobuf int32 (varint, possibly 64-bit sign-extended) as signed."""
    if not isinstance(v, int):
        return 0
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _txt(b) -> str:
    return b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else ""


def _bytes(b) -> bytes:
    return bytes(b) if isinstance(b, (bytes, bytearray)) else b""


@dataclass
class CarInfo:
    tag_uid: bytes = b""              # 0x04 + 6-byte NFC UID
    signature_status: bool = False
    car_ndef_data: bytes = b""
    signature: bytes = b""
    publickey: bytes = b""

    @property
    def uid(self) -> str:
        return format_uid(self.tag_uid)

    @property
    def mattel_id(self):
        return decode_ndef_record(self.car_ndef_data).get("mattel_id") if self.car_ndef_data else None


@dataclass
class SpeedMeasurement:
    timestamp_ms: int = 0
    speed: float = 0.0               # raw float; * SPEED_SCALE for "scale mph"
    t_ir1_in: int = 0
    t_ir1_out: int = 0
    t_ir2_in: int = 0
    t_ir2_out: int = 0
    estimated_car_count: int = 0

    @property
    def speed_mph(self) -> float:
        return self.speed * SPEED_SCALE

    @property
    def reconstructed_speed(self) -> float | None:
        return speed_from_gates(self.t_ir1_in, self.t_ir2_in)


@dataclass
class OfflineRaceSession:
    time_played: int = 0
    top_speed: float = 0.0
    scan_count: int = 0


@dataclass
class DeviceInfo:
    firmware_version: int = 0
    hardware_version: int = 0
    battery_level: float = 0.0
    mode: DeviceMode = DeviceMode.UNKNOWN
    boot_timestamp_sec: int = 0
    serial_number: str = ""
    battery_status: BatteryStatus = BatteryStatus.UNKNOWN
    q_value: int = 0
    i_value: int = 0
    semantic_firmware_version: str = ""
    accessory_attached: bool = False


@dataclass
class Event:
    type: EventType = EventType.UNKNOWN
    car_info: "CarInfo | None" = None
    speed_measurement: "SpeedMeasurement | None" = None
    measurement_history: list = field(default_factory=list)
    offline_race_sessions: list = field(default_factory=list)
    accessory_id: int = 0


@dataclass
class CommandResponse:
    failed: bool = False
    fail_message: str = ""


@dataclass
class PortalMessage:                  # = MCPP.HWiD.PortalToApp
    timestamp_ms: int = 0
    event: "Event | None" = None
    info: "DeviceInfo | None" = None
    cmd_response: "CommandResponse | None" = None
    raw: bytes = b""


def _parse_car_info(b) -> CarInfo:
    f = _pb_fields(b)
    return CarInfo(
        tag_uid=_bytes(_pb_first(f, 1)),
        signature_status=bool(_pb_first(f, 2) or 0),
        car_ndef_data=_bytes(_pb_first(f, 3)),
        signature=_bytes(_pb_first(f, 4)),
        publickey=_bytes(_pb_first(f, 5)),
    )


def _parse_speed(b) -> SpeedMeasurement:
    f = _pb_fields(b)
    return SpeedMeasurement(
        timestamp_ms=_pb_first(f, 1) or 0,
        speed=_f32(_pb_first(f, 2)),
        t_ir1_in=_s32(_pb_first(f, 3) or 0),
        t_ir1_out=_s32(_pb_first(f, 4) or 0),
        t_ir2_in=_s32(_pb_first(f, 5) or 0),
        t_ir2_out=_s32(_pb_first(f, 6) or 0),
        estimated_car_count=_pb_first(f, 7) or 0,
    )


def _parse_offline(b) -> OfflineRaceSession:
    f = _pb_fields(b)
    return OfflineRaceSession(
        time_played=_pb_first(f, 1) or 0,
        top_speed=_f32(_pb_first(f, 2)),
        scan_count=_pb_first(f, 3) or 0,
    )


def _parse_event(b) -> Event:
    f = _pb_fields(b)
    return Event(
        type=_enum(EventType, _pb_first(f, 1) or 0),
        car_info=_parse_car_info(_pb_first(f, 2)) if 2 in f else None,
        speed_measurement=_parse_speed(_pb_first(f, 3)) if 3 in f else None,
        measurement_history=[_parse_speed(x) for x in f.get(4, [])],
        offline_race_sessions=[_parse_offline(x) for x in f.get(5, [])],
        accessory_id=_pb_first(f, 6) or 0,
    )


def _parse_device_info(b) -> DeviceInfo:
    f = _pb_fields(b)
    return DeviceInfo(
        firmware_version=_pb_first(f, 1) or 0,
        hardware_version=_pb_first(f, 2) or 0,
        battery_level=_f32(_pb_first(f, 3)),
        mode=_enum(DeviceMode, _pb_first(f, 4) or 0),
        boot_timestamp_sec=_pb_first(f, 5) or 0,
        serial_number=_txt(_pb_first(f, 6)),
        battery_status=_enum(BatteryStatus, _pb_first(f, 7) or 0),
        q_value=_pb_first(f, 8) or 0,
        i_value=_pb_first(f, 9) or 0,
        semantic_firmware_version=_txt(_pb_first(f, 10)),
        accessory_attached=bool(_pb_first(f, 11) or 0),
    )


def _parse_cmd_response(b) -> CommandResponse:
    f = _pb_fields(b)
    return CommandResponse(failed=bool(_pb_first(f, 1) or 0), fail_message=_txt(_pb_first(f, 2)))


def parse_message(payload: bytes) -> PortalMessage:
    f = _pb_fields(payload)
    return PortalMessage(
        timestamp_ms=_pb_first(f, 1) or 0,
        event=_parse_event(_pb_first(f, 2)) if 2 in f else None,
        info=_parse_device_info(_pb_first(f, 3)) if 3 in f else None,
        cmd_response=_parse_cmd_response(_pb_first(f, 4)) if 4 in f else None,
        raw=bytes(payload),
    )


def to_legacy_events(msg: "PortalMessage") -> list:
    events = []
    ev = msg.event
    if ev:
        if ev.type == EventType.CAR_OFF_PORTAL:
            events.append((CHAR_EVENT_2, b""))
        elif ev.car_info and len(ev.car_info.tag_uid) >= 7:
            events.append((CHAR_EVENT_2, ev.car_info.tag_uid))
            if len(ev.car_info.car_ndef_data) > 4:
                events.append((CHAR_EVENT_1, ev.car_info.car_ndef_data))
        if ev.speed_measurement:
            events.append((CHAR_EVENT_3, struct.pack("<f", ev.speed_measurement.speed)))
    return events


# ---------------------------------------------------------------------------
# Protobuf encoder + AppToPortal command builders (app -> portal)
# ---------------------------------------------------------------------------
class CommandType(IntEnum):
    UNKNOWN = 0
    FAST_MODE = 1
    NORMAL_MODE = 2
    REQUEST_DEVICE_INFO = 3
    TEST_MODE = 4
    RESET = 5
    START_OTA = 6
    SET_LED_COLOR = 7
    RESET_LED_CONTROL = 8
    CLEAR_BONDING = 9


def _enc_uvarint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _enc_varint(field_num: int, value: int) -> bytes:
    return _enc_uvarint((field_num << 3) | 0) + _enc_uvarint(value)


def _enc_bytes(field_num: int, value: bytes) -> bytes:
    return _enc_uvarint((field_num << 3) | 2) + _enc_uvarint(len(value)) + bytes(value)


def build_command(cmd_type: "CommandType", rgb_color: "bytes | None" = None,
                  ota_signature: "bytes | None" = None,
                  ota_publickey: "bytes | None" = None) -> bytes:
    cmd = _enc_varint(1, int(cmd_type))
    if ota_signature:
        cmd += _enc_bytes(2, ota_signature)
    if ota_publickey:
        cmd += _enc_bytes(3, ota_publickey)
    if rgb_color is not None:
        cmd += _enc_bytes(4, rgb_color)
    return _enc_bytes(2, cmd)            # AppToPortal.command = field 2


def cmd_request_device_info() -> bytes:
    return build_command(CommandType.REQUEST_DEVICE_INFO)


def cmd_set_led_color(r: int, g: int, b: int) -> bytes:
    return build_command(CommandType.SET_LED_COLOR, rgb_color=bytes([r & 0xFF, g & 0xFF, b & 0xFF]))


def cmd_reset_led() -> bytes:
    return build_command(CommandType.RESET_LED_CONTROL)


def cmd_set_mode(mode: "DeviceMode") -> bytes:
    mapping = {
        DeviceMode.FAST: CommandType.FAST_MODE,
        DeviceMode.NORMAL: CommandType.NORMAL_MODE,
        DeviceMode.TEST: CommandType.TEST_MODE,
    }
    return build_command(mapping.get(mode, CommandType.NORMAL_MODE))


def cmd_reset() -> bytes:
    return build_command(CommandType.RESET)


def cmd_clear_bonding() -> bytes:
    return build_command(CommandType.CLEAR_BONDING)
