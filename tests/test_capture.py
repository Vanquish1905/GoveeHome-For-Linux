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


class Frames:
    """Fake backend handing out a fixed list of frames."""
    label = "fake"

    def __init__(self, frames):
        self.frames = list(frames)

    def open(self):
        pass

    def close(self):
        pass

    def grab(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def _screen_source(frames, tmp_path):
    from goveehome.config import Config
    from goveehome.sync.engine import ScreenSource
    config = Config(tmp_path / "c.json")
    src = ScreenSource(config, backend_factory=lambda name: Frames(frames))
    src.open()
    return src


def test_single_black_glitch_frames_are_ignored(tmp_path):
    from goveehome.models import Device
    from goveehome.sync.colors import Smoother
    from goveehome.sync.engine import Target
    red = np.zeros((90, 160, 3), np.uint8)
    red[:] = (200, 0, 0)
    black = np.zeros((90, 160, 3), np.uint8)
    src = _screen_source([red, black, red, black, black, black, black], tmp_path)
    t = [Target(Device("a"), {}, [(0, 0, 1, 1)], np.array([0.5]), Smoother())]
    seen = [src.render(t, i / 30)["a"][0][0] for i in range(7)]
    assert min(seen[:4]) > 150          # the lone black frame was skipped
    assert seen[-1] == 0                # a real fade to black still comes through


gst_ok = pytest.mark.skipif(
    not __import__("goveehome.capture.gst", fromlist=["x"]).has_element("videotestsrc"),
    reason="GStreamer test source not installed")


@gst_ok
def test_gstreamer_pipeline_delivers_true_colours():
    from goveehome.capture.gst import GstCapture

    class Test(GstCapture):
        label = "test"

        def source_description(self):
            return "videotestsrc name=src pattern=red is-live=true ! video/x-raw,width=1920,height=1080"

    cap = Test()
    cap.open()
    try:
        frame = None
        for _ in range(30):
            frame = cap.grab()
            if frame.max() > 0:
                break
    finally:
        cap.close()
    assert frame.shape == (90, 160, 3)
    assert frame[..., 0].min() > 240 and frame[..., 1].max() < 15 and frame[..., 2].max() < 15


@gst_ok
def test_pipeline_falls_back_when_the_preferred_format_is_refused():
    """Like a compositor that can't hand out plain RGB: the second variant must take over."""
    from goveehome.capture.gst import GstCapture

    class YuvOnly(GstCapture):
        label = "test"

        def source_description(self):
            return ("videotestsrc name=src pattern=blue is-live=true ! "
                    "video/x-raw,format=I420,width=1280,height=720")

        def source_variants(self):
            return ["video/x-raw,format={ BGRx, RGBx }", ""]

    cap = YuvOnly()
    cap.open()
    try:
        frame = cap.grab()
        for _ in range(20):
            if frame.max() > 0:
                break
            frame = cap.grab()
    finally:
        cap.close()
    assert cap.variant == "fallback"
    assert frame[..., 2].mean() > 200 and frame[..., 0].mean() < 30
    assert "I420" in cap.source_format


def test_capture_colour_order_detection():
    from goveehome.capture import calibrate
    ok = {"red": (240, 10, 5), "green": (8, 230, 12), "blue": (4, 9, 250)}
    assert calibrate.best_order(ok)[0] == (0, 1, 2)
    swapped = {"red": (5, 10, 240), "green": (8, 230, 12), "blue": (250, 9, 4)}   # KWin bug
    order, message = calibrate.best_order(swapped)
    assert order == (2, 1, 0) and "red and blue" in message
    frame = np.zeros((4, 4, 3), np.uint8)
    frame[..., 2] = 200                                    # "blue" in the capture = red on screen
    fixed = calibrate.apply_order(frame, order)
    assert fixed[0, 0].tolist() == [200, 0, 0]
    unclear = {"red": (120, 110, 115), "green": (8, 230, 12), "blue": (4, 9, 250)}
    assert calibrate.best_order(unclear)[0] is None


def test_capture_check_end_to_end_with_a_swapping_capture():
    """A fake capture that swaps red and blue, like the KWin bug."""
    from goveehome.capture import calibrate
    screen = {"rgb": (0, 0, 0)}

    class Swapping:
        def grab(self):
            f = np.zeros((90, 160, 3), np.uint8)
            f[:] = screen["rgb"]
            return f[..., ::-1].copy()

    measured = calibrate.measure(Swapping(), lambda rgb: screen.update(rgb=rgb or (0, 0, 0)), settle=0.01)
    order, _ = calibrate.best_order(measured)
    assert order == (2, 1, 0)
    screen["rgb"] = (255, 120, 0)                          # orange on screen
    assert calibrate.apply_order(Swapping().grab(), order)[0, 0].tolist() == [255, 120, 0]
