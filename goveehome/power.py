"""Follow the computer: lights off when it sleeps or shuts down, on when it wakes.

Listens to systemd-logind on the system bus. A "delay" inhibitor gives us a
moment to send the commands before the machine actually goes down.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
MANAGER = "org.freedesktop.login1.Manager"


class PowerWatcher:
    def __init__(self, on_sleep: Callable[[], None], on_wake: Callable[[], None]):
        self.on_sleep = on_sleep
        self.on_wake = on_wake
        self._bus = None
        self._subs: list[int] = []
        self._fd: int | None = None

    def start(self) -> bool:
        try:
            from gi.repository import Gio
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except Exception as exc:
            log.warning("No system bus, can't follow sleep/shutdown: %s", exc)
            return False
        for signal in ("PrepareForSleep", "PrepareForShutdown"):
            self._subs.append(self._bus.signal_subscribe(
                LOGIN1, MANAGER, signal, LOGIN1_PATH, None, Gio.DBusSignalFlags.NONE, self._on_signal))
        self._inhibit()
        return True

    def stop(self) -> None:
        if self._bus is not None:
            for sub in self._subs:
                self._bus.signal_unsubscribe(sub)
        self._subs.clear()
        self._release()

    def _inhibit(self) -> None:
        if self._fd is not None or self._bus is None:
            return
        try:
            from gi.repository import Gio, GLib
            reply, fds = self._bus.call_with_unix_fd_list_sync(
                LOGIN1, LOGIN1_PATH, MANAGER, "Inhibit",
                GLib.Variant("(ssss)", ("sleep:shutdown", "GoveeHome", "Turning the lights off", "delay")),
                GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None)
            self._fd = fds.get(reply.unpack()[0])
        except Exception as exc:
            log.info("Could not take a sleep inhibitor: %s", exc)

    def _release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _on_signal(self, _conn, _sender, _path, _iface, signal, params, *_):
        going_down = bool(params.unpack()[0])
        if going_down:
            try:
                self.on_sleep()
            except Exception:
                log.exception("sleep handler failed")
            # UDP packets need a moment to leave before the network goes away
            threading.Timer(0.8, self._release).start()
        elif signal == "PrepareForSleep":
            self._inhibit()
            try:
                self.on_wake()
            except Exception:
                log.exception("wake handler failed")
