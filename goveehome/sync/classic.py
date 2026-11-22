"""Screen sync the GoveeScreen way: one honest colour for the whole light.

A port of the frame analysis and sending logic of GoveeScreen
(https://github.com/Baba0bab/GoveeScreen, Core/FrameAnalyzer.cs and
Core/SyncEngine.cs), the Windows app this style is modelled on:

* black bars at the top and bottom are skipped,
* the light takes the **average colour** of the rest of the screen, or the
  most present vivid hue ("dominant"), which slides back to the average when
  only a little of the picture is colourful,
* the light's **brightness follows the brightness of the screen** and is
  sent as its own command, the colour itself is sent as it is,
* changes are smoothed (35 % per 33 ms), sent at most 30 times a second and
  only when they are big enough to see.

Every light gets one plain colour command, which every Govee light with LAN
control understands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from goveehome.sync.engine import Source

DARK_THRESHOLD = 22          # channel < 22/255 = dark pixel
DARK_ROW_TOLERANCE = 0.97    # a row is a black bar if >= 97 % of its pixels are dark

HUE_BINS = 36                # hues grouped in 10 degree slices
MIN_CHROMA = 32              # max - min < 32/255: grey pixel, no hue
MIN_VALUE = 40               # max < 40/255: too dark for a reliable hue
MIN_COLOR_SHARE = 0.02       # under 2 % coloured pixels: average colour
FULL_COLOR_SHARE = 0.15      # from 15 %: dominant hue only

MIN_SEND_INTERVAL = 0.033 * 0.9   # 30 per second, with GoveeScreen's 10 % pacing tolerance
COLOR_DEADBAND = 2                # per channel; smaller changes aren't visible on the lamp
SMOOTHING_ALPHA = 0.35            # per 33 ms, corrected for the real time between frames

INTENSITY = {1: 0.5, 2: 1.0, 3: 2.0, 4: None}   # 4 = always full brightness
STRENGTH_LABELS = {0: "Off (exactly like GoveeScreen)", 1: "Light", 2: "Medium", 3: "Strong", 4: "Full"}
STRENGTH_CURVE = {0: None, 1: 1.6, 2: 2.5, 3: 4.0, 4: 9.0}
NEUTRAL = 0.04       # below this saturation the screen counts as white / grey
INTENSITY_LABELS = {1: "50 %", 2: "100 %", 3: "200 %", 4: "Max"}
COLOR_MODES = {"average": "Average colour", "dominant": "Dominant colour"}


@dataclass
class FrameColor:
    r: int
    g: int
    b: int
    brightness: float          # percent, Rec. 709 luma of the average colour


def count_dark_rows(frame: np.ndarray, from_top: bool, max_rows: int) -> int:
    rows = frame if from_top else frame[::-1]
    dark = (rows < DARK_THRESHOLD).all(axis=2).mean(axis=1) >= DARK_ROW_TOLERANCE
    count = 0
    for is_dark in dark[:max_rows]:
        if not is_dark:
            break
        count += 1
    return count


def analyze(frame: np.ndarray, mode: str = "average") -> tuple[FrameColor, FrameColor]:
    """Returns (colour to send, plain average). frame is H x W x 3 RGB uint8."""
    h = frame.shape[0]
    max_bar = h // 3
    skip_top = count_dark_rows(frame, True, max_bar)
    skip_bottom = count_dark_rows(frame, False, max_bar)
    start, end = skip_top, h - skip_bottom
    if end <= start:
        black = FrameColor(0, 0, 0, 0.0)
        return black, black
    area = frame[start:end].reshape(-1, 3)
    sums = area.astype(np.int64).sum(axis=0)
    r, g, b = (int(v) for v in sums // len(area))      # integer division, as in GoveeScreen
    brightness = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0 * 100.0
    average = FrameColor(r, g, b, brightness)
    if mode != "dominant":
        return average, average
    dr, dg, db = dominant(area, (r, g, b))
    return FrameColor(dr, dg, db, brightness), average


def dominant(px: np.ndarray, average: tuple[int, int, int]) -> tuple[int, int, int]:
    """Most present vivid hue, weighted by chroma, read in windows of three neighbouring
    slices; slides towards the average when few pixels are coloured."""
    p = px.astype(np.int32)
    r, g, b = p[:, 0], p[:, 1], p[:, 2]
    mx = p.max(axis=1)
    chroma = mx - p.min(axis=1)
    keep = (chroma >= MIN_CHROMA) & (mx >= MIN_VALUE)
    colourful = int(keep.sum())
    if colourful == 0:
        return average
    r, g, b, mx, c = r[keep], g[keep], b[keep], mx[keep], chroma[keep].astype(np.float64)
    hue = np.where(mx == r, (g - b) / c, np.where(mx == g, (b - r) / c + 2, (r - g) / c + 4))
    hue = np.where(hue < 0, hue + 6, hue)
    bins = (hue * HUE_BINS / 6).astype(np.int64) % HUE_BINS
    weight = np.bincount(bins, weights=c, minlength=HUE_BINS)
    sum_r = np.bincount(bins, weights=r * c, minlength=HUE_BINS)
    sum_g = np.bincount(bins, weights=g * c, minlength=HUE_BINS)
    sum_b = np.bincount(bins, weights=b * c, minlength=HUE_BINS)
    score = np.roll(weight, 1) + weight + np.roll(weight, -1)
    best = int(score.argmax())
    window = [(best - 1) % HUE_BINS, best, (best + 1) % HUE_BINS]
    w = weight[window].sum()
    target = (sum_r[window].sum() / w, sum_g[window].sum() / w, sum_b[window].sum() / w)
    share = colourful / len(px)
    t = float(np.clip((share - MIN_COLOR_SHARE) / (FULL_COLOR_SHARE - MIN_COLOR_SHARE), 0, 1))
    return tuple(int(np.clip(round(a + (d - a) * t), 0, 255)) for a, d in zip(average, target))


def strengthen(color: FrameColor, level: int) -> FrameColor:
    """The screen's colour at full strength; its brightness is sent on its own.

    Screen averages are pale mixes, (120, 154, 141) for a nature scene, which a
    light shows as almost white. Since the brightness already travels as a
    separate command, the colour can be sent at full value: same hue, the
    saturation raised along 1 - (1 - s) ** k. Grey and white stay white.
    """
    k = STRENGTH_CURVE.get(level)
    if k is None:
        return color
    c = np.array([color.r, color.g, color.b], dtype=np.float64)
    mx, mn = c.max(), c.min()
    if mx < 6:
        return FrameColor(0, 0, 0, color.brightness)
    sat = (mx - mn) / mx
    if sat < NEUTRAL:
        return FrameColor(255, 255, 255, color.brightness)
    ramp = (sat - NEUTRAL) / (1 - NEUTRAL)
    new_sat = max(sat, 1 - (1 - ramp) ** k)
    hue_part = (c - mn) / (mx - mn)                 # 0..1 per channel, keeps the hue
    out = 255 * (1 - new_sat) + hue_part * 255 * new_sat
    r, g, b = (int(round(v)) for v in np.clip(out, 0, 255))
    return FrameColor(r, g, b, color.brightness)


def scale_brightness(percent: float, level: int) -> float:
    factor = INTENSITY.get(level, 1.0)
    if factor is None:
        return 100.0
    return float(np.clip(percent * factor, 0, 100))


class LightState:
    """Smoothing and send bookkeeping per light, as in GoveeScreen's ProcessColor()."""

    def __init__(self):
        self.ema: list[float] | None = None
        self.last_ema = 0.0
        self.last_send = -1.0
        self.sent_color: tuple[int, int, int] = (0, 0, 0)
        self.sent_brightness = -1.0
        self.shown: tuple[int, int, int] = (0, 0, 0)

    def step(self, color: FrameColor, level: int, smooth: bool, now: float):
        """Returns (colour or None, brightness or None) to send now."""
        brightness = scale_brightness(color.brightness, level)
        r, g, b = float(color.r), float(color.g), float(color.b)
        if smooth:
            if self.ema is None:
                self.ema = [r, g, b, brightness]
            else:
                dt_ms = float(np.clip((now - self.last_ema) * 1000.0, 1, 500))
                alpha = 1 - (1 - SMOOTHING_ALPHA) ** (dt_ms / 33.0)
                target = (r, g, b, brightness)
                self.ema = [e + alpha * (v - e) for e, v in zip(self.ema, target)]
            self.last_ema = now
            r, g, b, brightness = self.ema
        final = (int(round(r)), int(round(g)), int(round(b)))
        self.shown = final
        color_changed = any(abs(a - s) >= COLOR_DEADBAND for a, s in zip(final, self.sent_color))
        brightness_changed = abs(brightness - self.sent_brightness) > 1
        due = self.last_send < 0 or now - self.last_send >= MIN_SEND_INTERVAL
        if not (color_changed or brightness_changed) or not due:
            return None, None
        self.last_send = now
        send_color = final if color_changed else None
        send_brightness = None
        if color_changed:
            self.sent_color = final
        if brightness_changed:
            self.sent_brightness = brightness
            send_brightness = brightness
        return send_color, send_brightness


