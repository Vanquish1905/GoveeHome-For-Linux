import numpy as np
import pytest

from goveehome.config import Config
from goveehome.sync import effects, music
from goveehome.sync.engine import Target
from goveehome.sync.colors import Smoother
from goveehome.models import Device


@pytest.mark.parametrize("effect", list(effects.EFFECTS))
@pytest.mark.parametrize("n", [1, 2, 15])
def test_effects_render_valid_colours(effect, n):
    for t in (0.0, 1.3, 50.0):
        c = effects.render(effect, np.linspace(0, 1, n), t, effects.Params())
        assert c.shape == (n, 3)
        assert np.isfinite(c).all() and c.min() >= 0 and c.max() <= 255


def test_effects_move_over_time():
    a = effects.render("rainbow", np.linspace(0, 1, 10), 0.0, effects.Params())
    b = effects.render("rainbow", np.linspace(0, 1, 10), 2.0, effects.Params())
    assert np.abs(a - b).max() > 20


def test_gradient_uses_custom_colours():
    p = effects.Params(color_a=(255, 0, 0), color_b=(0, 0, 255))
    c = effects.render("gradient", np.linspace(0, 1, 30), 0.0, p)
    assert c[:, 1].max() < 1          # only red/blue mixes
    assert c[:, 0].max() > 250 and c[:, 2].max() > 250


def test_hsv_primaries():
    assert np.allclose(effects.hsv(np.array([0.0, 1 / 3, 2 / 3]), 1, 1),
                       [[255, 0, 0], [0, 255, 0], [0, 0, 255]], atol=1)


def tone(freq, seconds=0.1, amp=0.5):
    t = np.arange(int(music.RATE * seconds)) / music.RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_analyzer_finds_frequencies():
    a = music.Analyzer()
    a.feed(tone(70))
    low = a.analyze(0.0)
    a.feed(tone(6000))
    high = a.analyze(0.1)
    assert low.bands.argmax() <= 2
    assert high.bands.argmax() >= len(high.bands) - 6
    assert low.centroid < high.centroid


def test_analyzer_silence():
    a = music.Analyzer()
    a.feed(np.zeros(4096, np.float32))
    r = a.analyze(0.0)
    assert r.level == 0 and r.bands.max() == 0 and not r.beat


def test_beat_detection_at_120_bpm():
    a = music.Analyzer()
    rate, fps = music.RATE, 50
    beats = []
    for i in range(fps * 6):                 # six seconds at 50 analyses per second
        now = i / fps
        chunk = np.zeros(rate // fps, np.float32)
        phase = now % 0.5
        if phase < 0.12:                     # kick drum every half second
            t = np.arange(len(chunk)) / rate + phase
            chunk = (0.9 * np.sin(2 * np.pi * 55 * t) * np.exp(-t * 20)).astype(np.float32)
        a.feed(chunk)
        if a.analyze(now).beat:
            beats.append(now)
    gaps = np.diff(beats)
    assert len(beats) >= 9
    assert np.allclose(gaps, 0.5, atol=0.05)


class FakeAudio:
    label = "Test audio"

    def __init__(self):
        self.t = 0

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        self.t += 1
        return tone(60 if self.t % 10 < 2 else 3000, 0.025, 0.6)


@pytest.mark.parametrize("mode", list(music.MODES))
def test_music_source_modes(tmp_path, mode):
    config = Config(tmp_path / "c.json")
    config.section("music")["mode"] = mode
    src = music.MusicSource(config, audio_factory=FakeAudio)
    src.open()
    targets = [Target(Device("a"), {}, [(0, 0, 1, 1)] * 8, np.linspace(0, 1, 8), Smoother()),
               Target(Device("b"), {}, [(0, 0, 1, 1)], np.array([0.5]), Smoother())]
    for i in range(40):
        out = src.render(targets, i / 40)
    assert out["a"].shape == (8, 3) and out["b"].shape == (1, 3)
    assert np.isfinite(out["a"]).all()
    assert src.preview().shape == (90, 160, 3)
