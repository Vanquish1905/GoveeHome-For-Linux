"""Small colour helpers shared by the protocols, the sync engine and the UI."""

from __future__ import annotations

import math
import re

RGB = tuple[int, int, int]

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

NAMED_COLORS: dict[str, RGB] = {
    "red": (255, 0, 0),
    "orange": (255, 110, 0),
    "amber": (255, 160, 20),
    "yellow": (255, 220, 0),
    "lime": (150, 255, 0),
    "green": (0, 255, 40),
    "teal": (0, 255, 170),
    "cyan": (0, 230, 255),
    "blue": (0, 60, 255),
    "indigo": (80, 0, 255),
    "violet": (170, 0, 255),
    "magenta": (255, 0, 200),
    "pink": (255, 60, 120),
    "white": (255, 255, 255),
    "warm": (255, 180, 107),
}


def clamp(value: float, lo: int = 0, hi: int = 255) -> int:
    return int(max(lo, min(hi, round(value))))


def parse_color(text: str) -> RGB:
    """Parse '#ff8800', 'ff8800', '#f80', 'red' or '255,136,0'."""
    text = text.strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"expected three values, got {text!r}")
        r, g, b = (int(p) for p in parts)
        if not all(0 <= v <= 255 for v in (r, g, b)):
            raise ValueError("colour values must be between 0 and 255")
        return r, g, b
    match = _HEX_RE.match(text)
    if not match:
        raise ValueError(f"not a colour: {text!r}")
    h = match.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def rgb_to_int(rgb: RGB) -> int:
    r, g, b = rgb
    return (r << 16) | (g << 8) | b


def int_to_rgb(value: int) -> RGB:
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def kelvin_to_rgb(kelvin: float) -> RGB:
    """Approximate the colour of a black body radiator.

    Based on the well known fit by Tanner Helland; accurate enough to paint a
    preview swatch for a white temperature.
    """
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    return clamp(r), clamp(g), clamp(b)


def luminance(rgb: RGB) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
