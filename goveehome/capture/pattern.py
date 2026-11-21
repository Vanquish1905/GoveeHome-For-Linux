"""A moving test image. Handy for checking zone layouts without a screen."""

from __future__ import annotations

import time

import numpy as np

from goveehome.capture.base import FRAME_HEIGHT, FRAME_WIDTH, CaptureBackend


class PatternCapture(CaptureBackend):
    id = "pattern"
    label = "Test pattern"

    def __init__(self):
        x = np.linspace(0.0, 1.0, FRAME_WIDTH, dtype=np.float32)
        y = np.linspace(0.0, 1.0, FRAME_HEIGHT, dtype=np.float32)
        self._xx, self._yy = np.meshgrid(x, y)
        self._start = time.monotonic()

    def grab(self) -> np.ndarray:
        t = (time.monotonic() - self._start) * 0.15
        hue = (self._xx * 0.8 + self._yy * 0.2 + t) % 1.0
        # hsv -> rgb with s = v = 1
        h6 = hue * 6.0
        c = np.ones_like(hue)
        x = 1.0 - np.abs(h6 % 2.0 - 1.0)
        z = np.zeros_like(hue)
        idx = h6.astype(np.int32) % 6
        r = np.choose(idx, [c, x, z, z, x, c])
        g = np.choose(idx, [x, c, c, x, z, z])
        b = np.choose(idx, [z, z, x, c, c, x])
        frame = np.stack([r, g, b], axis=-1)
        # dark band in the middle, like a letterboxed film
        frame[int(FRAME_HEIGHT * 0.3):int(FRAME_HEIGHT * 0.7), int(FRAME_WIDTH * 0.25):int(FRAME_WIDTH * 0.75)] *= 0.15
        time.sleep(0.005)
        return (frame * 255).astype(np.uint8)
