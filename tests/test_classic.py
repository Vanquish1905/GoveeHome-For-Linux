"""The GoveeScreen style screen sync (port of GoveeScreen's FrameAnalyzer / SyncEngine)."""

import threading
import time

import numpy as np

from goveehome.capture.pattern import PatternCapture
from goveehome.config import Config
from goveehome.manager import DeviceManager
from goveehome.models import Device
from goveehome.sync import classic
from goveehome.sync.engine import SyncEngine


def test_average_skips_black_bars_like_goveescreen():
    f = np.zeros((90, 160, 3), np.uint8)
    f[12:78] = (200, 100, 50)            # film between letterbox bars
    colour, average = classic.analyze(f)
    assert (colour.r, colour.g, colour.b) == (200, 100, 50)
    assert abs(colour.brightness - (0.2126 * 200 + 0.7152 * 100 + 0.0722 * 50) / 2.55) < 1e-6


def test_all_black_frame():
    colour, _ = classic.analyze(np.zeros((90, 160, 3), np.uint8))
    assert (colour.r, colour.g, colour.b, colour.brightness) == (0, 0, 0, 0)


def test_average_uses_integer_division():
    f = np.zeros((2, 2, 3), np.uint8)
    f[0, 0] = (255, 255, 255)
    f[0, 1] = (30, 30, 30)
    f[1] = (40, 40, 40)
    colour, _ = classic.analyze(f)
    assert colour.r == (255 + 30 + 40 + 40) // 4


def test_dominant_mixes_back_to_average_with_little_colour():
    f = np.full((90, 160, 3), 60, np.uint8)
    f[:, :1] = (255, 0, 0)               # under 2 % red pixels -> plain average
    colour, average = classic.analyze(f, "dominant")
    assert (colour.r, colour.g, colour.b) == (average.r, average.g, average.b)
    g = np.full((90, 160, 3), 60, np.uint8)
    g[:, :40] = (255, 0, 0)              # 25 % red -> fully the dominant red
    colour, average = classic.analyze(g, "dominant")
    assert colour.r > 240 and colour.g < 10 and colour.b < 10
    assert colour.brightness == average.brightness   # brightness always follows the whole picture


def test_intensity_levels():
    assert classic.scale_brightness(40, 1) == 20
    assert classic.scale_brightness(40, 2) == 40
    assert classic.scale_brightness(40, 3) == 80
    assert classic.scale_brightness(70, 3) == 100
    assert classic.scale_brightness(5, 4) == 100


def test_light_state_smoothing_deadband_and_rate():
    s = classic.LightState()
    c = classic.FrameColor(200, 100, 50, 40.0)
    assert s.step(c, 2, True, 0.0) == ((200, 100, 50), 40.0)
    assert s.step(c, 2, True, 0.010) == (None, None)            # nothing changed
    d = classic.FrameColor(0, 0, 0, 0.0)
    assert s.step(d, 2, True, 0.020) == (None, None)            # too soon after the last send
    colour, bright = s.step(d, 2, True, 0.033 + 0.010)
    assert colour is not None and 0 < colour[0] < 200           # smoothed, not jumped
    s2 = classic.LightState()
    s2.step(c, 2, False, 0.0)
    colour, _ = s2.step(d, 2, False, 0.05)
    assert colour == (0, 0, 0)                                   # smoothing off: straight there


class Lan:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


def test_classic_sync_sends_colour_and_brightness_commands(tmp_path):
    m = DeviceManager(Config(tmp_path / "c.json"))
    m.lan = Lan()
    neon = m.devices["neon"] = Device("neon", sku="H61A0", ip="10.0.0.5")
    neon.state.merge(color=(1, 2, 3), brightness=55)
    assert m.config.sync["style"] == "classic"
    done = threading.Event()
    engine = SyncEngine(m, on_state=lambda r, msg: (not r) and done.set(),
                        backend_factory=lambda name: PatternCapture())
    engine.start()
    time.sleep(0.8)
    engine.stop()
    assert done.wait(3)
    names = [c[0] for c in m.lan.calls]
    assert "color" in names and "brightness" in names
    assert "stream_colors" not in names and "stream_enable" not in names
    # stopped: colour and brightness put back
    assert m.lan.calls[-1] in (("color", "10.0.0.5", (1, 2, 3)), ("request_status", "10.0.0.5"))
    assert ("brightness", "10.0.0.5", 55) in m.lan.calls


def test_config_migration_switches_to_classic(tmp_path):
    import json
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"version": 4, "sync": {"style": "zones"}}))
    assert Config(path).sync["style"] == "classic"
