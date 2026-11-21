import numpy as np

from goveehome.sync import colors as sc


def frame_with(color_left, color_right, w=40, h=20):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, : w // 2] = color_left
    f[:, w // 2:] = color_right
    return f


def test_extract_columns():
    f = frame_with((255, 0, 0), (0, 0, 255))
    out = sc.extract(f, [(0, 0, 0.5, 1), (0.5, 0, 1, 1)], mode="average")
    assert np.allclose(out[0], (255, 0, 0))
    assert np.allclose(out[1], (0, 0, 255))


def test_vivid_prefers_saturated_pixels():
    f = np.full((10, 10, 3), 128, dtype=np.uint8)
    f[0, 0:2] = (255, 0, 0)
    avg = sc.average(f.reshape(-1, 3))
    viv = sc.vivid(f.reshape(-1, 3))
    assert viv[0] - viv[1] > avg[0] - avg[1] + 20


def test_vivid_on_grey_equals_average():
    f = np.full((5, 5, 3), 90, dtype=np.uint8).reshape(-1, 3)
    assert np.allclose(sc.vivid(f), sc.average(f))


def test_adjust_saturation_and_black_level():
    grey = sc.adjust(np.array([[100, 100, 100]]), saturation=2.0)
    assert np.allclose(grey, 100)
    boosted = sc.adjust(np.array([[150, 100, 100]]), saturation=2.0)
    assert boosted[0, 0] > 150 and boosted[0, 1] < 100
    dark = sc.adjust(np.array([[3, 2, 1], [50, 50, 50]]), black_level=6)
    assert dark[0].sum() == 0 and dark[1].sum() > 0


def test_smoother_converges_and_snaps_on_cuts():
    s = sc.Smoother(0.8)
    s(np.array([[0, 0, 0]]))
    small = s(np.array([[20, 20, 20]]))[0, 0]
    assert 0 < small < 20
    s.reset()
    s(np.array([[0, 0, 0]]))
    cut = s(np.array([[255, 255, 255]]))[0, 0]
    assert cut > 200  # a scene cut is followed almost immediately


def test_to_rgb_list():
    assert sc.to_rgb_list(np.array([[1.4, 254.6, -3]])) == [(1, 255, 0)]
