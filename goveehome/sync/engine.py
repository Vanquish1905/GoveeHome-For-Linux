"""The screen sync loop: capture -> zones -> colours -> lights."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from goveehome import capture
from goveehome.capture import CaptureError
from goveehome.manager import DeviceManager
from goveehome.models import Device
from goveehome.sync import colors as sc
from goveehome.sync.zones import Rect, layout_rects

log = logging.getLogger(__name__)

PREVIEW_INTERVAL = 1 / 12   # how often the UI gets a frame
MAX_FPS_COLORWC = 15        # plain colour commands; lights choke beyond this
MAX_FPS_BLE = 10


@dataclass
class Target:
    device: Device
    settings: dict
    rects: list[Rect]
    smoother: sc.Smoother
    last_sent: float = 0.0
    last_colors: list = field(default_factory=list)


@dataclass
class Preview:
    frame: np.ndarray
    targets: dict[str, tuple[list[Rect], list[tuple[int, int, int]]]]
    fps: float
    backend: str


class SyncEngine:
    def __init__(self, manager: DeviceManager,
                 on_preview: Callable[[Preview], None] | None = None,
                 on_state: Callable[[bool, str | None], None] | None = None,
                 backend_factory: Callable[[str], capture.CaptureBackend] | None = None):
        self.manager = manager
        self.config = manager.config
        self.on_preview = on_preview
        self.on_state = on_state
        self._factory = backend_factory or (lambda name: capture.create(name, self.config))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self.device_ids: list[str] | None = None   # None = every device with sync enabled
        self.backend_name = ""
        self.fps = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, device_ids: list[str] | None = None) -> None:
        if self.running:
            return
        self.device_ids = device_ids
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="govee-sync", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def reload(self) -> None:
        """Pick up changed device settings (layout, segments, ...) on the next frame."""
        self._reload.set()

    # internals -----------------------------------------------------------------
    def _targets(self) -> list[Target]:
        out = []
        depth = float(self.config.sync.get("edge_depth", 0.18))
        smoothing = float(self.config.sync.get("smoothing", 0.5))
        for device in self.manager.list():
            if not device.can_stream:
                continue
            settings = self.manager.stream_settings(device)
            if self.device_ids is not None:
                if device.id not in self.device_ids:
                    continue
            elif not settings.get("sync", True):
                continue
            rects = layout_rects(settings["layout"], settings["segments"], depth, settings["reverse"])
            out.append(Target(device, settings, rects, sc.Smoother(smoothing)))
        return out

    def _notify(self, running: bool, message: str | None = None) -> None:
        if self.on_state:
            try:
                self.on_state(running, message)
            except Exception:
                log.exception("on_state failed")

    def _run(self) -> None:
        name = self.config.sync.get("backend", "auto")
        try:
            backend = self._factory(name)
            self.backend_name = backend.label
            backend.open()
        except CaptureError as exc:
            self._notify(False, str(exc))
            return
        targets = self._targets()
        if not targets:
            backend.close()
            self._notify(False, "No lights selected for screen sync. Lights need LAN control "
                                "or Bluetooth; cloud-only lights are too slow.")
            return
        self._notify(True, None)
        error: str | None = None
        last_preview = 0.0
        frame_times: list[float] = []
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                sync = self.config.sync
                fps = max(1, min(60, int(sync.get("fps", 20))))
                if self._reload.is_set():
                    self._reload.clear()
                    for t in targets:
                        self.manager.stream_stop(t.device, restore=False)
                    targets = self._targets()
                frame = backend.grab()
                self._process(frame, targets, sync, started)
                frame_times.append(started)
                frame_times = [t for t in frame_times if started - t < 2.0]
                self.fps = (len(frame_times) - 1) / max(1e-3, started - frame_times[0]) if len(frame_times) > 1 else 0.0
                if self.on_preview and started - last_preview >= PREVIEW_INTERVAL:
                    last_preview = started
                    self.on_preview(Preview(
                        frame=frame,
                        targets={t.device.id: (t.rects, t.last_colors) for t in targets},
                        fps=self.fps,
                        backend=self.backend_name,
                    ))
                delay = 1.0 / fps - (time.monotonic() - started)
                if delay > 0:
                    self._stop.wait(delay)
        except CaptureError as exc:
            error = str(exc)
        except Exception as exc:  # keep the lights in a sane state whatever happens
            log.exception("sync loop crashed")
            error = f"Screen sync stopped: {exc}"
        finally:
            restore = bool(self.config.sync.get("restore_on_stop", True))
            for t in targets:
                self.manager.stream_stop(t.device, restore=restore)
            backend.close()
            self.fps = 0.0
            self._notify(False, error)

    def _process(self, frame: np.ndarray, targets: list[Target], sync: dict, now: float) -> None:
        mode = sync.get("mode", "vivid")
        saturation = float(sync.get("saturation", 1.3))
        brightness = float(sync.get("brightness", 1.0))
        black = float(sync.get("black_level", 6))
        smoothing = float(sync.get("smoothing", 0.5))
        for t in targets:
            t.smoother.smoothing = smoothing
            raw = sc.extract(frame, t.rects, mode)
            adjusted = sc.adjust(raw, saturation, brightness, black)
            smoothed = t.smoother(adjusted)
            colors = sc.to_rgb_list(smoothed)
            limit = None
            if not t.settings["streaming"]:
                limit = MAX_FPS_BLE if not t.device.ip else MAX_FPS_COLORWC
            if limit and now - t.last_sent < 1.0 / limit:
                continue
            # skip identical frames but still send now and then so the light
            # doesn't time out of streaming mode
            if colors == t.last_colors and now - t.last_sent < 1.0:
                continue
            t.last_sent = now
            t.last_colors = colors
            self.manager.stream(t.device, colors, t.settings)
