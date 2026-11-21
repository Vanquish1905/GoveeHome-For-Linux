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


def detect(frame: np.ndarray, threshold: int = 18, max_fraction: float = 0.3,
           edge: int = 40) -> Box:
    """Find letterbox / pillarbox bars.

    Real bars are pitch black, the same size on both sides and end in a
    clear edge to the picture. Dark film scenes fade out gradually and are
    rarely symmetric, so they don't count as bars.
    """
    h, w = frame.shape[:2]
    peak = frame.max(axis=2)
    row_peak = peak.max(axis=1)
    col_peak = peak.max(axis=0)
    dark_rows = row_peak < threshold
    dark_cols = col_peak < threshold
    top, bottom = _bar(dark_rows), _bar(dark_rows[::-1])
    left, right = _bar(dark_cols), _bar(dark_cols[::-1])

    def accept(a: int, b: int, size: int, peaks: np.ndarray) -> int:
        bar = min(a, b)
        if bar <= 1 or bar >= size * max_fraction:
            return 0
        if abs(a - b) > max(2, size // 40):
            return 0                      # not symmetric: a dark scene, not bars
        if peaks[a] < edge or peaks[size - 1 - b] < edge:
            return 0                      # no sharp edge where the picture starts
        return bar

    v = accept(top, bottom, h, row_peak)
    hz = accept(left, right, w, col_peak)
    return v, v, hz, hz


class BarDetector:
    def __init__(self, stable_frames: int = 30, threshold: int = 18):
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
