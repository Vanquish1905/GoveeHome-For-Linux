import pytest
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
    m.config.sync["style"] = "classic"
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


def test_config_migration_switches_to_the_grid(tmp_path):
    import json
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"version": 6, "sync": {"style": "classic"}}))
    assert Config(path).sync["style"] == "grid"


# --- 9 parts ----------------------------------------------------------------------------------

def nine_colour_screen():
    """A screen whose 9 parts each have their own colour."""
    colours = [(255, 0, 0), (255, 255, 0), (0, 255, 0),
               (255, 0, 255), (128, 128, 128), (0, 255, 255),
               (0, 0, 255), (255, 128, 0), (255, 255, 255)]
    f = np.zeros((90, 160, 3), np.uint8)
    for i, c in enumerate(colours):
        r, col = divmod(i, 3)
        f[r * 30:(r + 1) * 30, col * 53:(col + 1) * 53 + (1 if col == 2 else 0)] = c
    return f, colours


def test_grid_colours_give_each_part_its_colour():
    f, colours = nine_colour_screen()
    cells = classic.grid_colours(f)
    for got, want in zip(cells, colours):
        assert np.abs(np.array([got.r, got.g, got.b]) - np.array(want)).max() <= 3


def test_segments_follow_the_part_they_sit_next_to():
    # TV backlight: up the left side, across the top, down the right side
    cells = classic.segment_cells({"segments": 9, "layout": "u_shape", "reverse": False})
    assert cells[0] == 6 and cells[-1] == 8           # starts bottom left, ends bottom right
    assert 0 in cells and 1 in cells and 2 in cells   # passes the top left, middle and right
    # light bars: left bar = left column, right bar = right column, top to bottom
    bars = classic.segment_cells({"segments": 6, "layout": "bars", "reverse": False})
    assert bars == [0, 3, 6, 2, 5, 8]
    # a strip on "whole screen" goes around the screen
    around = classic.segment_cells({"segments": 8, "layout": "whole", "reverse": False})
    assert set(around) == {0, 1, 2, 3, 5, 6, 7, 8}


class Nine:
    label = "test"

    def open(self):
        pass

    def close(self):
        pass

    def grab(self):
        return nine_colour_screen()[0]


@pytest.mark.parametrize("detail", [False, True])
def test_grid_style_streams_part_colours_and_plain_lights_get_one_colour(tmp_path, detail):
    m = DeviceManager(Config(tmp_path / "c.json"))
    m.lan = Lan()
    m.config.sync.update(style="grid", grid_detail=detail, skip_panel=0.0, smooth=False, intensity=4)
    tv = m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")        # streams 15 segments
    bulb = m.devices["bulb"] = Device("bulb", sku="H6008", ip="10.0.0.2")  # plain colour only
    done = threading.Event()
    engine = SyncEngine(m, on_state=lambda r, msg: (not r) and done.set(),
                        backend_factory=lambda name: Nine())
    engine.start()
    time.sleep(0.6)
    engine.stop()
    assert done.wait(3)
    frames = [c[2] for c in m.lan.calls if c[0] == "stream_colors" and c[1] == "10.0.0.1"]
    assert frames and len(frames[-1]) == 15
    first, last = frames[-1][0], frames[-1][-1]
    assert first[2] > 200 and first[0] < 30            # starts at the bottom left part: blue
    assert last == (255, 255, 255)                     # ends at the bottom right part: white
    assert any(c[0] == "color" and c[1] == "10.0.0.2" for c in m.lan.calls)
    assert any(c[0] == "brightness" and c[1] == "10.0.0.2" for c in m.lan.calls)


def test_colour_strength_shows_the_screen_colour_not_white():
    pale = classic.FrameColor(120, 154, 141, 57.0)          # nature scene average
    strong = classic.strengthen(pale, 3)
    assert strong.g == 255 and strong.r < 130 and strong.brightness == 57.0
    assert (strong.g - strong.r) > 3 * (pale.g - pale.r)       # much clearer colour
    off = classic.strengthen(pale, 0)
    assert (off.r, off.g, off.b) == (120, 154, 141)           # off = exactly like GoveeScreen
    white = classic.strengthen(classic.FrameColor(235, 235, 236, 90.0), 3)
    assert min(white.r, white.g, white.b) >= 250                # white stays white
    tint = classic.strengthen(classic.FrameColor(128, 128, 120, 50.0), 4)
    assert min(tint.r, tint.g, tint.b) > 230                    # a faint tint isn't blown up
    black = classic.strengthen(classic.FrameColor(2, 2, 3, 0.5), 4)
    assert (black.r, black.g, black.b) == (0, 0, 0)


def test_colour_strength_keeps_the_hue():
    import colorsys
    for rgb in [(200, 150, 120), (40, 52, 60), (180, 110, 90), (90, 60, 140)]:
        before = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[0]
        out = classic.strengthen(classic.FrameColor(*rgb, 50.0), 3)
        after = colorsys.rgb_to_hsv(out.r / 255, out.g / 255, out.b / 255)[0]
        assert abs(before - after) < 0.02 or abs(before - after) > 0.98


def test_fifty_parts():
    assert classic.grid_size({"grid_detail": True}) == (10, 5)
    assert classic.grid_size({"grid_detail": False}) == (3, 3)
    assert classic.grid_size({}) == (10, 5)
    f = np.zeros((90, 160, 3), np.uint8)
    f[:, :16] = (255, 0, 0)          # left tenth red
    f[:, -16:] = (0, 0, 255)         # right tenth blue
    cells = classic.grid_colours(f, "dominant", 10, 5)
    assert len(cells) == 50
    assert all(cells[r * 10].r == 255 and cells[r * 10].b == 0 for r in range(5))
    assert all(cells[r * 10 + 9].b == 255 and cells[r * 10 + 9].r == 0 for r in range(5))
    assert classic.cell_of((0.0, 0.4, 0.25, 0.6), 10, 5) == 20   # left edge zone -> left column
    assert classic.cell_of((0.75, 0.4, 1.0, 0.6), 10, 5) == 29   # right edge zone -> right column
    bars = classic.segment_cells({"segments": 10, "layout": "bars", "reverse": False}, 10, 5)
    assert bars == [0, 10, 20, 30, 40, 9, 19, 29, 39, 49]
    around = classic.segment_cells({"segments": 40, "layout": "whole", "reverse": False}, 10, 5)
    assert len(set(around)) > 15                                 # many different parts


def test_segment_colours_stay_strong_in_dark_parts():
    # a dark red part on an otherwise bright screen: still clearly red, not grey and not off
    dark_red = classic.strengthen(classic.FrameColor(60, 10, 10, 15.0), 3)
    r, g, b = classic.segment_light(dark_red, 70.0, 2)
    assert r > 120 and g < 10 and b < 10
