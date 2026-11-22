"""Check that the screen capture delivers the colours that are really on screen.

Some compositors hand out frames whose colour channels are in a different
order than they claim. KWin (KDE Plasma) has had bugs where red and blue
come out swapped. Then a red film scene turns the lights blue and screen
sync never matches the screen, while effects look fine.

The check shows pure red, green and blue on the screen for a moment each,
captures them and sees which channel each one comes back in. If they come
back in a different order, the order to put them right is saved and screen
sync applies it to every frame.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

PRIMARIES = [("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))]
NORMAL = (0, 1, 2)
ORDER_NAMES = {
    (0, 1, 2): "as delivered",
    (2, 1, 0): "red and blue swapped",
    (1, 0, 2): "red and green swapped",
    (0, 2, 1): "green and blue swapped",
    (1, 2, 0): "channels rotated",
    (2, 0, 1): "channels rotated",
}


def centre(frame: np.ndarray, share: float = 0.5) -> np.ndarray:
    h, w = frame.shape[:2]
    dy, dx = int(h * (1 - share) / 2), int(w * (1 - share) / 2)
    return frame[dy:h - dy, dx:w - dx].reshape(-1, 3).astype(np.float32).mean(axis=0)


def best_order(measured: dict[str, np.ndarray]) -> tuple[tuple[int, int, int] | None, str]:
    """From the captured red, green and blue, work out the channel order.

    Returns (order, message). order[c] is the captured channel that holds
    the real channel c; None if the result isn't clear (for example the
    colours were shown on a screen that isn't the shared one).
    """
    order = []
    for name, _expected in PRIMARIES:
        got = np.asarray(measured.get(name, (0, 0, 0)), dtype=np.float32)
        strongest = int(got.argmax())
        others = np.delete(got, strongest)
        if got[strongest] < 60 or got[strongest] < 1.6 * max(others.max(), 1):
            return None, (f"The {name} test came back as {tuple(int(v) for v in got)}, which isn't clear. "
                          "Make sure the colours are shown on the screen you share for screen sync.")
        order.append(strongest)
    if sorted(order) != [0, 1, 2]:
        return None, "Two test colours came back as the same colour; the capture can't be corrected this way."
    order_t = tuple(order)
    return order_t, ORDER_NAMES.get(order_t, "reordered")


def apply_order(frame: np.ndarray, order) -> np.ndarray:
    if order is None or tuple(order) == NORMAL:
        return frame
    return frame[..., list(order)]


def measure(backend, show: Callable[[tuple | None], None], settle: float = 1.0,
            log: Callable[[str], None] = lambda s: None) -> dict[str, np.ndarray]:
    """Show each primary with show(rgb), capture it, return what came back."""
    results: dict[str, np.ndarray] = {}
    for name, rgb in PRIMARIES:
        show(rgb)
        end = time.monotonic() + settle
        frame = None
        while time.monotonic() < end:
            frame = backend.grab()
        for _ in range(3):
            frame = backend.grab()
        results[name] = centre(frame)
        log(f"{name:5s} on screen -> captured {tuple(int(v) for v in results[name])}")
    show(None)
    return results


class ColourWindow:
    """A fullscreen window in one colour. Must be used from the GTK main thread."""

    def __init__(self):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gtk
        self.rgb = (0, 0, 0)
        self.window = Gtk.Window(title="GoveeHome colour check", decorated=False)
        # fill the screen even where fullscreen isn't honoured
        try:
            monitors = Gdk.Display.get_default().get_monitors()
            geo = monitors.get_item(0).get_geometry()
            self.window.set_default_size(geo.width, geo.height)
        except Exception:
            self.window.set_default_size(1920, 1080)
        area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        area.set_draw_func(self._draw)
        self.area = area
        self.window.set_child(area)
        self.window.fullscreen()
        self.window.present()

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(*(c / 255 for c in self.rgb))
        cr.paint()

    def set(self, rgb):
        self.rgb = rgb
        self.area.queue_draw()

    def close(self):
        self.window.close()


def run_check(open_backend: Callable[[], object], on_log: Callable[[str], None],
              on_done: Callable[[tuple | None, str, dict], None]) -> None:
    """Run the whole check from the GTK main thread; results come back via on_done (main thread)."""
    from gi.repository import GLib
    win = ColourWindow()

    def show(rgb):
        done = threading.Event()

        def apply():
            if rgb is None:
                win.close()
            else:
                win.set(rgb)
            done.set()
            return False
        GLib.idle_add(apply)
        done.wait(2)

    def work():
        backend = None
        try:
            time.sleep(1.0)                 # let the window go fullscreen
            backend = open_backend()
            measured = measure(backend, show, log=lambda s: GLib.idle_add(on_log, s))
            order, message = best_order(measured)
        except Exception as exc:            # capture could not start etc.
            show(None)
            order, message, measured = None, f"The check could not run: {exc}", {}
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
        GLib.idle_add(on_done, order, message, measured)

    threading.Thread(target=work, name="govee-colour-check", daemon=True).start()
