"""Screen capture backends and automatic selection."""

from __future__ import annotations

import os

from goveehome.capture import grim, portal, x11
from goveehome.capture.base import CaptureBackend, CaptureError
from goveehome.capture.pattern import PatternCapture

__all__ = ["CaptureBackend", "CaptureError", "BACKENDS", "available_backends", "auto_backend", "create"]

# id -> label, in order of preference
BACKENDS: dict[str, str] = {
    "auto": "Automatic",
    "portal": portal.PortalCapture.label,
    "x11": "X11",
    "grim": grim.GrimCapture.label,
    "pattern": PatternCapture.label,
}


def _wlroots() -> bool:
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    return any(name in desktop for name in ("sway", "hyprland", "river", "wayfire", "labwc", "niri"))


def available_backends() -> list[str]:
    out = []
    if portal.available():
        out.append("portal")
    if x11.available():
        out.append("x11")
    if grim.available():
        out.append("grim")
    out.append("pattern")
    return out


def auto_backend() -> str:
    found = available_backends()
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if wayland and _wlroots() and "grim" in found and "portal" not in found:
        return "grim"
    if wayland and "portal" in found:
        return "portal"
    if "x11" in found:
        return "x11"
    if "grim" in found:
        return "grim"
    raise CaptureError(
        "No screen capture method available. On Wayland install pipewire-gstreamer "
        "and python3-gobject; on X11 install python3-mss.")


def create(backend: str, config=None) -> CaptureBackend:
    if backend in (None, "", "auto"):
        backend = auto_backend()
    sync = config.sync if config is not None else {}
    if backend == "portal":
        def save_token(token: str) -> None:
            if config is not None:
                config.set("portal_restore_token", token)
        token = config.get("portal_restore_token", "") if config is not None else ""
        return portal.PortalCapture(restore_token=token, on_token=save_token)
    if backend == "x11":
        return x11.X11Capture(monitor=int(sync.get("monitor", 1)))
    if backend == "grim":
        return grim.GrimCapture()
    if backend == "pattern":
        return PatternCapture()
    raise CaptureError(f"Unknown capture backend {backend!r}")
