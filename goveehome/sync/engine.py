"""The light show loop: a source renders colours, the engine sends them.

Sources are the screen (screen sync), the sound card (music sync) and the
built-in effects. They all produce sRGB colours per light and segment; the
engine takes care of smoothing, gamma / white balance, rate limits per
transport, previews and putting the lights back when it stops. Only one
engine runs at a time.
"""

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
from goveehome.sync.content import ContentTracker
from goveehome.sync.letterbox import BarDetector, crop, map_rect
from goveehome.sync.zones import Rect, layout_rects

log = logging.getLogger(__name__)

PREVIEW_INTERVAL = 1 / 15   # how often the UI gets a frame
MAX_FPS_COLORWC = 15        # plain colour commands; lights choke beyond this
MAX_FPS_BLE = 10
KEEPALIVE = 1.0             # resend unchanged colours this often


class SourceError(Exception):
    pass


@dataclass
class Target:
    device: Device
    settings: dict
    rects: list[Rect]
    positions: np.ndarray            # 0..1 along the light, already reversed if needed
    smoother: sc.Smoother
    gains: tuple[float, float, float] = (1.0, 1.0, 1.0)
    last_sent: float = 0.0
    last_colors: list = field(default_factory=list)
    display: list = field(default_factory=list)   # what the preview shows

    @property
    def segments(self) -> int:
        return len(self.rects)


@dataclass
class Preview:
    frame: np.ndarray | None
    targets: dict[str, tuple[list[Rect], list[tuple[int, int, int]]]]
    fps: float
    backend: str
    delay: float | None = None     # seconds from screen to light, screen sync only
    details: str = ""              # diagnostics for the status area


class Source:
    kind = "sync"        # device setting that decides whether a light joins in
    label = ""

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def fps(self) -> int:
        return 30

    def smoothing(self) -> float:
        return 0.0

    def render(self, targets: list[Target], now: float) -> dict[str, np.ndarray]:
        raise NotImplementedError

    def preview(self) -> np.ndarray | None:
        return None

    def preview_rects(self, target: Target) -> list[Rect]:
        return []


class ScreenSource(Source):
    kind = "sync"

    def __init__(self, config, backend_factory: Callable[[str], capture.CaptureBackend] | None = None):
        self.config = config
        self._factory = backend_factory or (lambda name: capture.create(name, config))
        self.backend: capture.CaptureBackend | None = None
        self.detector = BarDetector()
        self.tracker = ContentTracker()
        self.box = (0, 0, 0, 0)
        self.frame: np.ndarray | None = None
        self._black_run = 0
        self.details = ""
        self.grabbed_at: float | None = None
        self.capture_age: float | None = None

    def open(self) -> None:
        self.backend = self._factory(self.config.sync.get("backend", "auto"))
        self.label = self.backend.label
        self.backend.open()

    def close(self) -> None:
        if self.backend:
            self.backend.close()

    def fps(self) -> int:
        return int(self.config.sync.get("fps", 30))

    def smoothing(self) -> float:
        return float(self.config.sync.get("smoothing", 0.04))

    BLACK = 6              # a frame whose brightest pixel is below this is "black"
    BLACK_CONFIRM = 3      # black frames needed in a row before we believe them

    def render(self, targets, now):
        frame = self.backend.grab()
        self.grabbed_at = time.monotonic()
        self.capture_age = getattr(self.backend, "last_age", None)
        # Capture sometimes hands out a single empty (black) frame, e.g. when
        # the compositor reallocates buffers. Passing it on makes every light
        # flash off for a moment, so a black frame only counts once it lasts.
        if int(frame.max()) < self.BLACK:
            self._black_run += 1
            if self._black_run < self.BLACK_CONFIRM and self.frame is not None:
                frame = self.frame
        else:
            self._black_run = 0
        self.frame = frame
        self._describe(frame)
        sync = self.config.sync
        bars = self.detector(frame) if sync.get("letterbox", True) else (0, 0, 0, 0)
        video = self.tracker(frame) if sync.get("follow_video", True) else (0, 0, 0, 0)
        # the moving picture wins (video in a window, game); otherwise black bars
        self.box = video if video != (0, 0, 0, 0) else bars
        work = crop(frame, self.box)
        analyzer = sc.FrameAnalyzer(work)
        mode = sync.get("mode", "accurate")
        saturation = float(sync.get("saturation", 1.15))
        brightness = float(sync.get("brightness", 1.0))
        black = float(sync.get("black_level", 8))
        return {t.device.id: sc.adjust(analyzer.zones(t.rects, mode), saturation, brightness, black)
                for t in targets}

    def _describe(self, frame: np.ndarray) -> None:
        """A line for the status area: what we capture and how colourful it is."""
        px = frame.reshape(-1, 3).astype(np.float32)
        mx = px.max(axis=1)
        sat = (mx - px.min(axis=1)) / np.maximum(mx, 1.0)
        colour = float(((sat > 0.25) & (mx > 30)).mean())
        fmt = getattr(self.backend, "source_format", "") or ""
        parts = [f"Picture: {fmt}" if fmt else "Picture"]
        parts.append(f"{colour * 100:.0f} % of it is colourful")
        if self.box != (0, 0, 0, 0):
            parts.append("following the video")
        self.details = ", ".join(parts)

    def preview(self):
        return self.frame

    def preview_rects(self, target):
        if self.frame is None or self.box == (0, 0, 0, 0):
            return target.rects
        return [map_rect(r, self.box, self.frame.shape) for r in target.rects]


