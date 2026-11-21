"""Colour palettes for music sync (and anything else that wants one).

A palette is a short list of colours the light show blends between. The
special "custom" palette uses colours the user picked.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from goveehome.colors import parse_color

# id -> (label, colours). None means the full rainbow.
PALETTES: dict[str, tuple[str, list[str] | None]] = {
    "rainbow": ("Rainbow", None),
    "custom": ("Your colours", []),
    "warm": ("Warm", ["#ff0000", "#ff5a00", "#ffc800", "#ff005a"]),
    "cool": ("Cool", ["#0050ff", "#00dcff", "#7800ff", "#00ffa0"]),
    "neon": ("Neon", ["#ff00c8", "#00fff0", "#b4ff00", "#7800ff"]),
    "fire": ("Fire", ["#ff1400", "#ff7800", "#ffc828"]),
    "ocean": ("Ocean", ["#0028a0", "#0078ff", "#00dcc8", "#0046c8"]),
    "forest": ("Forest", ["#14a000", "#78dc00", "#007828", "#c8c800"]),
    "sunset": ("Sunset", ["#ff5a00", "#ff283c", "#c80078", "#5a00a0"]),
    "aurora": ("Aurora", ["#00ff78", "#00b4c8", "#5a00ff", "#00ff3c"]),
    "pastel": ("Pastel", ["#ff9ec8", "#9ed8ff", "#c8ff9e", "#e0b0ff", "#ffe29e"]),
    "candy": ("Candy", ["#ff3c9b", "#ff9ee0", "#7ae1ff", "#ffffff"]),
    "cyberpunk": ("Cyberpunk", ["#ff007a", "#00f0ff", "#fcee0a", "#7a00ff"]),
    "vaporwave": ("Vaporwave", ["#ff71ce", "#01cdfe", "#05ffa1", "#b967ff"]),
    "lava": ("Lava", ["#800000", "#ff2000", "#ff6a00", "#ffb000"]),
    "ice": ("Ice", ["#ffffff", "#9ee6ff", "#3c8cff", "#c8f0ff"]),
    "gold": ("Gold", ["#ffb400", "#ffd25a", "#c87800", "#fff0b4"]),
    "love": ("Love", ["#ff0040", "#ff4d94", "#c80050", "#ff9ec0"]),
    "purple": ("Purple rain", ["#5a00c8", "#a000ff", "#ff00c8", "#3c00a0"]),
    "tropical": ("Tropical", ["#00ffb4", "#ffdc00", "#ff5a78", "#00b4ff"]),
    "retro": ("Retro", ["#ff8c00", "#e6421e", "#008c8c", "#ffd23c"]),
    "club": ("Club", ["#ff0000", "#0000ff", "#ff00ff", "#00ffff"]),
    "christmas": ("Christmas", ["#ff0000", "#00c800", "#ffffff"]),
    "halloween": ("Halloween", ["#ff6400", "#8c00ff", "#3cff00"]),
    "white": ("White", ["#ffffff", "#ffd8a8"]),
}

DEFAULT_CUSTOM = ["#ff0050", "#00b4ff", "#ffd200"]


def _hsv(u: np.ndarray) -> np.ndarray:
    h = np.asarray(u, dtype=np.float32) % 1.0
    i = np.floor(h * 6).astype(np.int32) % 6
    f = h * 6 - np.floor(h * 6)
    one, zero = np.ones_like(h), np.zeros_like(h)
    q, t = 1 - f, f
    r = np.choose(i, [one, q, zero, zero, t, one])
    g = np.choose(i, [t, one, one, q, zero, zero])
    b = np.choose(i, [zero, zero, t, one, one, q])
    return np.stack([r, g, b], axis=-1) * 255.0


def blend(colors: Sequence[Sequence[float]], u: np.ndarray, cyclic: bool = True) -> np.ndarray:
    """Interpolate a list of colours at positions u (0..1)."""
    pal = np.asarray(colors, dtype=np.float32).reshape(-1, 3)
    n = len(pal)
    u = np.asarray(u, dtype=np.float32)
    if n == 1:
        return np.broadcast_to(pal[0], u.shape + (3,)).astype(np.float32)
    if cyclic:
        x = (u % 1.0) * n
        i0 = np.floor(x).astype(np.int32) % n
        i1 = (i0 + 1) % n
    else:
        x = np.clip(u, 0, 1) * (n - 1)
        i0 = np.clip(np.floor(x).astype(np.int32), 0, n - 1)
        i1 = np.clip(i0 + 1, 0, n - 1)
    f = (x - np.floor(x))[..., None]
    f = f * f * (3 - 2 * f)  # smoothstep, softer transitions
    return pal[i0] * (1 - f) + pal[i1] * f


def colors_of(palette_id: str, custom: Sequence[str] | None = None) -> list[tuple[int, int, int]] | None:
    label, hexes = PALETTES.get(palette_id, PALETTES["rainbow"])
    if palette_id == "custom":
        hexes = list(custom or []) or DEFAULT_CUSTOM
    if hexes is None:
        return None
    out = []
    for h in hexes:
        try:
            out.append(parse_color(h))
        except ValueError:
            pass
    return out or [(255, 255, 255)]


def palette_fn(palette_id: str, custom: Sequence[str] | None = None) -> Callable[[np.ndarray], np.ndarray]:
    cols = colors_of(palette_id, custom)
    if cols is None:
        return _hsv
    return lambda u: blend(cols, u)


def preview_colors(palette_id: str, custom: Sequence[str] | None = None, steps: int = 7) -> list[tuple]:
    fn = palette_fn(palette_id, custom)
    return [tuple(int(c) for c in row) for row in fn(np.linspace(0, 1, steps, endpoint=False))]
