"""Colours for single segments of a light, like "Segment" colouring in the Govee app.

The colours are kept by the light itself (unlike a light show, nothing has to
keep running). Over LAN they travel as Bluetooth style packets wrapped in a
``ptReal`` message; over Bluetooth the same packets are written directly; the
cloud API has its own segment command.

Packet (20 bytes, last byte XOR of the others):

    33 05 15 01  R G B  00 00 00 00 00  M0 M1 ...   colour for the segments in the mask
    33 05 15 02  BR     M0 M1 ...                    brightness (1-100) for those segments

The mask has one bit per segment, segment 1 = bit 0 of M0.
"""

from __future__ import annotations

import colorsys

from goveehome.colors import RGB, clamp, parse_color, to_hex
from goveehome.protocol.ble import build_packet

MAX_SEGMENTS = 56          # 7 mask bytes fit in a packet

# built-in looks, stretched over any number of segments
BUILT_IN: dict[str, list[str]] = {
    "Rainbow": ["#ff0000", "#ff8000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#8000ff"],
    "Sunset": ["#ff2a00", "#ff6a00", "#ffa200", "#ff4a6a", "#a03cff"],
    "Ocean": ["#00204a", "#0050c8", "#00a0ff", "#00e0d0", "#0050c8"],
    "Forest": ["#0a5a00", "#3ca000", "#a0e000", "#3ca000", "#0a5a00"],
    "Fire": ["#ff1000", "#ff5000", "#ffa000", "#ff5000", "#ff1000"],
    "Candy": ["#ff40a0", "#40c0ff"],
    "Christmas": ["#ff0000", "#00c000"],
    "Police": ["#ff0000", "#0000ff"],
    "Halloween": ["#ff5a00", "#8000ff"],
    "Ice": ["#ffffff", "#a0e0ff", "#40a0ff", "#a0e0ff"],
    "Neon": ["#ff00ff", "#00ffff", "#ffff00"],
    "Warm and cosy": ["#ff7a20", "#ffb050", "#ff9030"],
}

FILLS = {
    "gradient": "Gradient",
    "rainbow": "Rainbow",
    "alternate": "Alternating",
    "mirror": "Mirrored gradient",
}


def mask_bytes(segments, count: int) -> list[int]:
    """Bit mask for 0-based segment indexes, at least 2 bytes long."""
    width = max(2, (max(count, 1) + 7) // 8)
    width = min(width, 7)
    out = [0] * width
    for s in segments:
        s = int(s)
        if 0 <= s < width * 8:
            out[s // 8] |= 1 << (s % 8)
    return out


def colour_packet(segments, rgb: RGB, count: int) -> bytes:
    r, g, b = (clamp(c) for c in rgb)
    return build_packet(0x33, 0x05, [0x15, 0x01, r, g, b, 0, 0, 0, 0, 0, *mask_bytes(segments, count)])


def brightness_packet(segments, percent: int, count: int) -> bytes:
    return build_packet(0x33, 0x05, [0x15, 0x02, clamp(percent, 1, 100), *mask_bytes(segments, count)])


def group_colours(colours) -> list[tuple[RGB, list[int]]]:
    """[(colour, [segments])], one entry per distinct colour, segments without a colour left out."""
    groups: dict[RGB, list[int]] = {}
    for i, c in enumerate(colours):
        if c is None:
            continue
        groups.setdefault(tuple(int(v) for v in c), []).append(i)
    return list(groups.items())


def packets(colours) -> list[bytes]:
    count = len(colours)
    return [colour_packet(segs, rgb, count) for rgb, segs in group_colours(colours)]


# fills ------------------------------------------------------------------------------------
def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def stretch(stops, n: int) -> list[RGB]:
    """Spread a list of colours smoothly over n segments."""
    stops = [parse_color(s) if isinstance(s, str) else tuple(s) for s in stops]
    if n <= 0:
        return []
    if len(stops) == 1 or n == 1:
        return [stops[0]] * n
    out = []
    for i in range(n):
        pos = i / (n - 1) * (len(stops) - 1)
        k = min(int(pos), len(stops) - 2)
        out.append(_mix(stops[k], stops[k + 1], pos - k))
    return out


def fill(kind: str, n: int, a: RGB = (255, 0, 0), b: RGB = (0, 0, 255)) -> list[RGB]:
    if kind == "rainbow":
        return [tuple(int(round(v * 255)) for v in colorsys.hsv_to_rgb(i / max(n, 1), 1, 1)) for i in range(n)]
    if kind == "alternate":
        return [a if i % 2 == 0 else b for i in range(n)]
    if kind == "mirror":
        half = (n + 1) // 2
        left = stretch([a, b], half)
        return left + left[: n - half][::-1]
    return stretch([a, b], n)


def apply_fill(colours: list, selected, kind: str, a: RGB, b: RGB) -> list:
    """Fill the selected segments (all when none are selected) in order."""
    chosen = sorted(selected) or list(range(len(colours)))
    out = list(colours)
    for idx, rgb in zip(chosen, fill(kind, len(chosen), a, b)):
        out[idx] = rgb
    return out


def preset_colours(preset, n: int) -> list[RGB]:
    """A saved or built-in preset on a light with n segments."""
    stops = BUILT_IN.get(preset, preset) if isinstance(preset, str) else preset
    stops = [parse_color(s) for s in stops]
    if len(stops) == n:
        return stops
    if isinstance(preset, str) and len(stops) <= 2:
        # two colour looks repeat instead of blending
        return [stops[i % len(stops)] for i in range(n)]
    return stretch(stops, n)


def to_hex_list(colours) -> list[str | None]:
    return [to_hex(c) if c is not None else None for c in colours]


def from_hex_list(values, n: int) -> list[RGB | None]:
    out: list[RGB | None] = []
    for v in (values or [])[:n]:
        try:
            out.append(parse_color(v) if v else None)
        except ValueError:
            out.append(None)
    return out + [None] * (n - len(out))


def parse_spec(spec: str, n: int) -> list[tuple[list[int], RGB]]:
    """'1-5=red' or '3,7=#00ff00' or 'all=blue' -> [(0-based segments, colour)]."""
    if "=" not in spec:
        raise ValueError(f"expected SEGMENTS=COLOUR, got {spec!r}")
    where, colour = spec.split("=", 1)
    rgb = parse_color(colour)
    segs: list[int] = []
    for part in where.split(","):
        part = part.strip().lower()
        if part in ("all", "*"):
            segs += range(n)
        elif "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            segs += range(lo - 1, hi)
        elif part:
            segs.append(int(part) - 1)
    bad = [s + 1 for s in segs if not 0 <= s < n]
    if bad:
        raise ValueError(f"this light has segments 1-{n}, not {bad[0]}")
    return [(sorted(set(segs)), rgb)]
