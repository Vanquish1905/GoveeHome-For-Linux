import numpy as np
import pytest

from goveehome import capture
from goveehome.capture.base import downscale
from goveehome.capture.grim import parse_ppm
from goveehome.capture.pattern import PatternCapture


def test_downscale_averages_blocks():
    f = np.zeros((180, 320, 3), dtype=np.uint8)
    f[:, 160:] = 200
    small = downscale(f, 160, 90)
    assert small.shape == (90, 160, 3)
    assert small[0, 0, 0] == 0 and small[0, -1, 0] == 200


def test_downscale_drops_alpha():
    f = np.zeros((90, 160, 4), dtype=np.uint8)
    assert downscale(f).shape == (90, 160, 3)


def test_parse_ppm_with_comment():
    pixels = bytes(range(12))
    data = b"P6\n# made by grim\n2 2\n255\n" + pixels
    img = parse_ppm(data)
    assert img.shape == (2, 2, 3)
    assert img[1, 1].tolist() == [9, 10, 11]


def test_parse_ppm_rejects_other_formats():
    with pytest.raises(capture.CaptureError):
        parse_ppm(b"P5\n1 1\n255\n\x00")


def test_pattern_backend():
    with PatternCapture() as cap:
        frame = cap.grab()
    assert frame.dtype == np.uint8 and frame.ndim == 3


def test_create_pattern_and_unknown():
    assert capture.create("pattern").id == "pattern"
    with pytest.raises(capture.CaptureError):
        capture.create("telepathy")


def test_auto_without_display(monkeypatch):
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        monkeypatch.delenv(var, raising=False)
    assert capture.available_backends() == ["pattern"]
    with pytest.raises(capture.CaptureError):
        capture.auto_backend()


def test_downscale_is_a_real_area_average():
    """Fine detail (text, 1px patterns) must average out, not alias."""
    rng = np.random.default_rng(3)
    big = np.zeros((1080, 1920, 3), dtype=np.uint8)
    big[:, :960] = (60, 0, 0)
    big[rng.random((1080, 1920)) < 0.2] = 255
    truth = big.astype(float).reshape(90, 12, 160, 12, 3).mean(axis=(1, 3))
    assert np.abs(downscale(big).astype(float) - truth).mean() < 2
