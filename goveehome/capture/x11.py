"""X11 capture through the `mss` package (XGetImage / XShm)."""

from __future__ import annotations

import os

import numpy as np

from goveehome.capture.base import CaptureBackend, CaptureError, downscale


def available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        import mss  # noqa: F401
    except ImportError:
        return False
    return True


class X11Capture(CaptureBackend):
    id = "x11"
    label = "X11"

    def __init__(self, monitor: int = 0):
        self.monitor = monitor
        self._sct = None
        self._region = None

    def open(self) -> None:
        try:
            import mss
        except ImportError as exc:
            raise CaptureError("X11 capture needs the 'mss' package") from exc
        try:
            self._sct = mss.mss()
        except Exception as exc:
            raise CaptureError(f"Cannot open the X display: {exc}") from exc
        monitors = self._sct.monitors  # [0] is the union of all monitors
        index = self.monitor if 0 <= self.monitor < len(monitors) else 0
        self._region = monitors[index]

    def grab(self) -> np.ndarray:
        if self._sct is None:
            self.open()
        try:
            shot = self._sct.grab(self._region)
        except Exception as exc:
            raise CaptureError(f"X11 capture failed: {exc}") from exc
        bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return downscale(bgra[:, :, 2::-1])

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None
