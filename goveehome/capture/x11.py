"""X11 capture.

Uses GStreamer's ximagesrc (X shared memory, ~60 frames a second even on a
4K screen) when the GStreamer "good" plugins are installed, and falls back
to `mss`, which is several times slower on big screens.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import numpy as np

from goveehome.capture.base import FRAME_HEIGHT, FRAME_WIDTH, CaptureBackend, CaptureError, downscale
from goveehome.capture.gst import GstCapture, has_element

try:
    from PIL import Image
except ImportError:
    Image = None


def _has_mss() -> bool:
    try:
        import mss  # noqa: F401
    except ImportError:
        return False
    return True


def available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    return has_element("ximagesrc") or _has_mss()


def _xrandr_monitors() -> list[dict]:
    if not shutil.which("xrandr"):
        return []
    try:
        out = subprocess.run(["xrandr", "--listactivemonitors"], capture_output=True, text=True,
                             timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)$", line.strip())
        if m:
            w, h, x, y, name = m.groups()
            found.append({"width": int(w), "height": int(h), "left": int(x), "top": int(y), "output": name})
    return found


def monitors() -> list[dict]:
    """[{index, width, height, left, top}]; index 0 is all monitors together."""
    if not os.environ.get("DISPLAY"):
        return []
    mons: list[dict] = []
    if _has_mss():
        import mss
        try:
            with mss.mss() as sct:
                mons = [dict(m) for m in sct.monitors]
        except Exception:
            mons = []
    if not mons:
        single = _xrandr_monitors()
        if single:
            left = min(m["left"] for m in single)
            top = min(m["top"] for m in single)
            right = max(m["left"] + m["width"] for m in single)
            bottom = max(m["top"] + m["height"] for m in single)
            mons = [{"left": left, "top": top, "width": right - left, "height": bottom - top}] + single
    return [{"index": i, **m} for i, m in enumerate(mons)]


class X11GstCapture(GstCapture):
    id = "x11"
    label = "X11"

    def __init__(self, monitor: int = 1):
        super().__init__()
        self.monitor = monitor

    def source_description(self) -> str:
        desc = "ximagesrc name=src use-damage=false show-pointer=false"
        mons = monitors()
        if mons and 0 < self.monitor < len(mons) and len(mons) > 2:
            m = mons[self.monitor]
            desc += (f" startx={m['left']} starty={m['top']}"
                     f" endx={m['left'] + m['width'] - 1} endy={m['top'] + m['height'] - 1}")
        return desc + " ! video/x-raw,framerate=60/1"

    def _measure_age(self, sample) -> None:
        self.last_age = None  # ximagesrc grabs on demand, there is no queue to measure


class MssCapture(CaptureBackend):
    id = "x11"
    label = "X11 (mss)"

    def __init__(self, monitor: int = 1):
        self.monitor = monitor
        self._sct = None
        self._region = None

    def open(self) -> None:
        try:
            import mss
        except ImportError as exc:
            raise CaptureError("X11 capture needs the GStreamer 'good' plugins or the 'mss' package") from exc
        try:
            self._sct = mss.mss()
        except Exception as exc:
            raise CaptureError(f"Cannot open the X display: {exc}") from exc
        mons = self._sct.monitors
        self._region = mons[self.monitor if 0 <= self.monitor < len(mons) else 0]

    def grab(self) -> np.ndarray:
        if self._sct is None:
            self.open()
        try:
            shot = self._sct.grab(self._region)
        except Exception as exc:
            raise CaptureError(f"X11 capture failed: {exc}") from exc
        if Image is not None:
            img = Image.frombuffer("RGB", (shot.width, shot.height), shot.bgra, "raw", "BGRX", 0, 1)
            return np.asarray(img.resize((FRAME_WIDTH, FRAME_HEIGHT), Image.BOX))
        bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return downscale(bgra[:, :, 2::-1])

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


def X11Capture(monitor: int = 1) -> CaptureBackend:
    return X11GstCapture(monitor) if has_element("ximagesrc") else MssCapture(monitor)
