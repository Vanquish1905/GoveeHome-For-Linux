import pytest

from goveehome.colors import int_to_rgb, kelvin_to_rgb, parse_color, rgb_to_int, to_hex


@pytest.mark.parametrize("text,rgb", [
    ("#ff8800", (255, 136, 0)),
    ("FF8800", (255, 136, 0)),
    ("#f80", (255, 136, 0)),
    ("red", (255, 0, 0)),
    ("255, 136, 0", (255, 136, 0)),
])
def test_parse_color(text, rgb):
    assert parse_color(text) == rgb


@pytest.mark.parametrize("bad", ["", "#12345", "300,0,0", "blurple", "1,2"])
def test_parse_color_rejects(bad):
    with pytest.raises(ValueError):
        parse_color(bad)


def test_int_round_trip():
    assert int_to_rgb(rgb_to_int((1, 2, 3))) == (1, 2, 3)
    assert to_hex((1, 2, 255)) == "#0102ff"


def test_kelvin_warm_is_red_cold_is_blue():
    warm = kelvin_to_rgb(2000)
    cold = kelvin_to_rgb(9000)
    assert warm[0] > warm[2]
    assert cold[2] >= cold[0]
