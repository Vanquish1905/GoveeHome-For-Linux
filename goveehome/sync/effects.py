"""Built-in effects, rendered on the PC and streamed to the lights.

They work without the cloud and on every light that supports screen sync.
Segment capable lights get the full pattern, others the colour at their
middle. Every effect is a function of the position along the light (0..1)
and time, returning sRGB colours.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from goveehome.colors import parse_color
from goveehome.sync.engine import Source

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


def palette(colors: Sequence[Sequence[float]], u: np.ndarray, cyclic: bool = True) -> np.ndarray:
    """Interpolate a list of colours at positions u (0..1)."""
    pal = np.asarray(colors, dtype=np.float32)
    n = len(pal)
    u = np.asarray(u, dtype=np.float32)
    if cyclic:
        x = (u % 1.0) * n
        i0 = np.floor(x).astype(np.int32) % n
        i1 = (i0 + 1) % n
    else:
        x = np.clip(u, 0, 1) * (n - 1)
        i0 = np.clip(np.floor(x).astype(np.int32), 0, n - 1)
        i1 = np.clip(i0 + 1, 0, n - 1)
    f = (x - np.floor(x))[..., None]
    f = f * f * (3 - 2 * f)  # smoothstep, softer transitions
    return pal[i0] * (1 - f) + pal[i1] * f


def noise(x: np.ndarray, t: float, seed: float = 0.0) -> np.ndarray:
    """Cheap smooth noise in 0..1 from a few unrelated sine waves."""
    x = np.asarray(x, dtype=np.float32)
    v = (np.sin(x * 7.13 + t * 1.7 + seed) * 0.5
         + np.sin(x * 3.71 - t * 2.9 + seed * 1.3) * 0.3
         + np.sin(x * 11.3 + t * 4.3 + seed * 2.1) * 0.2)
    return v * 0.5 + 0.5


@dataclass
class Params:
    speed: float = 1.0
    color_a: tuple = (255, 90, 0)
    color_b: tuple = (0, 80, 255)


def _rainbow(x, t, p):
    return hsv(x - t * 0.12 * p.speed, 1.0, 1.0)


def _cycle(x, t, p):
    return hsv(np.full_like(x, t * 0.05 * p.speed), 1.0, 1.0)


def _breathe(x, t, p):
    level = 0.08 + 0.92 * (0.5 - 0.5 * np.cos(TAU * t * 0.2 * p.speed)) ** 1.6
    return np.tile(np.asarray(p.color_a, np.float32), (len(x), 1)) * level


def _gradient(x, t, p):
    f = 0.5 + 0.5 * np.sin(TAU * (x - t * 0.1 * p.speed))
    a, b = np.asarray(p.color_a, np.float32), np.asarray(p.color_b, np.float32)
    return a * (1 - f[:, None]) + b * f[:, None]


def _candle(x, t, p):
    seeds = x * 37.0
    flicker = 0.55 + 0.45 * noise(seeds, t * 3.0 * p.speed) * noise(seeds + 5, t * 7.0 * p.speed)
    warm = np.array([255, 120, 25], np.float32)
    return warm * flicker[:, None]


def _fire(x, t, p):
    heat = noise(x * 2.0, t * 2.5 * p.speed) * 0.7 + noise(x * 9.0, t * 6.0 * p.speed, 3.0) * 0.3
    return palette([(60, 0, 0), (200, 20, 0), (255, 80, 0), (255, 170, 20), (255, 230, 120)],
                   heat, cyclic=False)


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


def _sunset(x, t, p):
    u = x * 0.5 + t * 0.02 * p.speed
    return palette([(255, 90, 0), (255, 40, 60), (200, 0, 120), (90, 0, 160), (255, 140, 0)], u)


def _forest(x, t, p):
    u = x * 0.7 + t * 0.03 * p.speed
    col = palette([(20, 160, 0), (120, 220, 0), (0, 120, 40), (200, 200, 0)], u)
    return col * (0.6 + 0.4 * noise(x * 4, t * 0.7 * p.speed, 1.0))[:, None]


def _party(x, t, p):
    rate = 2.0 * p.speed                    # colour changes per second
    step = np.floor(t * rate)
    phase = t * rate - step
    rng = np.random.default_rng(int(step) & 0xFFFFFFFF)
    hues = rng.random(max(1, len(x)))
    fade = 0.35 + 0.65 * (1.0 - phase) ** 2
    return hsv(hues, 1.0, fade)


def _stars(x, t, p):
    base = np.tile(np.array([0, 10, 50], np.float32), (len(x), 1))
    sparkle = np.clip((noise(x * 53.0, t * 2.0 * p.speed) - 0.78) * 4.5, 0, 1)
    return base + sparkle[:, None] * np.array([255, 255, 230], np.float32)


def _police(x, t, p):
    on = bool(np.floor(t * 3 * p.speed) % 2)
    pick = (x < 0.5) ^ on if len(x) > 1 else np.array([on])
    red = np.array([255, 0, 0], np.float32)
    blue = np.array([0, 40, 255], np.float32)
    return np.where(pick[:, None], red, blue)


@dataclass(frozen=True)
class Effect:
    id: str
    label: str
    fn: Callable
    uses_colors: int = 0     # how many of the custom colours it uses
    preview: tuple = ()      # colours for the effect card in the UI


EFFECTS: dict[str, Effect] = {e.id: e for e in [
    Effect("rainbow", "Rainbow", _rainbow, 0, ((255, 0, 0), (0, 255, 0), (0, 0, 255))),
    Effect("cycle", "Colour cycle", _cycle, 0, ((255, 0, 120), (255, 160, 0), (0, 200, 255))),
    Effect("gradient", "Gradient", _gradient, 2),
    Effect("breathe", "Breathe", _breathe, 1),
    Effect("candle", "Candle", _candle, 0, ((255, 120, 25), (180, 60, 5))),
    Effect("fire", "Fire", _fire, 0, ((200, 20, 0), (255, 170, 20))),
    Effect("aurora", "Aurora", _aurora, 0, ((0, 255, 120), (90, 0, 255))),
    Effect("ocean", "Ocean", _ocean, 0, ((0, 40, 160), (0, 220, 200))),
    Effect("sunset", "Sunset", _sunset, 0, ((255, 90, 0), (200, 0, 120))),
    Effect("forest", "Forest", _forest, 0, ((20, 160, 0), (200, 200, 0))),
    Effect("stars", "Starry night", _stars, 0, ((0, 10, 50), (200, 200, 255))),
    Effect("party", "Party", _party, 0, ((255, 0, 200), (0, 255, 100))),
    Effect("police", "Police", _police, 0, ((255, 0, 0), (0, 40, 255))),
]}


def render(effect_id: str, positions: np.ndarray, t: float, params: Params) -> np.ndarray:
    effect = EFFECTS.get(effect_id) or EFFECTS["rainbow"]
    x = np.asarray(positions, dtype=np.float32)
    return np.clip(effect.fn(x, t, params), 0, 255).astype(np.float32)


def card_colors(effect: Effect, params: Params) -> list[tuple]:
    if effect.uses_colors == 2:
        return [params.color_a, params.color_b]
    if effect.uses_colors == 1:
        return [params.color_a, tuple(int(c * 0.25) for c in params.color_a)]
    return list(effect.preview)


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

    def _params(self) -> Params:
        s = self.section
        try:
            a, b = parse_color(s.get("color_a", "#ff5a00")), parse_color(s.get("color_b", "#0050ff"))
        except ValueError:
            a, b = (255, 90, 0), (0, 80, 255)
        return Params(speed=float(s.get("speed", 1.0)), color_a=a, color_b=b)

    def open(self) -> None:
        import time
        self._start = time.monotonic()
        self.label = EFFECTS.get(self.effect or self.section.get("effect"), EFFECTS["rainbow"]).label

    def fps(self) -> int:
        return int(self.section.get("fps", 30))

    def render(self, targets, now):
        effect_id = self.effect or self.section.get("effect", "rainbow")
        self.label = EFFECTS.get(effect_id, EFFECTS["rainbow"]).label
        params = self._params()
        t = now - self._start
        brightness = float(self.section.get("brightness", 1.0))
        out = {target.device.id: render(effect_id, target.positions, t, params) * brightness
               for target in targets}
        strip = render(effect_id, np.linspace(0, 1, 160), t, params) * brightness
        self._frame = np.repeat(np.clip(strip, 0, 255).astype(np.uint8)[None, :, :], 90, axis=0)
        return out

    def preview(self):
        return self._frame
