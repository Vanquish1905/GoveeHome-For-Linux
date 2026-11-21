"""Music sync: lights react to whatever the PC is playing.

Audio comes from the monitor of the default output (what you hear), through
GStreamer's PulseAudio source, which PipeWire provides on current desktops.
No microphone involved, so it works with headphones too.
"""

from __future__ import annotations

import collections
import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from goveehome.sync.effects import hsv, palette
from goveehome.sync.engine import Source, SourceError

log = logging.getLogger(__name__)

RATE = 44100

MODES = {
    "spectrum": "Spectrum",
    "energy": "Energy",
    "pulse": "Beat pulse",
    "rolling": "Rolling",
}

PALETTES: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "rainbow": lambda u: hsv(u, 1.0, 1.0),
    "warm": lambda u: palette([(255, 0, 0), (255, 90, 0), (255, 200, 0), (255, 0, 90)], u),
    "cool": lambda u: palette([(0, 80, 255), (0, 220, 255), (120, 0, 255), (0, 255, 160)], u),
    "neon": lambda u: palette([(255, 0, 200), (0, 255, 240), (180, 255, 0), (120, 0, 255)], u),
    "fire": lambda u: palette([(255, 20, 0), (255, 120, 0), (255, 200, 40)], u),
}
PALETTE_LABELS = {"rainbow": "Rainbow", "warm": "Warm", "cool": "Cool", "neon": "Neon", "fire": "Fire"}


