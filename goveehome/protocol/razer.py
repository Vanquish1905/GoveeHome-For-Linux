"""Segment streaming packets ("razer" command of the LAN API).

Govee lights that support DreamView / Razer Chroma accept a binary frame
wrapped in the LAN JSON message:

    {"msg": {"cmd": "razer", "data": {"pt": "<base64 frame>"}}}

Frame layout (all values are single bytes):

    BB 00 LEN B0 GRADIENT COUNT R G B R G B ... XOR

LEN is ``COUNT * 3 + 2``, GRADIENT is 1 to let the light blend between the
given colours and XOR is the XOR of every preceding byte. Streaming has to be
switched on first with ``BB 00 01 B1 01 XOR`` and off again with
``BB 00 01 B1 00 XOR``; while it is on the light ignores its own effects.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence

from goveehome.colors import RGB, clamp

MAX_SEGMENTS = 84  # keeps LEN within a single byte


def checksum(data: Iterable[int]) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def _finish(frame: list[int]) -> bytes:
    frame.append(checksum(frame))
    return bytes(frame)


def enable_frame(enabled: bool) -> bytes:
    return _finish([0xBB, 0x00, 0x01, 0xB1, 0x01 if enabled else 0x00])


def color_frame(colors: Sequence[RGB], gradient: bool = False) -> bytes:
    if not colors:
        raise ValueError("at least one colour is required")
    colors = list(colors)[:MAX_SEGMENTS]
    frame = [0xBB, 0x00, len(colors) * 3 + 2, 0xB0, 0x01 if gradient else 0x00, len(colors)]
    for r, g, b in colors:
        frame.extend((clamp(r), clamp(g), clamp(b)))
    return _finish(frame)


def encode(frame: bytes) -> str:
    return base64.b64encode(frame).decode("ascii")


def decode(pt: str) -> bytes:
    return base64.b64decode(pt)
