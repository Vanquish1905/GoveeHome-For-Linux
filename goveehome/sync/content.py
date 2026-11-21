"""Find the part of the screen where the picture is.

When a film or game runs in a window, the screen edges show a white web page
or the desktop, and lights that take their colour from the edges turn white.
This tracker looks for the area where the picture moves and hands back a
crop box, so the zones are laid over the video instead of the whole screen.
Letterbox bars are excluded on the way, because they never move.

The box only changes when the new one has been stable for a moment, and it
falls back to the whole screen after a while without any movement.
"""

from __future__ import annotations

import numpy as np

Box = tuple[int, int, int, int]  # top, bottom, left, right in pixels, as in letterbox
FULL: Box = (0, 0, 0, 0)


def _span(active: np.ndarray) -> tuple[int, int] | None:
    idx = np.flatnonzero(active)
    if len(idx) == 0:
        return None
    return int(idx[0]), int(idx[-1])


class ContentTracker:
    def __init__(self, decay: float = 0.9, threshold: float = 4.0, line_share: float = 0.12,
                 min_area: float = 0.06, stable_frames: int = 12, idle_frames: int = 300):
        self.decay = decay                  # how long movement is remembered
        self.threshold = threshold          # brightness change that counts as movement
        self.line_share = line_share        # share of a row/column that must move
        self.min_area = min_area            # smaller areas are ignored (clocks, cursors)
        self.stable_frames = stable_frames
        self.idle_frames = idle_frames      # ~10 s at 30 fps without movement -> whole screen
        self.box: Box = FULL
        self._prev: np.ndarray | None = None
        self._motion: np.ndarray | None = None
        self._candidate: Box = FULL
        self._count = 0
        self._idle = 0

    def reset(self) -> None:
        self.__init__(self.decay, self.threshold, self.line_share, self.min_area,
                      self.stable_frames, self.idle_frames)

    def _measure(self, frame: np.ndarray) -> Box | None:
        h, w = frame.shape[:2]
        gray = frame.astype(np.float32).mean(axis=2)
        if self._prev is None or self._prev.shape != gray.shape:
            self._prev = gray
            self._motion = np.zeros_like(gray)
            return None
        diff = np.abs(gray - self._prev)
        self._prev = gray
        self._motion = self._motion * self.decay + diff * (1 - self.decay)
        active = self._motion > self.threshold * (1 - self.decay) * 2
        if active.mean() < 0.01:
            return None                      # nothing moves right now
        rows = _span(active.mean(axis=1) > self.line_share)
        cols = _span(active.mean(axis=0) > self.line_share)
        if rows is None or cols is None:
            return None
        top, bottom = rows
        left, right = cols
        area = (bottom - top + 1) * (right - left + 1) / (h * w)
        if area < self.min_area:
            return None
        box = (top, h - 1 - bottom, left, w - 1 - right)
        # nearly the whole screen moves: just use the whole screen
        if max(box) <= 2:
            return FULL
        return box

    def __call__(self, frame: np.ndarray) -> Box:
        found = self._measure(frame)
        if found is None:
            self._idle += 1
            if self._idle >= self.idle_frames:
                self.box = FULL
            return self.box
        self._idle = 0
        close = all(abs(a - b) <= 3 for a, b in zip(found, self._candidate))
        if close:
            self._count += 1
        else:
            self._candidate, self._count = found, 1
        if self._count >= self.stable_frames:
            self.box = self._candidate
        return self.box
