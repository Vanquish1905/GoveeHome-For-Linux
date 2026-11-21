"""Built-in effects, rendered on the PC and streamed to the lights.

They work without the cloud and on every light that supports light shows.
Segment capable lights get the full pattern, others the colour at their
middle. Every effect is a function of the position along the light (0..1),
the time in seconds and the user's options, returning sRGB colours.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from goveehome.colors import parse_color
from goveehome.sync.engine import Source
from goveehome.sync.palettes import blend

TAU = 2 * np.pi


def hsv(h, s, v) -> np.ndarray:
    """Vectorised HSV -> RGB (all 0..1 inputs, 0..255 output)."""
    h = np.asarray(h, dtype=np.float32) % 1.0
    s = np.broadcast_to(np.asarray(s, dtype=np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, dtype=np.float32), h.shape)
    i = np.floor(h * 6).astype(np.int32) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1) * 255.0


def palette(colors, u, cyclic: bool = True) -> np.ndarray:
    return blend(colors, u, cyclic)


def noise(x: np.ndarray, t: float, seed: float = 0.0) -> np.ndarray:
    """Cheap smooth noise in 0..1 from a few unrelated sine waves."""
    x = np.asarray(x, dtype=np.float32)
    v = (np.sin(x * 7.13 + t * 1.7 + seed) * 0.5
         + np.sin(x * 3.71 - t * 2.9 + seed * 1.3) * 0.3
         + np.sin(x * 11.3 + t * 4.3 + seed * 2.1) * 0.2)
    return v * 0.5 + 0.5


def rand(*keys) -> np.ndarray:
    """Repeatable pseudo random numbers in 0..1 from (arrays of) keys."""
    acc = np.float64(0.0)
    for i, k in enumerate(keys):
        acc = acc + np.asarray(k, dtype=np.float64) * (12.9898 + 61.33 * i)
    return (np.sin(acc) * 43758.5453) % 1.0


@dataclass
class Params:
    speed: float = 1.0
    color_a: tuple = (255, 90, 0)
    color_b: tuple = (0, 80, 255)
    color_c: tuple = (255, 0, 140)
    size: float = 0.3            # width of moving things, 0.05 .. 1
    reverse: bool = False

    def cols(self, n: int = 3) -> list[tuple]:
        return [self.color_a, self.color_b, self.color_c][:n]


def _tile(color, n) -> np.ndarray:
    return np.tile(np.asarray(color, np.float32), (n, 1))


def _seg_index(x: np.ndarray, count: int) -> np.ndarray:
    return np.clip((x * count).astype(np.int32), 0, count - 1)


# --- colourful ---------------------------------------------------------------------

def _rainbow(x, t, p):
    return hsv(x * (0.4 + p.size) - t * 0.12 * p.speed, 1.0, 1.0)


def _cycle(x, t, p):
    return hsv(np.full_like(x, t * 0.05 * p.speed), 1.0, 1.0)


def _rainbow_pulse(x, t, p):
    level = 0.15 + 0.85 * (0.5 - 0.5 * np.cos(TAU * t * 0.3 * p.speed))
    return hsv(x * 0.5 + t * 0.04 * p.speed, 1.0, level)


def _plasma(x, t, p):
    u = noise(x * 3, t * 0.6 * p.speed) + noise(x * 5, t * 0.4 * p.speed, 4.0) * 0.5
    return hsv(u * 0.8 + t * 0.03 * p.speed, 1.0, 1.0)


def _pastel(x, t, p):
    return hsv(x * 0.5 + t * 0.03 * p.speed, 0.35, 1.0)


# --- your colours ---------------------------------------------------------------------

def _solid(x, t, p):
    return _tile(p.color_a, len(x))


def _gradient(x, t, p):
    f = 0.5 + 0.5 * np.sin(TAU * (x - t * 0.1 * p.speed))
    a, b = np.asarray(p.color_a, np.float32), np.asarray(p.color_b, np.float32)
    return a * (1 - f[:, None]) + b * f[:, None]


def _three(x, t, p):
    return palette(p.cols(3), x * (0.5 + p.size) - t * 0.08 * p.speed)


def _breathe(x, t, p):
    level = 0.06 + 0.94 * (0.5 - 0.5 * np.cos(TAU * t * 0.2 * p.speed)) ** 1.6
    return _tile(p.color_a, len(x)) * level


def _alternate(x, t, p):
    """Switch between your colours, with a soft fade."""
    phase = t * 0.25 * p.speed
    return _tile(palette(p.cols(3), np.array([phase]))[0], len(x))


def _wave(x, t, p):
    f = np.clip(np.sin(TAU * (x / max(0.1, p.size) - t * 0.3 * p.speed)), 0, 1) ** 2
    a, b = np.asarray(p.color_a, np.float32), np.asarray(p.color_b, np.float32)
    return b * (1 - f[:, None]) + a * f[:, None]


def _chase(x, t, p):
    """Theatre style chase: every third light runs along."""
    n = max(3, int(round(len(x) if len(x) > 1 else 3)))
    step = int(t * 4 * p.speed)
    idx = _seg_index(x, n)
    lit = (idx + step) % 3 == 0
    a, b = np.asarray(p.color_a, np.float32), np.asarray(p.color_b, np.float32) * 0.15
    return np.where(lit[:, None], a, b)


def _wipe(x, t, p):
    """Fill the light with one colour after the other."""
    cols = p.cols(3)
    phase = t * 0.3 * p.speed
    k = int(phase) % len(cols)
    f = phase % 1.0
    cur, nxt = np.asarray(cols[k], np.float32), np.asarray(cols[(k + 1) % len(cols)], np.float32)
    return np.where((x <= f)[:, None], nxt, cur)


def _meteor(x, t, p):
    head = (t * 0.35 * p.speed) % 1.3
    d = head - x
    tail = np.where(d >= 0, np.clip(1 - d / max(0.05, p.size), 0, 1) ** 2, 0.0)
    sparkle = 0.85 + 0.15 * rand(np.floor(x * 50), np.floor(t * 20))
    return _tile(p.color_a, len(x)) * (tail * sparkle)[:, None]


def _scanner(x, t, p):
    """A light that sweeps back and forth."""
    pos = 0.5 - 0.5 * np.cos(TAU * t * 0.25 * p.speed)
    d = np.abs(x - pos)
    level = np.clip(1 - d / max(0.04, p.size * 0.5), 0, 1) ** 1.5
    return _tile(p.color_a, len(x)) * level[:, None]


def _strobe(x, t, p):
    on = (t * 6 * p.speed) % 1.0 < 0.3
    return _tile(p.color_a, len(x)) * (1.0 if on else 0.0)


def _heartbeat(x, t, p):
    phase = (t * 1.1 * p.speed) % 1.0
    beat = np.exp(-((phase - 0.08) / 0.04) ** 2) + 0.7 * np.exp(-((phase - 0.28) / 0.05) ** 2)
    return _tile(p.color_a, len(x)) * (0.05 + 0.95 * min(1.0, beat))


# --- nature -------------------------------------------------------------------------------

def _candle(x, t, p):
    seeds = x * 37.0
    flicker = 0.55 + 0.45 * noise(seeds, t * 3.0 * p.speed) * noise(seeds + 5, t * 7.0 * p.speed)
    return _tile((255, 120, 25), len(x)) * flicker[:, None]


def _fire(x, t, p):
    heat = noise(x * 2.0, t * 2.5 * p.speed) * 0.7 + noise(x * 9.0, t * 6.0 * p.speed, 3.0) * 0.3
    return palette([(60, 0, 0), (200, 20, 0), (255, 80, 0), (255, 170, 20), (255, 230, 120)],
                   heat, cyclic=False)


def _lava(x, t, p):
    blobs = noise(x * 1.5, t * 0.35 * p.speed) * 0.6 + noise(x * 4, t * 0.2 * p.speed, 7.0) * 0.4
    return palette([(90, 0, 0), (220, 20, 0), (255, 90, 0), (255, 160, 0)], blobs, cyclic=False)


def _aurora(x, t, p):
    u = x * 0.6 + 0.25 * np.sin(TAU * (x * 0.8 + t * 0.05 * p.speed)) + t * 0.03 * p.speed
    col = palette([(0, 255, 120), (0, 180, 200), (90, 0, 255), (0, 255, 60), (0, 120, 255)], u)
    shimmer = 0.6 + 0.4 * noise(x * 3, t * 0.8 * p.speed)
    return col * shimmer[:, None]


def _ocean(x, t, p):
    u = x * 0.5 + 0.2 * np.sin(TAU * (x * 1.5 - t * 0.12 * p.speed))
    col = palette([(0, 40, 160), (0, 120, 255), (0, 220, 200), (0, 70, 200)], u + t * 0.02 * p.speed)
    swell = 0.55 + 0.45 * noise(x * 2, t * 1.2 * p.speed, 2.0)
    return col * swell[:, None]


def _underwater(x, t, p):
    base = palette([(0, 20, 60), (0, 70, 110), (0, 110, 120)], x * 0.4 + t * 0.01 * p.speed)
    caustic = np.clip(noise(x * 9, t * 1.8 * p.speed, 5.0) - 0.55, 0, 1) * 2.2
    return base + caustic[:, None] * np.array([60, 200, 200], np.float32)


def _sunset(x, t, p):
    u = x * 0.5 + t * 0.02 * p.speed
    return palette([(255, 90, 0), (255, 40, 60), (200, 0, 120), (90, 0, 160), (255, 140, 0)], u)


def _forest(x, t, p):
    u = x * 0.7 + t * 0.03 * p.speed
    col = palette([(20, 160, 0), (120, 220, 0), (0, 120, 40), (200, 200, 0)], u)
    return col * (0.6 + 0.4 * noise(x * 4, t * 0.7 * p.speed, 1.0))[:, None]


def _stars(x, t, p):
    base = _tile((0, 10, 50), len(x))
    sparkle = np.clip((noise(x * 53.0, t * 2.0 * p.speed) - 0.78) * 4.5, 0, 1)
    return base + sparkle[:, None] * np.array([255, 255, 230], np.float32)


def _storm(x, t, p):
    base = _tile((10, 15, 45), len(x)) * (0.7 + 0.3 * noise(x * 2, t * 0.5))[:, None]
    slot = np.floor(t * 2.5 * p.speed)
    strike = rand(slot) > 0.82
    if strike:
        phase = (t * 2.5 * p.speed) % 1.0
        flash = float(np.exp(-phase * 9) + (0.6 * np.exp(-(phase - 0.25) * 12) if phase > 0.25 else 0))
        where = rand(slot, 3.0)
        reach = np.clip(1 - np.abs(x - where) * 1.5, 0.3, 1)
        base = base + (flash * reach)[:, None] * np.array([230, 230, 255], np.float32)
    return base


def _rain(x, t, p):
    """Matrix style green drops."""
    lanes = np.floor(x * 24)
    speed = 0.4 + rand(lanes) * 0.8
    head = (t * speed * p.speed + rand(lanes, 2.0)) % 1.0
    level = np.clip(1 - head / max(0.1, p.size), 0, 1) ** 2
    return np.stack([level * 30, level * 255, level * 60], axis=-1)


def _snow(x, t, p):
    base = _tile((20, 40, 90), len(x))
    flakes = np.clip((noise(x * 40, t * 1.5 * p.speed, 9.0) - 0.7) * 3.3, 0, 1)
    return base + flakes[:, None] * np.array([235, 215, 165], np.float32)


def _sunrise(x, t, p):
    """Slow wake-up light: 10 minutes at speed 1 from night to warm daylight."""
    k = np.clip(t / (600.0 / max(0.05, p.speed)), 0, 1)
    col = palette([(0, 0, 0), (60, 4, 0), (200, 40, 0), (255, 120, 30), (255, 200, 120), (255, 235, 200)],
                  np.array([k]), cyclic=False)[0]
    glow = 0.92 + 0.08 * x
    return _tile(col, len(x)) * glow[:, None]


# --- party & seasons -------------------------------------------------------------------

def _party(x, t, p):
    rate = 2.0 * p.speed
    step = np.floor(t * rate)
    phase = t * rate - step
    hues = rand(np.arange(max(1, len(x))), step)
    fade = 0.35 + 0.65 * (1.0 - phase) ** 2
    return hsv(hues, 1.0, fade)


def _disco(x, t, p):
    step = np.floor(t * 5 * p.speed)
    blocks = np.floor(x * 6)
    hues = rand(blocks, step)
    on = rand(blocks, step, 1.0) > 0.35
    return hsv(hues, 1.0, np.where(on, 1.0, 0.0))


def _twinkle(x, t, p):
    cols = p.cols(3)
    n = max(1, len(x))
    idx = np.arange(n)
    period = 1.2 / max(0.05, p.speed)
    offset = rand(idx, 5.0) * period
    phase = ((t + offset) % period) / period
    level = np.sin(np.pi * phase) ** 3
    which = (rand(idx, np.floor((t + offset) / period)) * len(cols)).astype(int) % len(cols)
    base = np.asarray(cols, np.float32)[which]
    return base * level[:, None] + base * 0.05


def _fireworks(x, t, p):
    out = np.zeros((len(x), 3), np.float32)
    rate = 1.2 * p.speed
    now = t * rate
    for k in range(3):                      # a few bursts overlapping
        slot = np.floor(now) - k
        age = (now - slot) / rate
        if age < 0 or age > 2.0:
            continue
        center = rand(slot, 1.0)
        color = hsv(rand(slot, 2.0), 0.8, 1.0)
        radius = 0.05 + age * 0.35 * (0.5 + p.size)
        ring = np.clip(1 - np.abs(np.abs(x - center) - radius) / 0.08, 0, 1)
        out += ring[:, None] * color * float(np.exp(-age * 2.2))
    return out


def _police(x, t, p):
    on = bool(np.floor(t * 3 * p.speed) % 2)
    pick = (x < 0.5) ^ on if len(x) > 1 else np.array([on])
    red = np.array([255, 0, 0], np.float32)
    blue = np.array([0, 40, 255], np.float32)
    return np.where(pick[:, None], red, blue)


def _christmas(x, t, p):
    n = max(2, len(x))
    step = int(t * 1.5 * p.speed)
    idx = _seg_index(x, n)
    cols = np.array([(255, 0, 0), (0, 200, 0), (255, 255, 255)], np.float32)
    col = cols[(idx + step) % 3]
    return col * (0.75 + 0.25 * noise(x * 30, t * 3))[:, None]


def _halloween(x, t, p):
    u = x * 0.5 + t * 0.05 * p.speed
    col = palette([(255, 90, 0), (120, 0, 200), (255, 60, 0), (40, 200, 0)], u)
    flicker = 0.5 + 0.5 * noise(x * 6, t * 4 * p.speed)
    return col * flicker[:, None]


# --- animated, in their own colours ------------------------------------------------------
# These all move along the light, and they also change over time on a single
# colour light, so every light gets something out of them.

def _gauss(x, centre, width):
    return np.exp(-((x - centre) / max(0.02, width)) ** 2)


def _juggle(x, t, p):
    """Several coloured dots weaving past each other."""
    out = np.zeros((len(x), 3), np.float32)
    for k in range(4):
        pos = 0.5 + 0.48 * np.sin(t * p.speed * (0.7 + 0.35 * k) + k * 1.7)
        out += _gauss(x, pos, 0.06 + 0.12 * p.size)[:, None] * hsv(np.array([k / 4 + t * 0.03]), 1, 1)[0]
    if len(x) == 1:
        out += hsv(np.array([t * 0.08 * p.speed]), 1, 0.7)[0]
    return out


def _sinelon(x, t, p):
    """One dot sweeping back and forth with a fading tail, changing colour."""
    pos = 0.5 + 0.5 * np.sin(t * 1.3 * p.speed)
    vel = np.cos(t * 1.3 * p.speed)
    d = (x - pos) * (-np.sign(vel) or 1)
    tail = np.where(d >= 0, np.exp(-d / max(0.05, p.size * 0.6)), np.exp(d / 0.03))
    color = hsv(np.array([t * 0.07 * p.speed]), 1, 1)[0]
    return tail[:, None] * color


def _bpm(x, t, p):
    """Rainbow bands pulsing to a beat."""
    beat = 0.5 + 0.5 * np.sin(TAU * (t * 2.0 * p.speed) - x * 6)
    return hsv(x * 0.6 + t * 0.1 * p.speed, 1.0, 0.25 + 0.75 * beat)


def _confetti(x, t, p):
    """Random coloured sparks popping up and fading."""
    n = max(1, len(x))
    idx = np.arange(n)
    rate = 3.0 * p.speed
    slot = np.floor(t * rate + rand(idx, 7.0) * 3)
    phase = (t * rate + rand(idx, 7.0) * 3) % 1.0
    on = rand(idx, slot) > 0.45
    hue = rand(idx, slot, 2.0)
    if len(x) == 1:                     # one colour: a new spark every beat
        on = np.array([True])
    return hsv(hue, 0.9, np.where(on, 0.15 + 0.85 * (1 - phase) ** 1.5, 0.0))


def _bouncing(x, t, p):
    """Coloured balls bouncing up and down the light."""
    out = np.zeros((len(x), 3), np.float32)
    cols = [(255, 40, 0), (0, 255, 80), (40, 90, 255)]
    for k, col in enumerate(cols):
        period = (1.6 + 0.5 * k) / p.speed
        ph = (t + k * 0.7) % period / period
        height = 1 - (2 * ph - 1) ** 2                    # parabola: up and down
        out += _gauss(x, height, 0.05 + 0.1 * p.size)[:, None] * np.asarray(col, np.float32)
    if len(x) == 1:
        out = hsv(np.array([np.floor(t * p.speed) / 3]), 1, 1)
    return out


def _ripple(x, t, p):
    """Rings of colour flowing out from the middle."""
    d = np.abs(x - 0.5) * 2
    band = d * 3 - t * 0.8 * p.speed
    hue = np.floor(band) * 0.13
    level = 0.35 + 0.65 * (0.5 + 0.5 * np.cos(TAU * band))
    return hsv(hue, 1.0, level)


def _rainbow_chase(x, t, p):
    n = max(3, len(x) if len(x) > 1 else 3)
    step = int(t * 5 * p.speed)
    idx = _seg_index(x, n)
    lit = (idx + step) % 3 == 0
    return hsv(x * 0.8 + t * 0.05 * p.speed, 1.0, np.where(lit, 1.0, 0.08))


def _color_blocks(x, t, p, colors):
    shift = t * 0.35 * p.speed
    k = np.floor((x * (2 + 6 * p.size) - shift)) % len(colors)
    return np.asarray(colors, np.float32)[k.astype(int)]


def _blocks(x, t, p):
    """Blocks of bright colours marching along."""
    out = _color_blocks(x, t, p, [(255, 0, 0), (255, 200, 0), (0, 200, 60), (0, 90, 255), (180, 0, 255)])
    if len(x) == 1:
        out = _color_blocks(np.array([t * 0.2 * p.speed % 1]), 0, p,
                            [(255, 0, 0), (255, 200, 0), (0, 200, 60), (0, 90, 255), (180, 0, 255)])
    return out


def _rgb_spin(x, t, p):
    out = _color_blocks(x, t * 1.5, p, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    if len(x) == 1:
        out = palette([(255, 0, 0), (0, 255, 0), (0, 0, 255)], np.array([t * 0.3 * p.speed]))
    return out


def _candy_stripes(x, t, p):
    u = (x * (3 + 6 * p.size) - t * 0.5 * p.speed) % 1.0
    if len(x) == 1:
        f = 0.5 + 0.5 * np.sin(TAU * t * 0.4 * p.speed)
        return np.array([[255, 0, 40]], np.float32) * (1 - f) + np.array([[255, 220, 220]], np.float32) * f
    return np.where((u < 0.5)[:, None], np.array([255, 0, 40], np.float32),
                    np.array([255, 220, 220], np.float32))


def _neon_chase(x, t, p):
    u = x * 3 - t * 0.6 * p.speed
    f = 0.5 + 0.5 * np.sin(TAU * u)
    a = np.array([255, 0, 200], np.float32)
    b = np.array([0, 230, 255], np.float32)
    return a * (f ** 3)[:, None] + b * ((1 - f) ** 3)[:, None]


def _pingpong(x, t, p):
    """Two colours racing towards each other and bouncing off."""
    pos = 0.5 - 0.5 * np.cos(TAU * t * 0.3 * p.speed)
    w = 0.05 + 0.12 * p.size
    a = _gauss(x, pos * 0.5, w)[:, None] * np.array([255, 60, 0], np.float32)
    b = _gauss(x, 1 - pos * 0.5, w)[:, None] * np.array([0, 120, 255], np.float32)
    out = a + b
    if len(x) == 1:
        out = palette([(255, 60, 0), (0, 120, 255)], np.array([pos]), cyclic=False)
    return out


def _pride(x, t, p):
    """Colour waves: slowly drifting rainbow with breathing brightness."""
    hue = x * (0.3 + 0.2 * np.sin(t * 0.13 * p.speed)) + t * 0.05 * p.speed
    level = 0.45 + 0.55 * (0.5 + 0.5 * np.sin(TAU * (x * 1.5 + t * 0.21 * p.speed)))
    return hsv(hue, 0.85 + 0.15 * np.sin(t * 0.5), level)


def _kaleidoscope(x, t, p):
    d = np.abs(x - 0.5) * 2
    hue = d * 0.7 - t * 0.15 * p.speed + 0.2 * np.sin(t * 0.7 * p.speed)
    return hsv(hue, 1.0, 0.5 + 0.5 * np.cos(TAU * (d * 2 - t * 0.4 * p.speed)) ** 2)


def _galaxy(x, t, p):
    swirl = noise(x * 2.5, t * 0.5 * p.speed) * 0.7 + x * 0.3 + t * 0.02 * p.speed
    base = palette([(60, 0, 140), (0, 40, 200), (200, 0, 160), (20, 0, 80)], swirl)
    stars = np.clip((noise(x * 60, t * 2.5 * p.speed, 3.0) - 0.8) * 5, 0, 1)
    return base + stars[:, None] * np.array([255, 240, 255], np.float32)


def _sparkle_rainbow(x, t, p):
    base = hsv(x * 0.5 + t * 0.06 * p.speed, 1.0, 0.45)
    spark = np.clip((noise(x * 70, t * 4 * p.speed, 11.0) - 0.75) * 4, 0, 1)
    return base + spark[:, None] * 255


def _dna(x, t, p):
    """Two colour strands winding around each other."""
    a = 0.5 + 0.5 * np.sin(TAU * (x * 2 - t * 0.4 * p.speed))
    b = 0.5 + 0.5 * np.sin(TAU * (x * 2 - t * 0.4 * p.speed) + np.pi)
    return (a ** 4)[:, None] * np.array([255, 0, 120], np.float32) + \
        (b ** 4)[:, None] * np.array([0, 200, 255], np.float32)


def _spectrum_sweep(x, t, p):
    phase = t * 0.25 * p.speed
    front = phase % 1.0
    hue_now = np.floor(phase) * 0.17
    return np.where((x <= front)[:, None], hsv(np.full_like(x, hue_now + 0.17), 1, 1),
                    hsv(np.full_like(x, hue_now), 1, 1))


def _flow(colors):
    def fn(x, t, p):
        u = x * (0.4 + p.size) + t * 0.08 * p.speed + 0.15 * np.sin(TAU * (x - t * 0.1 * p.speed))
        return palette(colors, u)
    return fn


def _comet(colors, rainbow=False):
    def fn(x, t, p):
        head = (t * 0.4 * p.speed) % 1.4
        d = head - x
        tail = np.where(d >= 0, np.clip(1 - d / max(0.08, p.size + 0.1), 0, 1) ** 2, 0.0)
        if rainbow:
            col = hsv(d * 1.5 + t * 0.1, 1, 1)
        else:
            col = palette(colors, np.clip(d * 6, 0, 1) ** 0.5 * 0.5 + 0.25, cyclic=False)
        out = col * tail[:, None]
        if len(x) == 1:
            out = palette(colors if not rainbow else [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
                          np.array([t * 0.15 * p.speed]))
        return out
    return fn


def _breathe_cycle(colors):
    def fn(x, t, p):
        phase = t * 0.2 * p.speed
        level = 0.12 + 0.88 * (0.5 - 0.5 * np.cos(TAU * phase)) ** 1.3
        col = np.asarray(colors, np.float32)[int(phase) % len(colors)]
        return _tile(col, len(x)) * level
    return fn


@dataclass(frozen=True)
class Effect:
    id: str
    label: str
    fn: Callable
    category: str = "Colourful"
    uses_colors: int = 0     # how many of your colours it uses (0 .. 3)
    preview: tuple = ()      # colours for the card in the UI
    uses_size: bool = False


CATEGORIES = ["Animated", "Colourful", "Your colours", "Nature", "Party and seasons"]

_ANIMATED = [
    ("juggle", "Juggle", _juggle, ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255)), True),
    ("sinelon", "Sweep", _sinelon, ((0, 0, 0), (255, 0, 120), (0, 0, 0)), True),
    ("bpm", "Beat bands", _bpm, ((255, 0, 80), (255, 200, 0), (0, 120, 255)), False),
    ("confetti", "Confetti", _confetti, ((255, 0, 150), (0, 255, 100), (255, 220, 0), (0, 100, 255)), False),
    ("bouncing", "Bouncing balls", _bouncing, ((255, 40, 0), (0, 255, 80), (40, 90, 255)), True),
    ("ripple", "Ripple", _ripple, ((0, 200, 255), (255, 0, 160), (0, 200, 255)), False),
    ("rainbow_chase", "Rainbow chase", _rainbow_chase, ((255, 0, 0), (0, 0, 0), (0, 255, 0), (0, 0, 0), (0, 0, 255)), False),
    ("blocks", "Colour blocks", _blocks, ((255, 0, 0), (255, 200, 0), (0, 200, 60), (0, 90, 255)), True),
    ("rgb_spin", "RGB spin", _rgb_spin, ((255, 0, 0), (0, 255, 0), (0, 0, 255)), True),
    ("candy_stripes", "Candy stripes", _candy_stripes, ((255, 0, 40), (255, 220, 220), (255, 0, 40)), True),
    ("neon_chase", "Neon chase", _neon_chase, ((255, 0, 200), (0, 230, 255), (255, 0, 200)), False),
    ("pingpong", "Ping pong", _pingpong, ((255, 60, 0), (0, 0, 0), (0, 120, 255)), True),
    ("pride", "Colour waves", _pride, ((255, 0, 0), (255, 255, 0), (0, 255, 120), (120, 0, 255)), False),
    ("kaleidoscope", "Kaleidoscope", _kaleidoscope, ((0, 255, 200), (255, 0, 200), (0, 255, 200)), False),
    ("galaxy", "Galaxy", _galaxy, ((60, 0, 140), (0, 40, 200), (200, 0, 160)), False),
    ("sparkle", "Rainbow sparkle", _sparkle_rainbow, ((120, 0, 0), (255, 255, 255), (0, 0, 120)), False),
    ("dna", "Double helix", _dna, ((255, 0, 120), (0, 200, 255), (255, 0, 120)), False),
    ("sweep_rainbow", "Spectrum sweep", _spectrum_sweep, ((255, 0, 0), (255, 255, 0), (0, 255, 0)), False),
    ("rainbow_comet", "Rainbow comet", _comet([], rainbow=True), ((0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)), True),
    ("blue_comet", "Ice comet", _comet([(255, 255, 255), (0, 160, 255), (0, 20, 120)]), ((0, 20, 120), (0, 160, 255), (255, 255, 255)), True),
    ("pink_comet", "Pink comet", _comet([(255, 220, 255), (255, 0, 150), (90, 0, 120)]), ((90, 0, 120), (255, 0, 150), (255, 220, 255)), True),
    ("fire_comet", "Fire comet", _comet([(255, 240, 150), (255, 90, 0), (120, 0, 0)]), ((120, 0, 0), (255, 90, 0), (255, 240, 150)), True),
    ("green_comet", "Green comet", _comet([(220, 255, 220), (0, 255, 60), (0, 60, 20)]), ((0, 60, 20), (0, 255, 60), (220, 255, 220)), True),
    ("flow_cotton", "Cotton candy", _flow([(255, 120, 200), (120, 200, 255), (255, 200, 240)]), ((255, 120, 200), (120, 200, 255), (255, 200, 240)), True),
    ("flow_tropical", "Tropical flow", _flow([(0, 255, 180), (255, 220, 0), (255, 60, 120), (0, 180, 255)]), ((0, 255, 180), (255, 220, 0), (255, 60, 120)), True),
    ("flow_inferno", "Inferno", _flow([(255, 0, 0), (255, 120, 0), (180, 0, 120), (255, 40, 0)]), ((255, 0, 0), (255, 120, 0), (180, 0, 120)), True),
    ("flow_mint", "Mint and lime", _flow([(0, 255, 160), (160, 255, 0), (0, 200, 120)]), ((0, 255, 160), (160, 255, 0), (0, 200, 120)), True),
    ("flow_cyber", "Cyber flow", _flow([(255, 0, 120), (0, 240, 255), (250, 240, 0), (120, 0, 255)]), ((255, 0, 120), (0, 240, 255), (250, 240, 0)), True),
    ("flow_ocean", "Deep sea flow", _flow([(0, 30, 150), (0, 200, 220), (0, 90, 255), (60, 0, 200)]), ((0, 30, 150), (0, 200, 220), (60, 0, 200)), True),
    ("breathe_rgb", "Breathing colours", _breathe_cycle([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255), (255, 200, 0), (0, 255, 255)]), ((255, 0, 0), (0, 255, 0), (0, 0, 255)), False),
]

EFFECTS: dict[str, Effect] = {e.id: e for e in [
    *[Effect(eid, label, fn, "Animated", 0, prev, size) for eid, label, fn, prev, size in _ANIMATED],
    # colourful
    Effect("rainbow", "Rainbow", _rainbow, "Colourful", 0, ((255, 0, 0), (0, 255, 0), (0, 0, 255)), True),
    Effect("cycle", "Colour cycle", _cycle, "Colourful", 0, ((255, 0, 120), (255, 160, 0), (0, 200, 255))),
    Effect("rainbow_pulse", "Rainbow pulse", _rainbow_pulse, "Colourful", 0, ((90, 0, 0), (255, 200, 0), (0, 60, 90))),
    Effect("plasma", "Plasma", _plasma, "Colourful", 0, ((255, 0, 200), (0, 255, 160), (255, 200, 0))),
    Effect("pastel", "Pastel dream", _pastel, "Colourful", 0, ((255, 170, 200), (170, 220, 255), (210, 255, 170))),
    # your colours
    Effect("solid", "Solid", _solid, "Your colours", 1),
    Effect("gradient", "Gradient", _gradient, "Your colours", 2),
    Effect("three", "Three colours", _three, "Your colours", 3, (), True),
    Effect("breathe", "Breathe", _breathe, "Your colours", 1),
    Effect("alternate", "Colour fade", _alternate, "Your colours", 3),
    Effect("wave", "Wave", _wave, "Your colours", 2, (), True),
    Effect("chase", "Chase", _chase, "Your colours", 2),
    Effect("wipe", "Colour wipe", _wipe, "Your colours", 3),
    Effect("meteor", "Meteor", _meteor, "Your colours", 1, (), True),
    Effect("scanner", "Scanner", _scanner, "Your colours", 1, (), True),
    Effect("heartbeat", "Heartbeat", _heartbeat, "Your colours", 1),
    Effect("strobe", "Strobe", _strobe, "Your colours", 1),
    # nature
    Effect("candle", "Candle", _candle, "Nature", 0, ((255, 120, 25), (180, 60, 5))),
    Effect("fire", "Fire", _fire, "Nature", 0, ((200, 20, 0), (255, 170, 20))),
    Effect("lava", "Lava lamp", _lava, "Nature", 0, ((120, 0, 0), (255, 120, 0))),
    Effect("aurora", "Aurora", _aurora, "Nature", 0, ((0, 255, 120), (90, 0, 255))),
    Effect("ocean", "Ocean", _ocean, "Nature", 0, ((0, 40, 160), (0, 220, 200))),
    Effect("underwater", "Underwater", _underwater, "Nature", 0, ((0, 20, 60), (60, 220, 220))),
    Effect("sunset", "Sunset", _sunset, "Nature", 0, ((255, 90, 0), (200, 0, 120))),
    Effect("sunrise", "Sunrise alarm", _sunrise, "Nature", 0, ((40, 0, 0), (255, 120, 30), (255, 235, 200))),
    Effect("forest", "Forest", _forest, "Nature", 0, ((20, 160, 0), (200, 200, 0))),
    Effect("stars", "Starry night", _stars, "Nature", 0, ((0, 10, 50), (200, 200, 255))),
    Effect("storm", "Thunderstorm", _storm, "Nature", 0, ((10, 15, 45), (230, 230, 255))),
    Effect("snow", "Snowfall", _snow, "Nature", 0, ((20, 40, 90), (255, 255, 255))),
    Effect("rain", "Digital rain", _rain, "Nature", 0, ((0, 30, 0), (40, 255, 80)), True),
    # party and seasons
    Effect("party", "Party", _party, "Party and seasons", 0, ((255, 0, 200), (0, 255, 100))),
    Effect("disco", "Disco", _disco, "Party and seasons", 0, ((255, 0, 0), (0, 0, 255), (255, 255, 0))),
    Effect("twinkle", "Twinkle", _twinkle, "Party and seasons", 3),
    Effect("fireworks", "Fireworks", _fireworks, "Party and seasons", 0, ((0, 0, 0), (255, 60, 200), (255, 220, 60)), True),
    Effect("police", "Police", _police, "Party and seasons", 0, ((255, 0, 0), (0, 40, 255))),
    Effect("christmas", "Christmas", _christmas, "Party and seasons", 0, ((255, 0, 0), (0, 200, 0), (255, 255, 255))),
    Effect("halloween", "Halloween", _halloween, "Party and seasons", 0, ((255, 90, 0), (120, 0, 200))),
]}


def render(effect_id: str, positions: np.ndarray, t: float, params: Params) -> np.ndarray:
    effect = EFFECTS.get(effect_id) or EFFECTS["rainbow"]
    x = np.asarray(positions, dtype=np.float32)
    if params.reverse:
        x = 1.0 - x
    return np.clip(effect.fn(x, t, params), 0, 255).astype(np.float32)


def card_colors(effect: Effect, params: Params) -> list[tuple]:
    if effect.uses_colors >= 2:
        return params.cols(effect.uses_colors)
    if effect.uses_colors == 1:
        return [params.color_a, tuple(int(c * 0.2) for c in params.color_a)]
    return list(effect.preview)


def params_from(section: dict) -> Params:
    def color(key, fallback):
        try:
            return parse_color(section.get(key) or fallback)
        except ValueError:
            return parse_color(fallback)
    return Params(
        speed=float(section.get("speed", 1.0)),
        color_a=color("color_a", "#ff5a00"),
        color_b=color("color_b", "#0050ff"),
        color_c=color("color_c", "#ff008c"),
        size=float(section.get("size", 0.3)),
        reverse=bool(section.get("reverse", False)),
    )


class EffectSource(Source):
    kind = "effects"

    def __init__(self, config, effect: str | None = None):
        self.config = config
        self.effect = effect
        self._start = 0.0
        self._frame: np.ndarray | None = None

    @property
    def section(self) -> dict:
        return self.config.section("effects")

    def open(self) -> None:
        self._start = time.monotonic()
        self._current = None
        self.label = EFFECTS.get(self.effect or self.section.get("effect"), EFFECTS["rainbow"]).label

    def fps(self) -> int:
        return int(self.section.get("fps", 30))

    def render(self, targets, now):
        effect_id = self.effect or self.section.get("effect", "rainbow")
        if effect_id != getattr(self, "_current", None):
            self._current = effect_id
            self._start = now        # every effect starts from its beginning (sunrise!)
        self.label = EFFECTS.get(effect_id, EFFECTS["rainbow"]).label
        params = params_from(self.section)
        t = now - self._start
        brightness = float(self.section.get("brightness", 1.0))
        out = {target.device.id: render(effect_id, target.positions, t, params) * brightness
               for target in targets}
        strip = render(effect_id, np.linspace(0, 1, 160), t, params) * brightness
        self._frame = np.repeat(np.clip(strip, 0, 255).astype(np.uint8)[None, :, :], 90, axis=0)
        return out

    def preview(self):
        return self._frame
