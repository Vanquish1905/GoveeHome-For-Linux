"""Wayland screen capture via xdg-desktop-portal + PipeWire + GStreamer.

This is the path that works on GNOME and KDE Plasma under Wayland (Fedora's
default). The first start shows the desktop's "share your screen" dialog.
We ask the portal to remember the choice (persist_mode = 2) and keep the
restore token in the config, so later starts are silent on desktops that
support it.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable

import numpy as np

from goveehome.capture.base import FRAME_HEIGHT, FRAME_WIDTH, CaptureBackend, CaptureError, downscale

# Plain bilinear scaling straight to 160x90 samples about 1% of a 4K screen
# and gives noisy, wrong colours. Lanczos takes every pixel into account when
# shrinking; it goes to 4x the target and the last step is an exact average.
SCALE_WIDTH = FRAME_WIDTH * 4
SCALE_HEIGHT = FRAME_HEIGHT * 4

log = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"

SOURCE_MONITOR = 1
PERSIST_UNTIL_REVOKED = 2
DIALOG_TIMEOUT = 180  # seconds the user gets to answer the share dialog


def _gi():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gio, GLib, Gst
    return Gio, GLib, Gst


def available() -> bool:
    wayland = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland"
    if not wayland:
        return False
    try:
        _, _, Gst = _gi()
        Gst.init(None)
        return Gst.ElementFactory.find("pipewiresrc") is not None
    except (ImportError, ValueError):
        return False


class PortalCapture(CaptureBackend):
    id = "portal"
    label = "Screen share portal (Wayland)"

    def __init__(self, restore_token: str = "", on_token: Callable[[str], None] | None = None):
        self.restore_token = restore_token
        self.on_token = on_token
        self._bus = None
        self._session: str | None = None
        self._pipeline = None
        self._sink = None
        self._fd: int | None = None
        self._last: np.ndarray | None = None

    # portal plumbing -----------------------------------------------------------
    def _request(self, ctx, method: str, signature: str, args: tuple, options: dict) -> dict:
        Gio, GLib, _ = _gi()
        token = "goveehome_" + uuid.uuid4().hex[:10]
        sender = self._bus.get_unique_name()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        answer: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params, *_):
            code, results = params.unpack()
            answer["code"] = code
            answer["results"] = results

        # Subscribe before calling so a fast answer can't be missed. The request
        # path is unique to this call, so no sender filter is needed.
        sub = self._bus.signal_subscribe(None, REQUEST, "Response", path, None,
                                         Gio.DBusSignalFlags.NONE, on_response)
        try:
            opts = {"handle_token": GLib.Variant("s", token), **options}
            params = GLib.Variant(signature, (*args, opts))
            self._bus.call_sync(PORTAL_BUS, PORTAL_PATH, SCREENCAST, method, params,
                                None, Gio.DBusCallFlags.NONE, -1, None)
            deadline = time.monotonic() + DIALOG_TIMEOUT
            while "code" not in answer:
                if time.monotonic() > deadline:
                    raise CaptureError("No answer from the screen share dialog")
                if not ctx.iteration(False):
                    time.sleep(0.02)
        except GLib.Error as exc:
            raise CaptureError(f"Screen share portal error: {exc.message}") from exc
        finally:
            self._bus.signal_unsubscribe(sub)
        if answer["code"] == 1:
            raise CaptureError("Screen sharing was cancelled")
        if answer["code"] != 0:
            raise CaptureError("The screen share portal refused the request")
        return answer["results"]

    def _negotiate(self) -> tuple[int, int]:
        Gio, GLib, _ = _gi()
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            res = self._request(ctx, "CreateSession", "(a{sv})", (), {
                "session_handle_token": GLib.Variant("s", "goveehome_" + uuid.uuid4().hex[:10]),
            })
            self._session = res["session_handle"]
            select = {
                "types": GLib.Variant("u", SOURCE_MONITOR),
                "multiple": GLib.Variant("b", False),
                "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
            }
            if self.restore_token:
                select["restore_token"] = GLib.Variant("s", self.restore_token)
            self._request(ctx, "SelectSources", "(oa{sv})", (self._session,), select)
            res = self._request(ctx, "Start", "(osa{sv})", (self._session, ""), {})
            streams = res.get("streams") or []
            if not streams:
                raise CaptureError("No screen was shared")
            node_id = streams[0][0]
            token = res.get("restore_token")
            if token and token != self.restore_token:
                self.restore_token = token
                if self.on_token:
                    self.on_token(token)
            reply, fds = self._bus.call_with_unix_fd_list_sync(
                PORTAL_BUS, PORTAL_PATH, SCREENCAST, "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (self._session, {})), GLib.VariantType("(h)"),
                Gio.DBusCallFlags.NONE, -1, None, None)
            fd = fds.get(reply.unpack()[0])
            return fd, node_id
        except GLib.Error as exc:
            raise CaptureError(f"Screen share portal error: {exc.message}") from exc
        finally:
            ctx.pop_thread_default()

    # backend API -----------------------------------------------------------------
    def open(self) -> None:
        try:
            _, _, Gst = _gi()
        except (ImportError, ValueError) as exc:
            raise CaptureError("Wayland capture needs PyGObject and GStreamer") from exc
        Gst.init(None)
        if Gst.ElementFactory.find("pipewiresrc") is None:
            raise CaptureError("GStreamer PipeWire plugin missing (install pipewire-gstreamer)")
        self._fd, node_id = self._negotiate()
        desc = (
            f"pipewiresrc name=src fd={self._fd} path={node_id} do-timestamp=true ! "
            f"videoscale method=lanczos ! video/x-raw,width={SCALE_WIDTH},height={SCALE_HEIGHT} ! "
            f"videoconvert ! video/x-raw,format=RGB ! "
            f"appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(desc)
        src = self._pipeline.get_by_name("src")
        if src is not None and src.find_property("keepalive-time"):
            src.set_property("keepalive-time", 500)
        self._sink = self._pipeline.get_by_name("sink")
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.close()
            raise CaptureError("Could not start the PipeWire stream")

    def _check_bus(self) -> None:
        _, _, Gst = _gi()
        bus = self._pipeline.get_bus()
        msg = bus.pop_filtered(Gst.MessageType.ERROR)
        if msg:
            err, _debug = msg.parse_error()
            raise CaptureError(f"PipeWire stream error: {err.message}")

    def grab(self) -> np.ndarray:
        if self._pipeline is None:
            self.open()
        _, _, Gst = _gi()
        # PipeWire only delivers frames when the screen changes, so a static
        # desktop simply keeps the last frame.
        sample = self._sink.emit("try-pull-sample", 100 * Gst.MSECOND)
        if sample is None:
            self._check_bus()
            if self._last is None:
                return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
            return self._last
        buf = sample.get_buffer()
        structure = sample.get_caps().get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        data = buf.extract_dup(0, buf.get_size())
        stride = len(data) // height
        rows = np.frombuffer(data, dtype=np.uint8).reshape(height, stride)
        self._last = downscale(rows[:, : width * 3].reshape(height, width, 3))
        return self._last

    def close(self) -> None:
        if self._pipeline is not None:
            _, _, Gst = _gi()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._sink = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._session and self._bus is not None:
            try:
                Gio, GLib, _ = _gi()
                self._bus.call_sync(PORTAL_BUS, self._session, SESSION, "Close", None,
                                    None, Gio.DBusCallFlags.NONE, -1, None)
            except Exception:
                pass
            self._session = None
