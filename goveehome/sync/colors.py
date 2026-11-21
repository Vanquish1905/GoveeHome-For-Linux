"""Turning screen pixels into light colours."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from goveehome.sync.zones import Rect


def zone_pixels(frame: np.ndarray, rect: Rect) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = rect
    xa, xb = int(x0 * w), max(int(x0 * w) + 1, int(round(x1 * w)))
    ya, yb = int(y0 * h), max(int(y0 * h) + 1, int(round(y1 * h)))
    return frame[ya:yb, xa:xb].reshape(-1, 3)


def average(pixels: np.ndarray) -> np.ndarray:
    return pixels.astype(np.float32).mean(axis=0)


def vivid(pixels: np.ndarray) -> np.ndarray:
    """Average weighted towards saturated, bright pixels.

    A plain average of a mostly grey frame with a red logo gives a muddy pink;
    weighting by chroma keeps the red, which is what people expect from
    ambient lighting. Falls back to the plain average for grey content.
    """
    px = pixels.astype(np.float32)
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    chroma = mx - mn
    weights = chroma * chroma + mx * 0.5 + 1.0
    total = weights.sum()
    return (px * weights[:, None]).sum(axis=0) / total


def adjust(color: np.ndarray, saturation: float = 1.0, brightness: float = 1.0,
           black_level: float = 0.0) -> np.ndarray:
    c = np.asarray(color, dtype=np.float32)
    lum = 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    c = lum[..., None] + (c - lum[..., None]) * saturation
    c = c * brightness
    c = np.clip(c, 0, 255)
    if black_level > 0:
        dark = c.max(axis=-1) < black_level
        c[dark] = 0
    return c


def extract(frame: np.ndarray, rects: Sequence[Rect], mode: str = "vivid") -> np.ndarray:
    fn = vivid if mode == "vivid" else average
    cache: dict[Rect, np.ndarray] = {}
    out = np.zeros((len(rects), 3), dtype=np.float32)
    for i, rect in enumerate(rects):
        if rect not in cache:
            cache[rect] = fn(zone_pixels(frame, rect))
        out[i] = cache[rect]
    return out


class Smoother:
    """Exponential smoothing that reacts faster to big changes (scene cuts)."""

    def __init__(self, smoothing: float = 0.5):
        self.smoothing = smoothing
        self._value: np.ndarray | None = None

    def reset(self) -> None:
        self._value = None

    def __call__(self, target: np.ndarray) -> np.ndarray:
        target = np.asarray(target, dtype=np.float32)
        if self._value is None or self._value.shape != target.shape or self.smoothing <= 0:
            self._value = target.copy()
            return self._value
        base = 1.0 - min(0.97, self.smoothing)
        diff = np.abs(target - self._value).max(axis=-1, keepdims=True) / 255.0
        alpha = np.clip(base + diff * (1.0 - base), base, 1.0)
        self._value = self._value + (target - self._value) * alpha
        return self._value


def to_rgb_list(colors: np.ndarray) -> list[tuple[int, int, int]]:
    return [tuple(int(v) for v in row) for row in np.clip(np.rint(colors), 0, 255).astype(np.uint8)]
