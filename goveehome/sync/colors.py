"""Turning screen pixels into light colours.

Screens store colours gamma encoded (sRGB); LEDs are driven linearly. Two
things follow from that and matter a lot for colours that actually match:

* zone colours are averaged in linear light, otherwise mixes come out too
  dark and muddy (the mean of black and white is not sRGB 128);
* the colour sent to an LED has to be gamma corrected, otherwise every
  colour looks pale because LEDs are far brighter at "half" than a screen.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from goveehome.sync.zones import Rect

SRGB_GAMMA = 2.2
_LUT_LINEAR = ((np.arange(256, dtype=np.float64) / 255.0) ** SRGB_GAMMA * 255.0).astype(np.float32)

MODES = {
    "vivid": "Colourful",
    "dominant": "Dominant colour",
    "accurate": "Exact average",
}


def to_linear(srgb: np.ndarray) -> np.ndarray:
    """uint8 sRGB -> float32 linear light, 0..255."""
    if srgb.dtype == np.uint8:
        return _LUT_LINEAR[srgb]
    return (np.clip(srgb, 0, 255) / 255.0) ** SRGB_GAMMA * 255.0


def to_srgb(linear: np.ndarray) -> np.ndarray:
    return (np.clip(linear, 0, 255) / 255.0) ** (1 / SRGB_GAMMA) * 255.0


def zone_slice(shape: tuple[int, ...], rect: Rect) -> tuple[slice, slice]:
    h, w = shape[:2]
    x0, y0, x1, y1 = rect
    xa = min(w - 1, int(x0 * w))
    ya = min(h - 1, int(y0 * h))
    xb = max(xa + 1, int(round(x1 * w)))
    yb = max(ya + 1, int(round(y1 * h)))
    return slice(ya, yb), slice(xa, xb)


def zone_pixels(frame: np.ndarray, rect: Rect) -> np.ndarray:
    ys, xs = zone_slice(frame.shape, rect)
    return frame[ys, xs].reshape(-1, 3)


# zone colour pickers; all take and return linear light ---------------------------

def average(lin: np.ndarray) -> np.ndarray:
    return lin.mean(axis=0)


def _hue(px: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hue (0..1), saturation and value of sRGB pixels."""
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    delta = mx - mn
    sat = delta / np.maximum(mx, 1.0)
    d = np.maximum(delta, 1e-6)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6.0
    return hue % 1.0, sat, mx / 255.0