class LightEngine:
    def __init__(self, manager: DeviceManager, source_factory: Callable[[], Source],
                 on_preview: Callable[[Preview], None] | None = None,
                 on_state: Callable[[bool, str | None], None] | None = None,
                 kind: str = "sync"):
        self.manager = manager
        self.config = manager.config
        self.source_factory = source_factory
        self.on_preview = on_preview
        self.on_state = on_state
        self.kind = kind
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self.device_ids: list[str] | None = None   # None = every light that has this show enabled
        self.backend_name = ""
        self.fps = 0.0
        self.delay: float | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, device_ids: list[str] | None = None) -> None:
        if self.running:
            return
        other = getattr(self.manager, "active_engine", None)
        if other is not None and other is not self and other.running:
            other.stop(wait=True)
        self.manager.active_engine = self
        self.device_ids = device_ids
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"govee-{self.kind}", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def reload(self) -> None:
        """Pick up changed light settings (layout, segments, ...) on the next frame."""
        self._reload.set()

    # internals -----------------------------------------------------------------
    def _targets(self, kind: str) -> list[Target]:
        out = []
        depth = float(self.config.sync.get("edge_depth", 0.25))
        for device in self.manager.list():
            if not device.can_stream:
                continue
            settings = self.manager.stream_settings(device)
            if self.device_ids is not None:
                if device.id not in self.device_ids:
                    continue
            elif not settings.get(kind, True):
                continue
            rects = layout_rects(settings["layout"], settings["segments"], depth, settings["reverse"])
            # effects and music draw along the light: one position per colour it can show
            n = len(rects) if settings["streaming"] else 1
            positions = np.linspace(0.0, 1.0, n) if n > 1 else np.array([0.5])
            if settings["reverse"]:
                positions = positions[::-1].copy()
            gains = tuple(float(g) for g in (settings.get("gains") or (1, 1, 1))[:3])
            out.append(Target(device, settings, rects, positions, sc.Smoother(), gains))
        return out

    def _notify(self, running: bool, message: str | None = None) -> None:
        if self.on_state:
            try:
                self.on_state(running, message)
            except Exception:
                log.exception("on_state failed")

    def _run(self) -> None:
        try:
            source = self.source_factory()
            source.open()
        except (CaptureError, SourceError) as exc:
            self._notify(False, str(exc))
            return
        except Exception as exc:
            log.exception("could not start %s", self.kind)
            self._notify(False, f"Could not start: {exc}")
            return
        self.backend_name = source.label
        self.delay = None
        targets = self._targets(source.kind)
        if not targets:
            source.close()
            self._notify(False, "No lights selected. Lights need LAN control or Bluetooth for "
                                "light shows; cloud-only lights are too slow.")
            return
        self._notify(True, None)
        error: str | None = None
        last_preview = 0.0
        frame_times: list[float] = []
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                if self._reload.is_set():
                    self._reload.clear()
                    for t in targets:
                        self.manager.stream_stop(t.device, restore=False)
                    targets = self._targets(source.kind)
                outputs = source.render(targets, started)
                now = time.monotonic()
                self._send(targets, outputs, source, now)
                grabbed = getattr(source, "grabbed_at", None)
                if grabbed is not None:
                    delay = time.monotonic() - grabbed + (getattr(source, "capture_age", None) or 0.0)
                    self.delay = delay if self.delay is None else self.delay * 0.9 + delay * 0.1
                frame_times.append(now)
                while frame_times and now - frame_times[0] > 2.0:
                    frame_times.pop(0)
                if len(frame_times) > 1:
                    self.fps = (len(frame_times) - 1) / max(1e-3, frame_times[-1] - frame_times[0])
                if self.on_preview and now - last_preview >= PREVIEW_INTERVAL:
                    last_preview = now
                    self.on_preview(Preview(
                        frame=source.preview(),
                        targets={t.device.id: (source.preview_rects(t), t.display) for t in targets},
                        fps=self.fps,
                        backend=self.backend_name,
                        delay=self.delay,
                        details=getattr(source, "details", ""),
                    ))
                fps = max(1, min(60, source.fps()))
                delay = 1.0 / fps - (time.monotonic() - started)
                if delay > 0:
                    self._stop.wait(delay)
        except (CaptureError, SourceError) as exc:
            error = str(exc)
        except Exception as exc:  # keep the lights in a sane state whatever happens
            log.exception("light show crashed")
            error = f"Stopped: {exc}"
        finally:
            restore = bool(self.config.sync.get("restore_on_stop", True))
            for t in targets:
                self.manager.stream_stop(t.device, restore=restore)
            source.close()
            self.fps = 0.0
            self._notify(False, error)

    def _send(self, targets: list[Target], outputs: dict, source: Source, now: float) -> None:
        gamma = float(self.config.get("gamma", 2.0))
        tau = source.smoothing()
        for t in targets:
            colors = outputs.get(t.device.id)
            if colors is None:
                continue
            if not t.settings["streaming"] and len(colors) > 1:
                colors = sc.combine(colors)
            t.smoother.smoothing = tau
            smoothed = t.smoother(colors, now)
            t.display = sc.to_rgb_list(smoothed)
            sent = sc.to_rgb_list(sc.led_output(smoothed, gamma, t.gains))
            limit = None
            if not t.settings["streaming"]:
                limit = MAX_FPS_BLE if not t.device.ip else MAX_FPS_COLORWC
            if limit and now - t.last_sent < 1.0 / limit:
                continue
            # skip identical frames but resend now and then so the light stays in streaming mode
            if sent == t.last_colors and now - t.last_sent < KEEPALIVE:
                continue
            t.last_sent = now
            t.last_colors = sent
            self.manager.stream(t.device, sent, t.settings)


class SyncEngine(LightEngine):
    """Screen sync."""

    def __init__(self, manager: DeviceManager, on_preview=None, on_state=None,
                 backend_factory: Callable[[str], capture.CaptureBackend] | None = None):
        super().__init__(manager, lambda: ScreenSource(manager.config, backend_factory),
                         on_preview, on_state, kind="sync")
