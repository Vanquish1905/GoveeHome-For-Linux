import pytest

from goveehome.sync.zones import LAYOUTS, layout_rects


@pytest.mark.parametrize("layout", list(LAYOUTS))
@pytest.mark.parametrize("n", [1, 2, 7, 10, 15])
def test_every_layout_gives_n_valid_rects(layout, n):
    rects = layout_rects(layout, n)
    assert len(rects) == n
    for x0, y0, x1, y1 in rects:
        assert 0 <= x0 < x1 <= 1
        assert 0 <= y0 < y1 <= 1


def test_columns_go_left_to_right():
    rects = layout_rects("columns", 4)
    assert [r[0] for r in rects] == [0, 0.25, 0.5, 0.75]


def test_left_goes_bottom_to_top():
    rects = layout_rects("left", 3, depth=0.2)
    assert rects[0][3] == 1.0 and rects[-1][1] == 0.0
    assert all(r[2] == 0.2 for r in rects)


def test_u_shape_path_is_continuous():
    rects = layout_rects("u_shape", 10)
    # starts bottom left, ends bottom right
    assert rects[0][0] == 0.0 and rects[0][3] == 1.0
    assert rects[-1][2] == 1.0 and rects[-1][3] == 1.0
    # the top edge holds the most segments (it is the longest side)
    top = [r for r in rects if r[1] == 0.0 and r[2] - r[0] < 1 and r[3] < 0.5]
    assert len(top) >= 3


def test_reverse():
    assert layout_rects("columns", 3, reverse=True) == layout_rects("columns", 3)[::-1]


def test_unknown_layout():
    with pytest.raises(ValueError):
        layout_rects("spiral", 3)


def test_bars_left_and_right_top_to_bottom():
    rects = layout_rects("bars", 12, depth=0.15)
    left, right = rects[:6], rects[6:]
    assert all(r[0] == 0.0 for r in left) and all(r[2] == 1.0 for r in right)
    assert left[0][1] == 0.0 and left[-1][3] == 1.0          # first segment at the top
    swapped = layout_rects("bars_swapped", 12, depth=0.15)
    assert swapped[:6] == right and swapped[6:] == left


def test_bars_reverse_keeps_the_sides():
    rects = layout_rects("bars", 12, reverse=True)
    assert all(r[0] == 0.0 for r in rects[:6]) and rects[0][3] == 1.0


def test_bars_above_and_below():
    rects = layout_rects("bars_top_bottom", 10, depth=0.2)
    assert all(r[1] == 0.0 for r in rects[:5]) and all(r[3] == 1.0 for r in rects[5:])
