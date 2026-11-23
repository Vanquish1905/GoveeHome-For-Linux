"""What you paint on a light: saved segment colours (presets) and animations.

Both are stored in the config and can be played on any light as an effect,
and exported to / imported from a JSON file to keep or share them.

Preset:    {"name": "Sunset", "colours": ["#ff2a00", ...]}
Animation: {"id": "a1b2c3d4", "name": "Police", "frames": [["#ff0000", ...], ...],
            "frame_time": 0.5, "fade": True, "mode": "loop" | "bounce"}

Segments without a colour are stored as null and shown dark.
"""

from __future__ import annotations

import json
import uuid

import numpy as np

from goveehome.colors import parse_color, to_hex

FILE_KIND = "goveehome-paintings"
FILE_VERSION = 1
MODES = {"loop": "Loop", "bounce": "Back and forth"}
MAX_FRAMES = 120


def new_animation(name: str, frames: list | None = None) -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name, "frames": frames or [],
            "frame_time": 0.5, "fade": True, "mode": "loop"}


def _hex_list(values) -> list[str | None]:
    out = []
    for v in values:
        if v is None:
            out.append(None)
        elif isinstance(v, str):
            out.append(to_hex(parse_color(v)))
        else:
            out.append(to_hex(tuple(int(c) for c in v)))
    return out


def clean_preset(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("a preset must be an object")
    name = str(raw.get("name") or "").strip()
    colours = raw.get("colours", raw.get("colors"))
    if not name or not isinstance(colours, list) or not colours:
        raise ValueError("a preset needs a name and colours")
    return {"name": name[:60], "colours": _hex_list(colours[:256])}


def clean_animation(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("an animation must be an object")
    name = str(raw.get("name") or "").strip()
    frames = raw.get("frames")
    if not name or not isinstance(frames, list) or not frames:
        raise ValueError("an animation needs a name and frames")
    frames = [_hex_list(f[:256]) for f in frames[:MAX_FRAMES] if isinstance(f, list) and f]
    if not frames:
        raise ValueError("an animation needs frames")
    mode = raw.get("mode") if raw.get("mode") in MODES else "loop"
    return {"id": str(raw.get("id") or uuid.uuid4().hex[:8])[:16], "name": name[:60], "frames": frames,
            "frame_time": min(30.0, max(0.05, float(raw.get("frame_time", 0.5)))),
            "fade": bool(raw.get("fade", True)), "mode": mode}


def unique_name(name: str, taken) -> str:
    taken = set(taken)
    if name not in taken:
        return name
    i = 2
    while f"{name} ({i})" in taken:
        i += 1
    return f"{name} ({i})"


# files ---------------------------------------------------------------------------------
def export_data(config, presets: list[str] | None = None, animations: list[str] | None = None) -> dict:
    """Everything (or the named presets / animation ids) as a dict ready for JSON."""
    p = [x for x in config.get("segment_presets") or [] if presets is None or x["name"] in presets]
    a = [x for x in config.get("animations") or [] if animations is None or x["id"] in animations]
    return {"kind": FILE_KIND, "version": FILE_VERSION, "presets": p, "animations": a}


def export_json(config, **kw) -> str:
    return json.dumps(export_data(config, **kw), indent=2)


def import_data(config, data) -> tuple[int, int]:
    """Add the presets and animations from an exported file. Returns how many of each.

    Also takes a single preset or animation, or a plain list of colours. Names that
    already exist get a number, nothing is overwritten.
    """
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise ValueError("this isn't a GoveeHome paintings file") from exc
    if isinstance(data, list):
        data = {"presets": [{"name": "Imported", "colours": data}]}
    if not isinstance(data, dict):
        raise ValueError("this isn't a GoveeHome paintings file")
    if "frames" in data:
        data = {"animations": [data]}
    elif "colours" in data or "colors" in data:
        data = {"presets": [data]}
    if not data.get("presets") and not data.get("animations"):
        raise ValueError("the file has no presets or animations")

    presets = list(config.get("segment_presets") or [])
    animations = list(config.get("animations") or [])
    added_p = added_a = 0
    for raw in data.get("presets") or []:
        preset = clean_preset(raw)
        preset["name"] = unique_name(preset["name"], [x["name"] for x in presets])
        presets.append(preset)
        added_p += 1
    for raw in data.get("animations") or []:
        anim = clean_animation(raw)
        anim["name"] = unique_name(anim["name"], [x["name"] for x in animations])
        if anim["id"] in {x["id"] for x in animations}:
            anim["id"] = uuid.uuid4().hex[:8]
        animations.append(anim)
        added_a += 1
    config.set("segment_presets", presets, save=False)
    config.set("animations", animations)
    return added_p, added_a


# playing ---------------------------------------------------------------------------------
def frame_array(frame, dark=(0, 0, 0)) -> np.ndarray:
    return np.array([parse_color(c) if c else dark for c in frame], dtype=np.float32)


def sample(frame: np.ndarray, x: np.ndarray) -> np.ndarray:
    """The painted segment under each position (0..1) of another light."""
    idx = np.clip((np.asarray(x) * len(frame)).astype(np.int32), 0, len(frame) - 1)
    return frame[idx]


def sequence(count: int, mode: str) -> list[int]:
    if mode == "bounce" and count > 2:
        return list(range(count)) + list(range(count - 2, 0, -1))
    return list(range(count))


_cache: dict[str, tuple] = {}


def _frames(anim: dict) -> list[np.ndarray]:
    key = tuple(tuple(f) for f in anim["frames"])
    hit = _cache.get(anim.get("id", ""))
    if hit is not None and hit[0] == key:
        return hit[1]
    frames = [frame_array(f) for f in anim["frames"]] or [np.zeros((1, 3), np.float32)]
    if len(_cache) > 64:
        _cache.clear()
    _cache[anim.get("id", "")] = (key, frames)
    return frames


def shifted_frames(colours: list, step: int = 1) -> list[list]:
    """Frames that move the colours along the light, one segment per frame, until it repeats."""
    n = len(colours)
    if n == 0:
        return []
    out = []
    for k in range(0, n, max(1, step)):
        out.append(colours[-k:] + colours[:-k] if k else list(colours))
    return out


def render_animation(anim: dict, x: np.ndarray, t: float, speed: float = 1.0) -> np.ndarray:
    frames = _frames(anim)
    order = sequence(len(frames), anim.get("mode", "loop"))
    pos = t * max(0.05, speed) / max(0.05, float(anim.get("frame_time", 0.5)))
    i = int(np.floor(pos)) % len(order)
    current = sample(frames[order[i]], x)
    if not anim.get("fade", True) or len(order) == 1:
        return current
    nxt = sample(frames[order[(i + 1) % len(order)]], x)
    f = pos - np.floor(pos)
    f = f * f * (3 - 2 * f)
    return current + (nxt - current) * f


def render_preset(colours, x: np.ndarray) -> np.ndarray:
    return sample(frame_array(colours), x)