def strongest_colour(srgb: np.ndarray, lin: np.ndarray, bins: int = 36, reach: int = 4,
                     min_share: float = 0.03) -> np.ndarray:
    """The colour you notice in an area, in linear light.

    Averaging very different colours gives grey (red + cyan, or a whole
    rainbow, average out to a pale grey), and white pages and grey UI wash
    everything out. Instead, pixels are grouped by hue, weighted by how
    saturated and bright they are, and the strongest colour family (about
    +-40 degrees of hue) is averaged on its own. Areas that really are grey,
    white or black stay that way.
    """
    px = srgb.astype(np.float32)
    hue, sat, val = _hue(px)
    colourful = (sat > 0.25) & (val > 0.1)
    if colourful.mean() < min_share:
        return lin.mean(axis=0)
    weights = sat * sat * val
    idx = (hue * bins).astype(np.int32) % bins
    hist = np.bincount(idx[colourful], weights=weights[colourful], minlength=bins)
    # circular smoothing so a colour sitting on a bin border isn't split
    window = sum(np.roll(hist, k) for k in range(-reach, reach + 1))
    centre = int(window.argmax())
    dist = np.abs(((idx - centre) + bins // 2) % bins - bins // 2)
    chosen = colourful & (dist <= reach)
    w = weights[chosen] + 1e-6
    return (lin[chosen] * w[:, None]).sum(axis=0) / w.sum()


def vivid(lin: np.ndarray, srgb: np.ndarray | None = None) -> np.ndarray:
    """The "Colourful" pick: the strongest colour in the zone, see strongest_colour()."""
    px = srgb if srgb is not None else to_srgb(lin)
    return strongest_colour(px, lin)


def dominant(lin: np.ndarray, srgb: np.ndarray, bins: int = 24) -> np.ndarray:
    """The colour covering most of the zone, judged by hue.

    Pixels are grouped into hue bins weighted by saturation and brightness;
    the light gets the mean of the strongest bin and its neighbours. If the
    zone is mostly grey/black, the plain mean is used.
    """
    px = srgb.astype(np.float32)
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    delta = mx - mn
    sat = np.where(mx > 0, delta / np.maximum(mx, 1), 0)
    val = mx / 255.0
    colourful = (sat > 0.25) & (val > 0.12)
    if colourful.sum() < max(3, 0.06 * len(px)):
        return average(lin)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    d = np.maximum(delta, 1e-6)
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6.0
    idx = (hue * bins).astype(np.int32) % bins
    weights = sat * val
    hist = np.bincount(idx[colourful], weights=weights[colourful], minlength=bins)
    best = int(hist.argmax())
    near = colourful & ((idx == best) | (idx == (best + 1) % bins) | (idx == (best - 1) % bins))
    return lin[near].mean(axis=0)


class FrameAnalyzer:
    """Caches per-frame work shared by every light and zone."""

    def __init__(self, frame: np.ndarray):
        self.frame = frame
        self.linear = to_linear(frame)
        self._cache: dict[tuple, np.ndarray] = {}

    def zone(self, rect: Rect, mode: str = "accurate") -> np.ndarray:
        """Return the zone colour as sRGB float (0..255)."""
        key = (rect, mode)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        ys, xs = zone_slice(self.frame.shape, rect)
        lin = self.linear[ys, xs].reshape(-1, 3)
        if mode == "vivid":
            value = vivid(lin, self.frame[ys, xs].reshape(-1, 3))
        elif mode == "dominant":
            value = dominant(lin, self.frame[ys, xs].reshape(-1, 3))
        else:
            value = average(lin)
        value = to_srgb(value)
        self._cache[key] = value
        return value

    def zones(self, rects: Sequence[Rect], mode: str = "accurate") -> np.ndarray:
        out = np.zeros((len(rects), 3), dtype=np.float32)
        for i, rect in enumerate(rects):
            out[i] = self.zone(rect, mode)
        return out


def extract(frame: np.ndarray, rects: Sequence[Rect], mode: str = "accurate") -> np.ndarray:
    return FrameAnalyzer(frame).zones(rects, mode)


def adjust(color: np.ndarray, saturation: float = 1.0, brightness: float = 1.0,
           black_level: float = 0.0) -> np.ndarray:
    """Saturation / brightness / black level on sRGB float colours."""
    c = np.asarray(color, dtype=np.float32)
    lum = 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    c = lum[..., None] + (c - lum[..., None]) * saturation
    c = np.clip(c * brightness, 0, 255)
    if black_level > 0:
        dark = c.max(axis=-1) < black_level
        c[dark] = 0
    return c


def vivid_colours(colors: np.ndarray, vividness: float = 4.0, neutral: float = 0.06) -> np.ndarray:
    """Turn screen colours into clean light colours, like Govee's own sync.

    Picture colours are rarely pure: skin, sky or grass all have the three
    channels on. Lights with white LEDs (RGBWW / RGBICWW, like the H6056)
    show that shared part as white, so everything comes out pale or white.
    The saturation is pushed along a curve (1 - (1 - s) ** vividness):
    clearly coloured areas become pure colours, slightly tinted ones get
    stronger, and grey or white (saturation below `neutral`) stays neutral.
    Brightness (the strongest channel) is kept. vividness <= 1 is off.
    """
    c = np.asarray(colors, dtype=np.float32)
    if vividness <= 1.0:
        return c
    mx = c.max(axis=-1, keepdims=True)
    mn = c.min(axis=-1, keepdims=True)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    ramp = np.clip((sat - neutral) / (1 - neutral), 0, 1)
    new_sat = np.where(sat > neutral, 1 - (1 - ramp) ** vividness, sat)
    new_sat = np.maximum(new_sat, sat)
    # rebuild: same hue and brightness, new saturation
    with np.errstate(invalid="ignore", divide="ignore"):
        hue_part = np.where(mx - mn > 1e-6, (c - mn) / np.maximum(mx - mn, 1e-6), 0.0)
    new_min = mx * (1 - new_sat)
    return np.clip(new_min + hue_part * (mx - new_min), 0, 255)


def led_output(colors: np.ndarray, gamma: float = 2.0,
               gains: Sequence[float] = (1.0, 1.0, 1.0)) -> np.ndarray:
    """sRGB colours -> values for the LED driver (gamma + white balance)."""
    c = np.clip(np.asarray(colors, dtype=np.float32), 0, 255) / 255.0
    if gamma and abs(gamma - 1.0) > 1e-3:
        c = c ** gamma
    c = c * np.asarray(gains, dtype=np.float32)
    return np.clip(c * 255.0, 0, 255)


class Smoother:
    """Time based exponential smoothing that lets scene cuts through quickly.

    `smoothing` is a time constant in seconds: 0 is instant, 0.1 feels
    responsive but calm, 0.4 is slow and soft. Being time based, the feel
    doesn't change with the update rate.
    """

    CUT_THRESHOLD = 0.3  # fraction of full scale that counts as a cut

    def __init__(self, smoothing: float = 0.08):
        self.smoothing = smoothing
        self._value: np.ndarray | None = None
        self._time: float | None = None

    def reset(self) -> None:
        self._value = None
        self._time = None

    def __call__(self, target: np.ndarray, now: float | None = None) -> np.ndarray:
        target = np.asarray(target, dtype=np.float32)
        if now is None:
            now = (self._time if self._time is not None else 0.0) + 1 / 30
        if self._value is None or self._value.shape != target.shape or self.smoothing <= 0:
            self._value = target.copy()
            self._time = now
            return self._value
        dt = max(0.0, now - (self._time if self._time is not None else now))
        self._time = now
        alpha = 1.0 - np.exp(-dt / self.smoothing)
        diff = np.abs(target - self._value).max(axis=-1, keepdims=True) / 255.0
        # big jumps (scene cuts, flashes) follow almost immediately
        cut = np.clip((diff - self.CUT_THRESHOLD) / (1 - self.CUT_THRESHOLD), 0, 1)
        alpha = np.where(diff > self.CUT_THRESHOLD, np.maximum(alpha, 0.6 + 0.4 * cut), alpha)
        self._value = self._value + (target - self._value) * alpha
        return self._value


def combine(colors: np.ndarray) -> np.ndarray:
    """One colour for a light that can only show one, from its zone colours.

    Same idea as the Colourful pick: the strongest colour family wins, so a
    light next to a green forest and a white sky turns green, and a screen
    full of different colours gives one of them, not grey. Returns (1, 3).
    """
    c = np.asarray(colors, dtype=np.float32).reshape(-1, 3)
    if len(c) == 1:
        return c
    return to_srgb(strongest_colour(c, to_linear(c), min_share=0.0001))[None, :]


class ColourBoost:
    """Bring back the colour of a washed-out picture.

    Some captures come out pale: KDE Plasma with HDR switched on hands out a
    washed-out picture, and some content is just pastel. Lights then only
    ever get greyish colours. This measures how saturated the most colourful
    tenth of the picture is and, if that's low, raises the saturation of the
    whole frame before colours are picked. It changes slowly, so it doesn't
    pump with every scene, and grey stays grey (there's nothing to boost).
    """

    TARGET = 0.65        # saturation the colourful part of the picture should reach
    MAX = 3.5

    def __init__(self):
        self.factor = 1.0

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        px = frame.reshape(-1, 3).astype(np.float32)
        mx = px.max(axis=1)
        sat = (mx - px.min(axis=1)) / np.maximum(mx, 1.0)
        lit = sat[mx > 40]
        if len(lit) < 50:
            return frame
        p90 = float(np.percentile(lit, 90))
        target = float(np.clip(self.TARGET / max(p90, 0.05), 1.0, self.MAX)) if p90 < self.TARGET else 1.0
        self.factor += (target - self.factor) * 0.08
        if self.factor < 1.03:
            return frame
        f = frame.astype(np.float32)
        lum = (0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2])[..., None]
        return np.clip(lum + (f - lum) * self.factor, 0, 255).astype(np.uint8)


def to_rgb_list(colors: np.ndarray) -> list[tuple[int, int, int]]:
    return [tuple(int(v) for v in row) for row in np.clip(np.rint(colors), 0, 255).astype(np.uint8)]
