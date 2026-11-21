"""Shared GStreamer capture pipeline (used for Wayland and X11).

    <source> ! queue (keeps only the newest frame) ! videoscale lanczos
             ! 640x360 ! RGB ! appsink (keeps only the newest frame)

Two things keep the delay low: the leaky queue right after the source means
a slow moment never builds up a backlog of old frames, and the appsink only
ever hands out the most recent one. Lanczos takes every screen pixel into
account when shrinking, so fine detail doesn't make colours jump around.
"""

from __future__ import annotations

import logging
import os

import numpy as np

from goveehome.capture.base import FRAME_HEIGHT, FRAME_WIDTH, CaptureBackend, CaptureError, downscale

log = logging.getLogger(__name__)

SCALE_WIDTH = FRAME_WIDTH * 4
SCALE_HEIGHT = FRAME_HEIGHT * 4
WAIT_MS = 100      # longest wait for a new frame; a static screen sends none


def gst():
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise CaptureError("Screen capture needs PyGObject with GStreamer") from exc
    Gst.init(None)
    return Gst


def has_element(name: str) -> bool:
    try:
        return gst().ElementFactory.find(name) is not None
    except CaptureError:
        return False


def _scale_threads() -> str:
    Gst = gst()
    probe = Gst.ElementFactory.make("videoscale", None)
    if probe is not None and probe.find_property("n-threads") is not None:
        return f" n-threads={max(1, min(4, os.cpu_count() or 1))}"
    return ""


class GstCapture(CaptureBackend):
    """Subclasses provide source_description() and may override open()."""

    def __init__(self):
        self._pipeline = None
        self._sink = None
        self._last: np.ndarray | None = None
        self.last_age: float | None = None     # seconds between screen and our frame
        self.source_format: str = ""           # e.g. "1920×1080 BGRx", for diagnostics

    def source_description(self) -> str:
        raise NotImplementedError

    def source_properties(self) -> dict:
        """Optional properties of the element named "src", set only if it has them."""
        return {}

    def start_pipeline(self) -> None:
        Gst = gst()
        desc = (
            f"{self.source_description()} ! "
            "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! "
            f"videoscale method=lanczos{_scale_threads()} ! "
            f"video/x-raw,width={SCALE_WIDTH},height={SCALE_HEIGHT} ! "
            "videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        )
        try:
            self._pipeline = Gst.parse_launch(desc)
        except Exception as exc:
            raise CaptureError(f"Could not build the capture pipeline: {exc}") from exc
        src = self._pipeline.get_by_name("src")
        for key, value in self.source_properties().items():
            if src is not None and src.find_property(key) is not None:
                src.set_property(key, value)
        self._sink = self._pipeline.get_by_name("sink")
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.close()
            raise CaptureError("Could not start screen capture")

    def open(self) -> None:
        self.start_pipeline()

    def _check_bus(self) -> None:
        Gst = gst()
        msg = self._pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if msg:
            err, _debug = msg.parse_error()
            raise CaptureError(f"Screen capture stopped: {err.message}")

    def grab(self) -> np.ndarray:
        if self._pipeline is None:
            self.open()
        Gst = gst()
        sample = self._sink.emit("try-pull-sample", WAIT_MS * Gst.MSECOND)
        if sample is None:
            self._check_bus()
            return self._last if self._last is not None else np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), np.uint8)
        frame = self._to_array(sample)
        if frame is None:          # damaged / empty buffer: keep the previous picture
            return self._last if self._last is not None else np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), np.uint8)
        self._measure_age(sample)
        if not self.source_format:
            self._read_format()
        self._last = downscale(frame)
        return self._last

    def _to_array(self, sample) -> np.ndarray | None:
        buf = sample.get_buffer()
        structure = sample.get_caps().get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        size = buf.get_size()
        if not width or not height or size < width * height * 3:
            return None
        data = buf.extract_dup(0, size)
        stride = size // height
        rows = np.frombuffer(data, dtype=np.uint8)[: stride * height].reshape(height, stride)
        return rows[:, : width * 3].reshape(height, width, 3)

    def _read_format(self) -> None:
        try:
            src = self._pipeline.get_by_name("src")
            caps = src.get_static_pad("src").get_current_caps()
            st = caps.get_structure(0)
            fmt = st.get_value("format") if st.has_field("format") else st.get_name()
            self.source_format = f"{st.get_value('width')}×{st.get_value('height')} {fmt}"
            if caps.get_features(0) is not None and caps.get_features(0).to_string() != "memory:SystemMemory":
                self.source_format += f" ({caps.get_features(0).to_string()})"
        except Exception:
            self.source_format = "unknown format"

    def _measure_age(self, sample) -> None:
        try:
            Gst = gst()
            buf = sample.get_buffer()
            clock = self._pipeline.get_clock()
            if clock is None or buf.pts == Gst.CLOCK_TIME_NONE:
                return
            running = clock.get_time() - self._pipeline.get_base_time()
            age = (running - buf.pts) / Gst.SECOND
            self.last_age = age if 0 <= age < 5 else None
        except Exception:
            self.last_age = None

    def close(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(gst().State.NULL)
            self._pipeline = None
            self._sink = None
