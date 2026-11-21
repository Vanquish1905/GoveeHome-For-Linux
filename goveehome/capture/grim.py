"""Capture via `grim` on wlroots compositors (Sway, Hyprland, river, ...).

Slower than the portal, but needs no permission dialog and works on
compositors whose portal lacks ScreenCast support.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import numpy as np

from goveehome.capture.base import CaptureBackend, CaptureError, downscale


def available() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) and shutil.which("grim") is not None


def parse_ppm(data: bytes) -> np.ndarray:
    """Parse a binary PPM (P6) image into an H x W x 3 array."""
    if not data.startswith(b"P6"):
        raise CaptureError("grim did not return a PPM image")
    fields: list[bytes] = []
    pos = 2
    while len(fields) < 3:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    pos += 1  # single whitespace before the pixel data
    width, height, maxval = (int(f) for f in fields)
    if maxval != 255:
        raise CaptureError("unsupported PPM depth")
    pixels = np.frombuffer(data, dtype=np.uint8, count=width * height * 3, offset=pos)
    return pixels.reshape(height, width, 3)


class GrimCapture(CaptureBackend):
    id = "grim"
    label = "grim (wlroots)"

    def __init__(self, output: str | None = None, scale: float = 0.1):
        self.output = output
        self.scale = scale

    def grab(self) -> np.ndarray:
        cmd = ["grim", "-t", "ppm", "-s", str(self.scale)]
        if self.output:
            cmd += ["-o", self.output]
        cmd.append("-")
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=2, check=True)
        except FileNotFoundError as exc:
            raise CaptureError("grim is not installed") from exc
        except subprocess.CalledProcessError as exc:
            raise CaptureError(exc.stderr.decode(errors="replace").strip() or "grim failed") from exc
        except subprocess.TimeoutExpired as exc:
            raise CaptureError("grim timed out") from exc
        return downscale(parse_ppm(result.stdout))
