"""Bluetooth LE control for lights without Wi-Fi (or with LAN control off).

Govee lights take 20 byte packets on a single write characteristic:

    33 CMD PAYLOAD... 00 00 ... XOR

The last byte is the XOR of the first 19. Known commands:

* ``33 01 01|00``           power on / off
* ``33 04 VALUE``           brightness (0-255 on most models)
* ``33 05 02 R G B``        colour, older strips
* ``33 05 0D R G B``        colour, most models from 2020 onwards
* ``33 05 15 01 R G B ...``  colour for all segments, some RGBIC strips
* ``AA 01``                 keep-alive, the light drops idle links

The actual Bluetooth part uses `bleak` and is optional: if it is not
installed everything else keeps working.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Sequence
from concurrent.futures import Future

from goveehome.colors import RGB, clamp

log = logging.getLogger(__name__)

WRITE_CHARACTERISTIC = "00010203-0405-0607-0809-0a0b0c0d2b11"
NAME_PREFIXES = ("ihoment_", "Govee_", "GBK_", "Minger_", "GVH")
PACKET_SIZE = 20


def build_packet(head: int, cmd: int, payload: Sequence[int] = ()) -> bytes:
    body = [head, cmd, *payload]
    if len(body) > PACKET_SIZE - 1:
        raise ValueError("payload too long")
    body.extend([0] * (PACKET_SIZE - 1 - len(body)))
    xor = 0
    for byte in body:
        xor ^= byte
    return bytes(body + [xor])


def power_packet(on: bool) -> bytes:
    return build_packet(0x33, 0x01, [0x01 if on else 0x00])


def brightness_packet(percent: int) -> bytes:
    return build_packet(0x33, 0x04, [clamp(percent * 255 / 100, 0, 255)])


def color_packet(rgb: RGB, mode: int = 0x02) -> bytes:
    r, g, b = (clamp(c) for c in rgb)
    if mode == 0x15:
        # segmented RGBIC models: colour applied to every segment in the mask
        return build_packet(0x33, 0x05, [0x15, 0x01, r, g, b, 0, 0, 0, 0, 0, 0xFF, 0x7F])
    return build_packet(0x33, 0x05, [mode, r, g, b])


def keepalive_packet() -> bytes:
    return build_packet(0xAA, 0x01)


def looks_like_govee(name: str | None) -> bool:
    return bool(name) and name.startswith(NAME_PREFIXES)


def sku_from_name(name: str) -> str:
    # "ihoment_H6199_ABCD" / "Govee_H6008_1234" -> "H6199"
    for part in name.replace("-", "_").split("_"):
        if len(part) == 5 and part[0] in "Hh" and part[1:].isalnum():
            return part.upper()
    return ""


def available() -> bool:
    try:
        import bleak  # noqa: F401
    except ImportError:
        return False
    return True


class BleClient:
    """Runs a private asyncio loop in a thread so callers can stay synchronous."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: dict[str, object] = {}
        self._keepalive_task = None

    def start(self) -> bool:
        if not available():
            return False
        if self._loop:
            return True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="govee-ble", daemon=True)
        self._thread.start()
        self._submit(self._keepalive())
        return True

    def stop(self) -> None:
        if not self._loop:
            return
        fut = self._submit(self._disconnect_all())
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop = None

    def _submit(self, coro) -> Future:
        assert self._loop is not None, "BLE client not started"
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # public API ------------------------------------------------------------
    def scan(self, timeout: float = 6.0) -> list[tuple[str, str]]:
        """Return [(address, name)] of nearby Govee lights. Blocks."""
        if not self.start():
            raise RuntimeError("Bluetooth support needs the 'bleak' package")
        return self._submit(self._scan(timeout)).result(timeout + 5)

    def write(self, address: str, packet: bytes) -> Future:
        if not self.start():
            raise RuntimeError("Bluetooth support needs the 'bleak' package")
        return self._submit(self._write(address, packet))

    # internals ---------------------------------------------------------------
    async def _scan(self, timeout: float):
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout)
        return [(d.address, d.name) for d in found if looks_like_govee(d.name)]

    async def _client(self, address: str):
        from bleak import BleakClient
        client = self._clients.get(address)
        if client is not None and client.is_connected:
            return client
        client = BleakClient(address, timeout=10.0)
        await client.connect()
        self._clients[address] = client
        return client

    async def _write(self, address: str, packet: bytes) -> None:
        try:
            client = await self._client(address)
            await client.write_gatt_char(WRITE_CHARACTERISTIC, packet, response=False)
        except Exception as exc:
            self._clients.pop(address, None)
            log.warning("Bluetooth write to %s failed: %s", address, exc)
            raise

    async def _keepalive(self) -> None:
        packet = keepalive_packet()
        while True:
            await asyncio.sleep(2.0)
            for address, client in list(self._clients.items()):
                if client.is_connected:
                    try:
                        await client.write_gatt_char(WRITE_CHARACTERISTIC, packet, response=False)
                    except Exception:
                        self._clients.pop(address, None)

    async def _disconnect_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