class AudioCapture:
    """Reads mono float samples from the desktop's audio output."""

    label = "System audio"

    def __init__(self, device: str = "@DEFAULT_MONITOR@"):
        self.device = device
        self._pipeline = None
        self._sink = None

    def open(self) -> None:
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise SourceError("Music sync needs PyGObject and GStreamer") from exc
        Gst.init(None)
        if Gst.ElementFactory.find("pulsesrc") is None:
            raise SourceError("Music sync needs the GStreamer PulseAudio plugin "
                              "(Fedora: gstreamer1-plugins-good)")
        desc = (
            f'pulsesrc device="{self.device}" client-name=GoveeHome buffer-time=40000 latency-time=10000 ! '
            f"audioconvert ! audioresample ! audio/x-raw,format=F32LE,channels=1,rate={RATE} ! "
            f"appsink name=sink max-buffers=64 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(desc)
        self._sink = self._pipeline.get_by_name("sink")
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.close()
            raise SourceError("Could not open the audio output for recording")

    def read(self) -> np.ndarray:
        from gi.repository import Gst
        chunks = []
        timeout = 30 * Gst.MSECOND
        while True:
            sample = self._sink.emit("try-pull-sample", timeout)
            if sample is None:
                break
            buf = sample.get_buffer()
            chunks.append(np.frombuffer(buf.extract_dup(0, buf.get_size()), dtype=np.float32))
            timeout = 0
        if not chunks:
            bus = self._pipeline.get_bus()
            msg = bus.pop_filtered(Gst.MessageType.ERROR)
            if msg:
                err, _ = msg.parse_error()
                raise SourceError(f"Audio capture failed: {err.message}")
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def close(self) -> None:
        if self._pipeline is not None:
            from gi.repository import Gst
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None


@dataclass
class Analysis:
    bands: np.ndarray       # 0..1 per band, low to high frequencies
    level: float            # 0..1 overall loudness
    beat: bool
    centroid: float         # 0..1, where the energy sits in the spectrum


class Analyzer:
    def __init__(self, rate: int = RATE, size: int = 2048, bands: int = 24):
        self.rate = rate
        self.size = size
        self.buffer = np.zeros(size, dtype=np.float32)
        self.window = np.hanning(size).astype(np.float32)
        freqs = np.fft.rfftfreq(size, 1 / rate)
        edges = np.geomspace(40, 12000, bands + 1)
        self.band_bins = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            idx = np.nonzero((freqs >= lo) & (freqs < hi))[0]
            if len(idx) == 0:
                idx = np.array([int(np.argmin(np.abs(freqs - (lo + hi) / 2)))])
            self.band_bins.append(idx)
        self.peak = np.full(bands, 0.5, dtype=np.float32)
        self.level_peak = 0.02
        self.bass_history: collections.deque = collections.deque(maxlen=40)
        self.last_beat = -1.0

    def feed(self, samples: np.ndarray) -> None:
        n = len(samples)
        if n == 0:
            return
        if n >= self.size:
            self.buffer[:] = samples[-self.size:]
        else:
            self.buffer = np.roll(self.buffer, -n)
            self.buffer[-n:] = samples

    def analyze(self, now: float, sensitivity: float = 1.0) -> Analysis:
        spectrum = np.abs(np.fft.rfft(self.buffer * self.window))
        energy = np.array([np.sqrt(np.mean(spectrum[b] ** 2)) for b in self.band_bins], dtype=np.float32)
        loud = np.log1p(energy)
        # automatic gain per band: follow the loudest recent value, slowly forget it
        self.peak = np.maximum(self.peak * 0.995, np.maximum(loud, 0.5))
        # half per band, half overall: every band gets used, but a band that only
        # ever holds a whisper doesn't light up as much as the loud ones
        reference = 0.5 * self.peak + 0.5 * float(self.peak.max())
        bands = np.clip(loud / reference * sensitivity, 0, 1) ** 1.6
        rms = float(np.sqrt(np.mean(self.buffer ** 2)))
        self.level_peak = max(self.level_peak * 0.997, rms, 0.02)
        level = float(np.clip(rms / self.level_peak * sensitivity, 0, 1))
        if rms < 1e-4:
            bands[:] = 0
            level = 0.0
        bass = float(loud[:3].mean())
        avg = float(np.mean(self.bass_history)) if self.bass_history else bass
        beat = (len(self.bass_history) > 8 and bass > avg * 1.25 + 0.15 and level > 0.08
                and now - self.last_beat > 0.18)
        if beat:
            self.last_beat = now
        self.bass_history.append(bass)
        total = float(bands.sum())
        centroid = float((bands * np.arange(len(bands))).sum() / total / (len(bands) - 1)) if total > 0 else 0.0
        return Analysis(bands, level, beat, centroid)


class MusicSource(Source):
    kind = "music"

    def __init__(self, config, audio_factory: Callable[[], object] | None = None):
        self.config = config
        self._audio_factory = audio_factory or AudioCapture
        self.audio = None
        self.analyzer = Analyzer()
        self._last = 0.0
        self._phase = 0.0
        self._pulse_u = 0.0
        self._pulse_env = 0.0
        self._roll = np.zeros((64, 3), dtype=np.float32)
        self._frame: np.ndarray | None = None
        self.analysis: Analysis | None = None

    @property
    def section(self) -> dict:
        return self.config.section("music")

    def open(self) -> None:
        self.audio = self._audio_factory()
        self.audio.open()
        self.label = getattr(self.audio, "label", "System audio")

    def close(self) -> None:
        if self.audio is not None:
            self.audio.close()

    def fps(self) -> int:
        return int(self.section.get("fps", 40))

    def smoothing(self) -> float:
        return 0.03

    def render(self, targets, now):
        s = self.section
        self.analyzer.feed(self.audio.read())
        a = self.analyzer.analyze(now, float(s.get("sensitivity", 1.0)))
        self.analysis = a
        dt = min(0.2, now - self._last) if self._last else 0.0
        self._last = now
        pal = PALETTES.get(s.get("palette", "rainbow"), PALETTES["rainbow"])
        mode = s.get("mode", "spectrum")
        brightness = float(s.get("brightness", 1.0))

        self._phase = (self._phase + dt * (0.02 + 0.08 * a.level) + (0.13 if a.beat else 0.0)) % 1.0
        if a.beat:
            self._pulse_u = (self._pulse_u + 0.29) % 1.0
            self._pulse_env = 1.0
        else:
            self._pulse_env *= float(np.exp(-dt / 0.25)) if dt else 1.0
        if mode == "rolling":
            shift = 1 + int(a.level * 3)
            self._roll = np.roll(self._roll, shift, axis=0)
            fresh = pal(np.array([self._phase + a.centroid * 0.5]))[0] * (0.1 + 0.9 * a.level)
            if a.beat:
                fresh = pal(np.array([self._pulse_u]))[0]
            self._roll[:shift] = fresh

        out = {}
        nb = len(a.bands)
        for t in targets:
            x = t.positions
            if mode == "spectrum":
                if len(x) > 1:
                    v = np.interp(x * (nb - 1), np.arange(nb), a.bands)
                    col = pal(x * 0.85 + self._phase * 0.2) * v[:, None]
                else:
                    col = pal(np.array([a.centroid * 0.85 + self._phase * 0.2])) * a.level
            elif mode == "energy":
                col = pal(self._phase + x * 0.3) * (0.12 + 0.88 * a.level)
            elif mode == "pulse":
                col = pal(np.full_like(x, self._pulse_u) + x * 0.1) * max(0.05, self._pulse_env)
            else:  # rolling
                idx = np.clip((x * (len(self._roll) / 3 - 1)).astype(int), 0, len(self._roll) - 1)
                col = self._roll[idx]
            out[t.device.id] = np.clip(col * brightness, 0, 255)
        self._frame = self._draw(a, pal)
        return out

    def _draw(self, a: Analysis, pal) -> np.ndarray:
        h, w = 90, 160
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        nb = len(a.bands)
        col_w = w // nb
        colors = pal(np.arange(nb) / nb * 0.85 + self._phase * 0.2)
        for i, v in enumerate(a.bands):
            top = h - int(v * (h - 4))
            frame[top:, i * col_w + 1:(i + 1) * col_w - 1] = colors[i].astype(np.uint8)
        return frame

    def preview(self):
        return self._frame
