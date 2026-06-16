#!/usr/bin/env python3
"""
MPID live monitor: performs the reverse-engineered handshake against the
Hot Wheels id portal and prints decoded application events.

Flow (mirrors MpidPeripheral.initialize):
    1. connect, subscribe (indicate) to TX/RX (0002-000a) and SESSION (0004-000a)
    2. read FACTORY (0003-000a) -> 136-byte token
    3. derive session key, write our pubkey+salt to SESSION (0004-000a)
    4. decrypt + decode everything arriving on TX/RX

Usage:
    python mpid_monitor.py                # scan for HWiD and connect
    python mpid_monitor.py <ADDRESS>      # connect to a specific BLE address
    python mpid_monitor.py --raw          # also dump encrypted frames, token, key
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime

from bleak import BleakScanner, BleakClient

from common_lib.mpid import (
    MpidSession, parse_message, EventType, SPEED_SCALE,
    PORTAL_NAME, CHAR_TXRX, CHAR_FACTORY, CHAR_SESSION,
    DeviceMode, cmd_set_mode, cmd_request_device_info, _pb_fields,
)

_MODES = {"fast": DeviceMode.FAST, "normal": DeviceMode.NORMAL, "test": DeviceMode.TEST}

_GATE_EVENTS = {
    EventType.IR_GATE_A_BLOCKED, EventType.IR_GATE_B_BLOCKED,
    EventType.IR_GATE_A_UNBLOCKED, EventType.IR_GATE_B_UNBLOCKED,
}
_ACCESSORY_EVENTS = {
    EventType.ACCESSORY_ATTACHED, EventType.ACCESSORY_DETACHED,
    EventType.ACCESSORY_IDENTIFIED,
}


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class MpidMonitor:
    def __init__(self, show_raw: bool = False, dump: bool = False,
                 mode: str | None = None, keepalive: float | None = None,
                 reconnect: bool = False):
        self.session = MpidSession()
        self.show_raw = show_raw
        self.dump = dump                 # full payload + protobuf field tree per msg
        self.mode = mode                 # 'fast' | 'normal' | 'test' to request
        self.keepalive = keepalive       # seconds between device-info pings (or None)
        self.reconnect = reconnect       # auto-reconnect after a disconnect

    def _on_txrx(self, _char, data: bytearray):
        if self.show_raw:
            print(f"[{ts()}] RX raw   : {data.hex()}")
        for payload in self.session.feed(bytes(data)):
            self._decode(payload)

    async def _send_cmd(self, client, payload: bytes, label: str = "command") -> bool:
        """Encrypt `payload` and write it to TX/RX, matching the write type the
        characteristic actually supports.

        Windows/WinRT cancels a write-with-response on a characteristic that only
        offers write-without-response (and vice versa), so we prefer the type the
        GATT properties advertise and fall back to the other. The frame is built
        once so a retry reuses the same packet counter. Non-fatal: returns False
        and prints a warning instead of raising, so monitoring continues."""
        frame = self.session.encrypt_packet(payload)
        char = client.services.get_characteristic(CHAR_TXRX)
        props = list(char.properties) if char else []
        # Prefer write-without-response when offered; only force response when sole option.
        prefer_response = ("write" in props) and ("write-without-response" not in props)
        last = None
        for response in (prefer_response, not prefer_response):
            try:
                await client.write_gatt_char(CHAR_TXRX, frame, response=response)
                return True
            except Exception as e:                       # try the other write type
                last = e
        print(f"  ! {label} write failed (TX/RX props={props or '?'}): {last}")
        return False

    def _decode(self, payload: bytes):
        msg = parse_message(payload)
        printed = False

        info = msg.info
        if info is not None:
            print(f"[{ts()}] STATUS    v{info.semantic_firmware_version or '?'} "
                  f"battery={info.battery_level:.2f} ({info.battery_status.name}) "
                  f"mode={info.mode.name} hw={info.hardware_version} "
                  f"accessory={info.accessory_attached}")
            printed = True

        ev = msg.event
        if ev is not None:
            ci = ev.car_info
            uid = ci.uid if (ci and ci.tag_uid) else "?"
            t = ev.type
            if t == EventType.CAR_ON_PORTAL:
                print(f"[{ts()}] CAR ON    uid={uid} mattel_id={(ci.mattel_id if ci else None) or '?'}")
            elif t == EventType.CAR_OFF_PORTAL:
                print(f"[{ts()}] CAR OFF   uid={uid}")
            elif t == EventType.CAR_DRIVE_BY:
                sm = ev.speed_measurement
                if sm:
                    recon = sm.reconstructed_speed
                    recon_s = (f" [gate-calc {recon * SPEED_SCALE:.1f}]"
                               if recon is not None else "")
                    print(f"[{ts()}] DRIVE BY  uid={uid} {sm.speed_mph:.1f} scale-mph "
                          f"(raw {sm.speed:.4f}){recon_s} ir1[{sm.t_ir1_in},{sm.t_ir1_out}] "
                          f"ir2[{sm.t_ir2_in},{sm.t_ir2_out}] est_cars={sm.estimated_car_count}")
                else:
                    print(f"[{ts()}] DRIVE BY  uid={uid}")
            elif t == EventType.CAR_HISTORY:
                for s in ev.offline_race_sessions:
                    print(f"[{ts()}] HISTORY   time_played={s.time_played} "
                          f"top_speed={s.top_speed * SPEED_SCALE:.1f} scan_count={s.scan_count}")
            elif t in _GATE_EVENTS:
                # Raw beam-break events -- never seen on NORMAL-mode firmware, so
                # always surface the full payload + portal timestamp to learn
                # whether they carry usable per-gate timing.
                print(f"[{ts()}] IR GATE   {t.name}  t_ms={msg.timestamp_ms}")
                self._dump_payload(payload)
            elif t == EventType.LOW_BATTERY:
                print(f"[{ts()}] LOW BATTERY")
            elif t in _ACCESSORY_EVENTS:
                print(f"[{ts()}] ACCESSORY {t.name} id={ev.accessory_id}")
            else:
                # Unknown/unhandled event type -- dump it so we can characterize it.
                print(f"[{ts()}] EVENT     {t.name} (#{int(t)})  t_ms={msg.timestamp_ms}")
                self._dump_payload(payload)
            printed = True

        if msg.cmd_response is not None:
            cr = msg.cmd_response
            print(f"[{ts()}] CMD RSP   failed={cr.failed} msg={cr.fail_message!r}")
            printed = True

        if not printed or self.show_raw:
            print(f"[{ts()}] payload   ({len(payload)}B): {payload.hex()}")
        if self.dump:
            self._dump_payload(payload)

    def _dump_payload(self, payload: bytes):
        """Print the raw payload and a one-level protobuf field tree, so new or
        unhandled messages (e.g. raw IR-gate events) can be reverse-engineered."""
        print(f"           payload ({len(payload)}B): {payload.hex()}")
        for fnum, vals in sorted(_pb_fields(payload).items()):
            for v in vals:
                if isinstance(v, (bytes, bytearray)):
                    sub = _pb_fields(v)
                    extra = f"  sub={ {k: len(x) for k, x in sub.items()} }" if sub else ""
                    print(f"             #{fnum} len={len(v)} {bytes(v).hex()}{extra}")
                else:
                    print(f"             #{fnum} varint={v}")

    def _on_session(self, _char, data: bytearray):
        if self.show_raw:
            print(f"[{ts()}] SESSION  : {data.hex()}")

    async def find_portal(self) -> str | None:
        print("Scanning for Hot Wheels Portal...")
        devices = await BleakScanner.discover(timeout=15.0)
        for d in devices:
            if d.name and PORTAL_NAME.lower() in d.name.lower():
                print(f"Found portal: {d.name} ({d.address})")
                return d.address
        print(f"Scanned {len(devices)} devices; portal not found.")
        return None

    async def run(self, address: str | None):
        if address is None:
            address = await self.find_portal()
            if address is None:
                return

        attempt = 0
        while True:
            attempt += 1
            try:
                await self._session_once(address)
            except KeyboardInterrupt:
                print("\nStopping.")
                return
            except Exception as e:                        # noqa: BLE-E722 (debug tool)
                print(f"\nConnection error: {e}")
            if not self.reconnect:
                return
            print(f"-- reconnecting (attempt {attempt + 1})... Ctrl+C to stop --")
            try:
                await asyncio.sleep(1.5)
            except KeyboardInterrupt:
                print("\nStopping.")
                return

    async def _session_once(self, address: str):
        # Fresh ECDH session per connection (the portal expects a new handshake).
        self.session = MpidSession()
        print(f"\nConnecting to {address}...")
        async with BleakClient(address) as client:
            print(f"Connected: {client.is_connected}  (MTU {client.mtu_size})")

            await client.start_notify(CHAR_TXRX, self._on_txrx)
            await client.start_notify(CHAR_SESSION, self._on_session)
            print("Subscribed to TX/RX and SESSION.")

            token = bytes(await client.read_gatt_char(CHAR_FACTORY))
            session_payload = self.session.start_session(token)
            print(f"FACTORY token: {len(token)} bytes;  session derived "
                  f"({len(self.session.session_key)}-byte key).")
            if self.show_raw:
                # device-identifying / ephemeral material -- only with --raw
                print(f"  token   : {token.hex()}")
                print(f"  parsed  : {self.session.token}")
                print(f"  key     : {self.session.session_key.hex()}")
                print(f"  SESSION : {session_payload.hex()}")

            await client.write_gatt_char(CHAR_SESSION, session_payload, response=True)

            txrx = client.services.get_characteristic(CHAR_TXRX)
            print(f"TX/RX properties: {list(txrx.properties) if txrx else '?'}")

            if self.mode:
                target = _MODES[self.mode]
                await asyncio.sleep(0.3)                  # let the session settle
                if await self._send_cmd(client, cmd_set_mode(target), f"set {target.name} mode"):
                    # nudge a fresh heartbeat so we can confirm the new mode
                    await self._send_cmd(client, cmd_request_device_info(), "request device info")
                    print(f"Requested {target.name} mode.")

            print("Session established. Listening for events "
                  "(place/run a car). Ctrl+C to stop.\n")

            next_ka = time.monotonic() + (self.keepalive or 0)
            while client.is_connected:
                await asyncio.sleep(0.2)
                if self.keepalive and time.monotonic() >= next_ka:
                    next_ka = time.monotonic() + self.keepalive
                    await self._send_cmd(client, cmd_request_device_info(), "keepalive")
            print("\nPortal disconnected (it may have powered off).")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address", nargs="?", default=None)
    ap.add_argument("--raw", action="store_true",
                    help="also dump encrypted frames, raw payloads, token, and key")
    ap.add_argument("--dump", action="store_true",
                    help="dump raw payload + protobuf field tree for every message")
    ap.add_argument("--mode", choices=list(_MODES),
                    help="request a portal mode after connecting "
                         "(test/fast may expose raw IR-gate events for non-chipped cars)")
    ap.add_argument("--keepalive", type=float, metavar="SECONDS",
                    help="ping device-info every SECONDS (may prevent an idle power-off)")
    ap.add_argument("--reconnect", action="store_true",
                    help="auto-reconnect (and re-assert --mode) after a disconnect; "
                         "useful for probing TEST mode, which drops the link quickly")
    args = ap.parse_args()
    await MpidMonitor(show_raw=args.raw, dump=args.dump, mode=args.mode,
                      keepalive=args.keepalive, reconnect=args.reconnect).run(args.address)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
