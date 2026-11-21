"""Where on the screen each segment of a light takes its colour from.

A zone is a rectangle ``(x0, y0, x1, y1)`` in normalised screen coordinates
(0..1, origin top left). Layouts describe how a light is mounted.
"""

from __future__ import annotations

Rect = tuple[float, float, float, float]

LAYOUTS: dict[str, str] = {
    "whole": "Whole screen",
    "columns": "Columns, left to right",
    "top": "Top edge, left to right",
    "bottom": "Bottom edge, left to right",
    "left": "Left edge, bottom to top",
    "right": "Right edge, bottom to top",
    "u_shape": "Left, top, right (TV backlight)",
    "around": "All four edges, clockwise from bottom left",
}

SCREEN_ASPECT = 16 / 9


def _split(n: int) -> list[tuple[float, float]]:
    return [(i / n, (i + 1) / n) for i in range(n)]


def _edges_layout(n: int, edges: list[str], depth: float) -> list[Rect]:
    """Distribute n segments along a path of edges, proportional to their length."""
    lengths = {"left": 1.0, "right": 1.0, "top": SCREEN_ASPECT, "bottom": SCREEN_ASPECT}
    total = sum(lengths[e] for e in edges)
    counts = [max(1, round(n * lengths[e] / total)) for e in edges]
    # fix rounding so the counts add up to n
    while sum(counts) > n:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < n:
        counts[counts.index(min(counts))] += 1
    rects: list[Rect] = []
    for edge, count in zip(edges, counts):
        if count <= 0:
            continue
        rects.extend(_edge(edge, count, depth, along_path=True))
    return rects


def _edge(edge: str, n: int, depth: float, along_path: bool = False) -> list[Rect]:
    """Segments of one edge. On a clockwise path left goes up, top goes right,
    right goes down and bottom goes left."""
    parts = _split(n)
    if edge == "top":
        return [(a, 0.0, b, depth) for a, b in parts]
    if edge == "bottom":
        rects = [(a, 1.0 - depth, b, 1.0) for a, b in parts]
        return rects[::-1] if along_path else rects
    if edge == "left":
        return [(0.0, 1.0 - b, depth, 1.0 - a) for a, b in parts]
    if edge == "right":
        rects = [(1.0 - depth, 1.0 - b, 1.0, 1.0 - a) for a, b in parts]
        return rects[::-1] if along_path else rects
    raise ValueError(edge)


def layout_rects(layout: str, segments: int, depth: float = 0.18, reverse: bool = False) -> list[Rect]:
    n = max(1, int(segments))
    depth = min(0.5, max(0.02, depth))
    if layout == "whole" or n == 1 and layout not in ("top", "bottom", "left", "right"):
        rects = [(0.0, 0.0, 1.0, 1.0)] * n
    elif layout == "columns":
        rects = [(a, 0.0, b, 1.0) for a, b in _split(n)]
    elif layout in ("top", "bottom", "left", "right"):
        rects = _edge(layout, n, depth)
    elif layout == "u_shape":
        rects = _edges_layout(n, ["left", "top", "right"], depth)
    elif layout == "around":
        rects = _edges_layout(n, ["left", "top", "right", "bottom"], depth)
    else:
        raise ValueError(f"unknown layout {layout!r}")
    return rects[::-1] if reverse else list(rects)
