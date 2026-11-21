import numpy as np

from goveehome.sync import letterbox as lb


def film(bars=12, h=90, w=160):
    f = np.full((h, w, 3), 140, dtype=np.uint8)
    f[:bars] = 0
    f[h - bars:] = 0
    return f


def test_detects_symmetric_bars():
    assert lb.detect(film(12)) == (12, 12, 0, 0)


def test_dark_frame_is_not_cropped():
    assert lb.detect(np.zeros((90, 160, 3), np.uint8)) == (0, 0, 0, 0)


def test_one_sided_dark_area_is_not_a_bar():
    f = np.full((90, 160, 3), 140, dtype=np.uint8)
    f[:20] = 0
    assert lb.detect(f) == (0, 0, 0, 0)


def test_dark_scene_is_not_a_letterbox():
    # a gradual fade to dark at top and bottom, no clear edge
    f = np.zeros((90, 160, 3), np.uint8)
    for y in range(90):
        f[y] = int(120 * min(y, 89 - y) / 45)
    assert lb.detect(f) == (0, 0, 0, 0)


def test_asymmetric_dark_area_is_not_a_letterbox():
    f = np.full((90, 160, 3), 140, dtype=np.uint8)
    f[:10] = 0
    f[-20:] = 0
    assert lb.detect(f) == (0, 0, 0, 0)


def test_detector_waits_for_stable_bars_and_drops_them_at_once():
    d = lb.BarDetector(stable_frames=3)
    assert d(film(12)) == (0, 0, 0, 0)
    d(film(12))
    assert d(film(12)) == (12, 12, 0, 0)
    assert d(film(0)) == (0, 0, 0, 0)    # picture fills the screen again


def test_crop_and_map_back():
    f = film(12)
    box = (12, 12, 0, 0)
    assert lb.crop(f, box).shape == (66, 160, 3)
    x0, y0, x1, y1 = lb.map_rect((0, 0, 1, 1), box, f.shape)
    assert (x0, x1) == (0, 1) and abs(y0 - 12 / 90) < 1e-9 and abs(y1 - 78 / 90) < 1e-9