class ClassicScreenSource(Source):
    """Screen sync style "Whole light, like GoveeScreen"."""

    kind = "sync"
    direct = True          # sends to the lights itself; the engine only shows previews

    def __init__(self, config, manager, backend_factory=None):
        from goveehome import capture
        self.config = config
        self.manager = manager
        self._factory = backend_factory or (lambda name: capture.create(name, config))
        self.backend = None
        self.frame: np.ndarray | None = None
        self.states: dict[str, LightState] = {}
        self.details = ""
        self.grabbed_at: float | None = None
        self.capture_age: float | None = None
        self.color: FrameColor | None = None

    @property
    def options(self) -> dict:
        return self.config.sync

    def open(self) -> None:
        self.backend = self._factory(self.options.get("backend", "auto"))
        self.label = self.backend.label
        self.backend.open()

    def close(self) -> None:
        if self.backend:
            self.backend.close()

    def fps(self) -> int:
        return 30

    def render(self, targets, now):
        from goveehome.capture.calibrate import apply_order
        frame = apply_order(self.backend.grab(), self.options.get("channel_order"))
        self.grabbed_at = time.monotonic()
        self.capture_age = getattr(self.backend, "last_age", None)
        self.frame = frame
        work = frame
        panel = float(self.options.get("skip_panel", 0.035))
        if panel > 0:                      # the taskbar / panel isn't part of the picture
            work = frame[: max(1, int(round(frame.shape[0] * (1 - panel))))]
        color, average = analyze(work, self.options.get("classic_mode", "dominant"))
        color = strengthen(color, int(self.options.get("colour_strength", 3)))
        self.color = color
        level = int(self.options.get("intensity", 2))
        smooth = bool(self.options.get("smooth", True))
        out = {}
        for t in targets:
            state = self.states.setdefault(t.device.id, LightState())
            send_color, send_brightness = state.step(color, level, smooth, now)
            if send_color is not None or send_brightness is not None:
                self.manager.stream_plain(t.device, send_color, send_brightness)
            out[t.device.id] = np.array([state.shown], dtype=np.float32)
        self.details = (f"Screen: average {average.r, average.g, average.b}, brightness "
                        f"{average.brightness:.0f} % · sending {color.r, color.g, color.b} "
                        f"at {scale_brightness(color.brightness, level):.0f} % brightness")
        return out

    def preview(self):
        return self.frame


def make_screen_source(config, manager, backend_factory=None):
    """The screen sync source for the chosen style."""
    if config.sync.get("style", "classic") == "classic":
        return ClassicScreenSource(config, manager, backend_factory)
    from goveehome.sync.engine import ScreenSource
    return ScreenSource(config, backend_factory)
