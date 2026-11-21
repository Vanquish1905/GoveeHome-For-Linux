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


from goveehome.capture.base import CaptureError
from goveehome.capture.gst import GstCapture, has_element

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


class PortalCapture(GstCapture):
    id = "portal"
    label = "Screen share portal (Wayland)"

    def __init__(self, restore_token: str = "", on_token: Callable[[str], None] | None = None):
        super().__init__()
        self._node = 0
        self.restore_token = restore_token
        self.on_token = on_token
        self._bus = None
        self._session: str | None = None
        self._fd: int | None = None

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
    def source_description(self) -> str:
        return f"pipewiresrc name=src fd={self._fd} path={self._node} do-timestamp=true"

    def source_properties(self) -> dict:
        # hand buffers back to the compositor at once so it never has to wait
        # for us, and repeat the last frame while the screen doesn't change
        return {"always-copy": True, "keepalive-time": 500}

    def open(self) -> None:
        if not has_element("pipewiresrc"):
            raise CaptureError("GStreamer PipeWire plugin missing (install pipewire-gstreamer)")
        self._fd, self._node = self._negotiate()
        self.start_pipeline()

    def close(self) -> None:
        super().close()
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
