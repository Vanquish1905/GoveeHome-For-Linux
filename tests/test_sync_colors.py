import numpy as np
import pytest

from goveehome.sync import colors as sc


def frame_with(color_left, color_right, w=40, h=20):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, : w // 2] = color_left
    f[:, w // 2:] = color_right
    return f


def test_extract_columns_keeps_pure_colours():
    f = frame_with((255, 0, 0), (0, 0, 255))
    out = sc.extract(f, [(0, 0, 0.5, 1), (0.5, 0, 1, 1)])
    assert np.allclose(out[0], (255, 0, 0), atol=0.5)
    assert np.allclose(out[1], (0, 0, 255), atol=0.5)


def test_mixing_happens_in_linear_light():
    # half black, half white looks like sRGB ~186, not 128
    f = frame_with((0, 0, 0), (255, 255, 255))
    out = sc.extract(f, [(0, 0, 1, 1)])[0]
    assert 180 < out[0] < 192


def test_red_and_green_mix_to_yellow_not_brown():
    f = frame_with((255, 0, 0), (0, 255, 0))
    r, g, b = sc.extract(f, [(0, 0, 1, 1)])[0]
    assert r > 180 and g > 180 and b < 5


@pytest.mark.parametrize("mode", list(sc.MODES))
def test_every_mode_handles_flat_and_black(mode):
    for value in (0, 90, 255):
        f = np.full((10, 10, 3), value, dtype=np.uint8)
        out = sc.extract(f, [(0, 0, 1, 1)], mode)[0]
        assert np.allclose(out, value, atol=1)


def test_vivid_prefers_saturated_pixels():
    f = np.full((10, 10, 3), 128, dtype=np.uint8)
    f[0, 0:4] = (255, 0, 0)
    avg = sc.extract(f, [(0, 0, 1, 1)], "accurate")[0]
    viv = sc.extract(f, [(0, 0, 1, 1)], "vivid")[0]
    assert viv[0] - viv[1] > avg[0] - avg[1] + 15


def test_dominant_picks_the_biggest_colour_area():
    f = np.zeros((10, 10, 3), dtype=np.uint8)
    f[:, :6] = (0, 0, 200)        # 60 % blue
    f[:, 6:] = (220, 0, 0)        # 40 % red
    r, g, b = sc.extract(f, [(0, 0, 1, 1)], "dominant")[0]
    assert b > 190 and r < 10


def test_dominant_on_grey_falls_back_to_mean():
    f = np.full((10, 10, 3), 77, dtype=np.uint8)
    assert np.allclose(sc.extract(f, [(0, 0, 1, 1)], "dominant")[0], 77, atol=1)


def test_tiny_zones_never_empty():
    f = np.full((9, 16, 3), 50, dtype=np.uint8)
    out = sc.extract(f, [(0.99, 0.99, 1.0, 1.0)])
    assert np.allclose(out, 50, atol=1)


def test_adjust_saturation_and_black_level():
    grey = sc.adjust(np.array([[100, 100, 100]]), saturation=2.0)
    assert np.allclose(grey, 100)
    boosted = sc.adjust(np.array([[150, 100, 100]]), saturation=2.0)
    assert boosted[0, 0] > 150 and boosted[0, 1] < 100
    dark = sc.adjust(np.array([[3, 2, 1], [50, 50, 50]]), black_level=6)
    assert dark[0].sum() == 0 and dark[1].sum() > 0


def test_led_output_gamma_and_gains():
    out = sc.led_output(np.array([[255, 128, 0]]), gamma=2.0)
    assert out[0, 0] == 255 and 60 < out[0, 1] < 70 and out[0, 2] == 0
    assert np.allclose(sc.led_output(np.array([[128, 128, 128]]), gamma=1.0), 128)
    wb = sc.led_output(np.array([[255, 255, 255]]), gamma=1.0, gains=(1.0, 0.8, 0.5))
    assert np.allclose(wb, (255, 204, 127.5))


def test_smoother_is_time_based():
    a, b = sc.Smoother(0.1), sc.Smoother(0.1)
    a(np.array([[0, 0, 0]]), 0.0)
    b(np.array([[0, 0, 0]]), 0.0)
    # 30 fps vs 60 fps for the same 0.1 s end up at the same value
    for i in range(1, 4):
        va = a(np.array([[60, 60, 60]]), i / 30)
    for i in range(1, 7):
        vb = b(np.array([[60, 60, 60]]), i / 60)
    assert abs(va[0, 0] - vb[0, 0]) < 0.5
    assert 30 < va[0, 0] < 50


def test_smoother_snaps_on_cuts_and_zero_is_instant():
    s = sc.Smoother(0.3)
    s(np.array([[0, 0, 0]]), 0.0)
    assert s(np.array([[255, 255, 255]]), 1 / 30)[0, 0] > 200
    s0 = sc.Smoother(0.0)
    s0(np.array([[0, 0, 0]]), 0.0)
    assert s0(np.array([[40, 40, 40]]), 0.01)[0, 0] == 40


def test_to_rgb_list():
    assert sc.to_rgb_list(np.array([[1.4, 254.6, -3]])) == [(1, 255, 0)]
