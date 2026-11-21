"""Black bar detection.

Films in 21:9 on a 16:9 screen (or 4:3 content) have black bars. Without
cropping them the top and bottom zones are always black. Bars are only
accepted when they are symmetric and stable for a moment, so a dark scene
doesn't make the crop jump around.
"""

from __future__ import annotations

import numpy as np

Box = tuple[int, int, int, int]  # top, bottom, left, right in pixels


def _bar(dark: np.ndarray) -> int:
    """Number of leading True values."""
    if dark.all():
        return len(dark)
    return int(np.argmin(dark))


def detect(frame: np.ndarray, threshold: int = 18, max_fraction: float = 0.3) -> Box:
    h, w = frame.shape[:2]
    peak = frame.max(axis=2)
    dark_rows = peak.max(axis=1) < threshold
    dark_cols = peak.max(axis=0) < threshold
    top, bottom = _bar(dark_rows), _bar(dark_rows[::-1])
    left, right = _bar(dark_cols), _bar(dark_cols[::-1])
    v = min(top, bottom)
    hz = min(left, right)
    # whole frame dark or bars implausibly large: don't crop
    if v >= h * max_fraction:
        v = 0
    if hz >= w * max_fraction:
        hz = 0
    # tolerate a row of compression noise at the bar edge
    if v <= 1:
        v = 0
    if hz <= 1:
        hz = 0
    return v, v, hz, hz


class BarDetector:
    def __init__(self, stable_frames: int = 10, threshold: int = 18):
        self.stable_frames = stable_frames
        self.threshold = threshold
        self.box: Box = (0, 0, 0, 0)
        self._candidate: Box = (0, 0, 0, 0)
        self._count = 0

    def reset(self) -> None:
        self.box = (0, 0, 0, 0)
        self._candidate = self.box
        self._count = 0

    def __call__(self, frame: np.ndarray) -> Box:
        found = detect(frame, self.threshold)
        # picture content appeared inside the current bars: shrink at once
        if any(f < b for f, b in zip(found, self.box)):
            self.box = tuple(min(f, b) for f, b in zip(found, self.box))
            self._candidate, self._count = self.box, 0
            return self.box
        if found == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = found, 1
        if self._count >= self.stable_frames:
            self.box = found
        return self.box


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    top, bottom, left, right = box
    h, w = frame.shape[:2]
    return frame[top:h - bottom or None, left:w - right or None]


def map_rect(rect, box: Box, shape) -> tuple[float, float, float, float]:
    """Map a zone of the cropped picture back to full-frame coordinates."""
    top, bottom, left, right = box
    h, w = shape[:2]
    ch, cw = max(1, h - top - bottom), max(1, w - left - right)
    x0, y0, x1, y1 = rect
    return ((left + x0 * cw) / w, (top + y0 * ch) / h, (left + x1 * cw) / w, (top + y1 * ch) / h)
