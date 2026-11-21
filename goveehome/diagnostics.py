"""A plain text report about screen sync, to paste into a bug report.

Contains versions, the desktop, how the screen is captured, how colourful
the captured picture is and what each light is being sent. No API key, no
account data.
"""

from __future__ import annotations

import os
import platform
import sys
import time

import numpy as np

from goveehome import __version__


def _gst_version() -> str:
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        return Gst.version_string()
    except Exception:
        return "not available"


def _os_name() -> str:
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def header() -> list[str]:
    return [
        f"GoveeHome {__version__}",
        f"System: {_os_name()}",
        f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')} "
        f"({os.environ.get('XDG_SESSION_TYPE', '?')})",
        f"Python {sys.version.split()[0]}, {_gst_version()}",
    ]


def colour_stats(frame: np.ndarray) -> str:
    px = frame.reshape(-1, 3).astype(np.float32)
    mx = px.max(axis=1)
    sat = (mx - px.min(axis=1)) / np.maximum(mx, 1.0)
    lit = sat[mx > 40]
    p90 = float(np.percentile(lit, 90)) if len(lit) > 10 else 0.0
    mean = px.mean(axis=0)
    return (f"average colour {tuple(int(v) for v in mean)}, "
            f"{((sat > 0.25) & (mx > 30)).mean() * 100:.0f} % colourful, "
            f"saturation of the most colourful tenth {p90:.2f}")


def light_lines(manager, sent: dict | None = None) -> list[str]:
    lines = []
    for d in manager.list():
        s = manager.stream_settings(d)
        mode = f"{s['segments']} segments streamed" if s["streaming"] else "single colour"
        lines.append(f"- {d.sku or '?'} '{d.display_name}': {', '.join(t.value for t in d.transports) or 'offline'}, "
                     f"{mode}, mounting {s['layout']}, reverse {s['reverse']}, screen sync {s.get('sync', True)}")
        if sent and d.id in sent:
            cols = sent[d.id]
            lines.append(f"    now getting: {' '.join('#%02x%02x%02x' % tuple(c) for c in cols[:15])}")
    return lines or ["- no lights found"]


def report_from_engine(app_engine, manager) -> str:
    """Report while screen sync runs in the app."""
    lines = header()
    src = getattr(app_engine, "source", None)
    lines.append("")
    lines.append("Screen sync: " + ("running" if app_engine.running else "not running"))
    if src is not None:
        backend = getattr(src, "backend", None)
        lines.append(f"Capture: {getattr(backend, 'label', '?')}, {getattr(backend, 'source_format', '') or '?'}"
                     f" ({getattr(backend, 'variant', '') or 'n/a'})")
        if src.frame is not None:
            lines.append("Picture: " + colour_stats(src.frame))
        lines.append(f"Details: {getattr(src, 'details', '')}")
    sync = manager.config.sync
    lines.append(f"Settings: pick {sync.get('mode')}, saturation {sync.get('saturation'):.2f}, "
                 f"gamma {manager.config.get('gamma', 2.0):.2f}, follow video {sync.get('follow_video')}, "
                 f"colour boost {sync.get('auto_boost')}, edge depth {sync.get('edge_depth'):.2f}")
    lines.append("")
    lines.append("Lights:")
    sent = {t.device.id: t.last_colors for t in getattr(app_engine, "targets", [])}
    lines += light_lines(manager, sent)
    return "\n".join(lines)


def run_capture_check(config, seconds: float = 4.0, log=print) -> str:
    """Capture the screen for a few seconds on its own and describe what comes in."""
    from goveehome.sync.engine import ScreenSource
    lines = header()
    src = ScreenSource(config)
    try:
        src.open()
    except Exception as exc:
        lines.append(f"Capture could not start: {exc}")
        return "\n".join(lines)
    backend = src.backend
    log("Capturing for a few seconds, keep something colourful on the screen…")
    frames = 0
    end = time.monotonic() + seconds
    last = None
    try:
        while time.monotonic() < end:
            last = backend.grab()
            frames += 1
    finally:
        src.close()
    lines.append(f"Capture: {backend.label}, {getattr(backend, 'source_format', '') or '?'} "
                 f"({getattr(backend, 'variant', '') or 'n/a'}), {frames / seconds:.0f} frames/s")
    from goveehome.sync.engine import kde_hdr_enabled
    hdr = kde_hdr_enabled()
    if hdr is not None:
        lines.append(f"KDE HDR: {'on' if hdr else 'off'}")
    if last is not None:
        lines.append("Picture: " + colour_stats(last))
        h, w = last.shape[:2]
        cells = []
        for y in (0, h // 2, h - 1):
            row = []
            for x in (0, w // 2, w - 1):
                row.append("#%02x%02x%02x" % tuple(int(v) for v in last[y, x]))
            cells.append(" ".join(row))
        lines.append("Corners and middle: " + " | ".join(cells))
    return "\n".join(lines)
