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
    "accurate": "Accurate",
    "vivid": "Vivid",
    "dominant": "Dominant colour",
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


def vivid(lin: np.ndarray) -> np.ndarray:
    """Mean weighted towards saturated pixels.

    A red logo on a grey page should make the light red, not pinkish grey.
    Grey content falls back to the plain mean.
    """
    mx = lin.max(axis=1)
    chroma = (mx - lin.min(axis=1)) / 255.0
    weights = 1.0 + 12.0 * chroma * chroma + 0.5 * mx / 255.0
    return (lin * weights[:, None]).sum(axis=0) / weights.sum()


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
            value = vivid(lin)
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


def to_rgb_list(colors: np.ndarray) -> list[tuple[int, int, int]]:
    return [tuple(int(v) for v in row) for row in np.clip(np.rint(colors), 0, 255).astype(np.uint8)]
