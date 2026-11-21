import tempfile
from pathlib import Path

import numpy as np

from goveehome.config import Config
from goveehome.models import Device
from goveehome.sync import colors as sc
from goveehome.sync.colors import Smoother
from goveehome.sync.content import FULL, ContentTracker
from goveehome.sync.engine import ScreenSource, Target
from goveehome.sync.zones import layout_rects

H, W = 90, 160


def browser_frame(i: int) -> np.ndarray:
    """A white web page with a red/blue video playing in the middle."""
    f = np.full((H, W, 3), 245, np.uint8)
    f[:8] = 60
    v = np.zeros((50, 90, 3), np.uint8)
    v[:, :45] = (200 + int(20 * np.sin(i / 3)), 40, 20)
    v[:, 45:] = (20, 70, 200 + int(20 * np.cos(i / 4)))
    v[(i * 3) % 50, :] = 255
    f[20:70, 35:125] = v
    return f


def test_tracker_finds_a_video_in_a_window():
    t = ContentTracker()
    for i in range(40):
        box = t(browser_frame(i))
    assert box == (20, 20, 35, 35)


def test_tracker_ignores_small_changes_and_falls_back_when_idle():
    t = ContentTracker(idle_frames=20)
    static = np.full((H, W, 3), 200, np.uint8)
    for i in range(30):
        f = static.copy()
        f[2:6, 150:158] = (i * 37) % 255         # a ticking clock
        assert t(f) == FULL
    for i in range(60):          # the switch itself is a full-screen change for a moment
        t(browser_frame(i))
    assert t.box != FULL
    for _ in range(25):
        t(static)                                 # video paused / closed
    assert t.box == FULL


def test_tracker_full_screen_motion_means_whole_screen():
    rng = np.random.default_rng(2)
    t = ContentTracker()
    for _ in range(30):
        box = t(rng.integers(0, 255, (H, W, 3)).astype(np.uint8))
    assert box == FULL


def test_colourful_pick_ignores_the_white_page():
    f = np.full((10, 10, 3), 245, np.uint8)
    f[:, :2] = (220, 30, 20)                      # only 20 % of the zone is red
    r, g, b = sc.extract(f, [(0, 0, 1, 1)], "vivid")[0]
    assert r > 200 and g < 120 and b < 120
    grey = np.full((10, 10, 3), 180, np.uint8)
    assert np.allclose(sc.extract(grey, [(0, 0, 1, 1)], "vivid")[0], 180, atol=1)


class Browser:
    label = "test"

    def __init__(self):
        self.i = 0

    def open(self):
        pass

    def close(self):
        pass

    def grab(self):
        self.i += 1
        return browser_frame(self.i)


def test_light_bars_show_the_video_not_white():
    """The 1.3 bug: bars beside the screen only ever showed white."""
    config = Config(Path(tempfile.mkdtemp()) / "c.json")
    src = ScreenSource(config, backend_factory=lambda name: Browser())
    src.open()
    rects = layout_rects("bars", 12, config.sync["edge_depth"])
    targets = [Target(Device("bars"), {}, rects, np.linspace(0, 1, 12), Smoother())]
    for k in range(40):
        out = src.render(targets, k / 30)["bars"]
    left, right = out[:6], out[6:]
    assert (left[:, 0] > 180).all() and (left[:, 2] < 80).all()      # red bar
    assert (right[:, 2] > 180).all() and (right[:, 0] < 80).all()    # blue bar


class Game:
    """A fullscreen scene where only part of the picture moves."""
    label = "test"

    def __init__(self):
        self.i = 0

    def open(self):
        pass

    def close(self):
        pass

    def grab(self):
        self.i += 1
        f = np.full((H, W, 3), 40, np.uint8)
        f[:, :60] = (30, 120 + int(30 * np.sin(self.i / 5)), 40)   # moving green forest, left
        f[:, 100:] = (200, 70, 20)                                    # still orange fire, right
        f[10:30, 60:100] = (235, 235, 235)                            # white sky
        return f


def test_fullscreen_picture_with_partial_movement_is_not_cropped():
    """1.4 cropped to the moving left part and gave both bars its colour."""
    config = Config(Path(tempfile.mkdtemp()) / "c.json")
    src = ScreenSource(config, backend_factory=lambda name: Game())
    src.open()
    rects = layout_rects("bars", 12, config.sync["edge_depth"])
    targets = [Target(Device("bars"), {}, rects, np.linspace(0, 1, 12), Smoother())]
    for k in range(40):
        out = src.render(targets, k / 30)["bars"]
    assert src.box == FULL
    left, right = out[:6], out[6:]
    assert (left[:, 1] > left[:, 0] + 50).all()          # green on the left
    assert (right[:, 0] > right[:, 2] + 100).all()       # orange on the right


def test_single_colour_lights_get_the_colourful_part():
    """Lights without segment streaming used to average the whole screen to grey."""
    zones = np.array([[230, 230, 230], [235, 235, 235], [40, 40, 40], [200, 70, 20]], np.float32)
    r, g, b = sc.combine(zones)[0]
    assert r > 150 and r > g * 1.5 and g > b
    greys = np.array([[200, 200, 200], [50, 50, 50]], np.float32)
    out = sc.combine(greys)[0]
    assert abs(out[0] - out[1]) < 1 and abs(out[1] - out[2]) < 1


def test_many_colours_give_a_colour_not_grey():
    """A whole-screen zone full of different colours used to come out grey."""
    from goveehome.capture.pattern import PatternCapture
    frame = PatternCapture().grab()
    for mode in ("vivid", "dominant"):
        r, g, b = sc.extract(frame, [(0, 0, 1, 1)], mode)[0]
        assert max(r, g, b) - min(r, g, b) > 150, mode
    r, g, b = sc.combine(np.array([[255, 0, 0], [0, 255, 255], [0, 255, 0], [255, 0, 255]], np.float32))[0]
    assert max(r, g, b) - min(r, g, b) > 200
