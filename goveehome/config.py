"""Settings stored as JSON in $XDG_CONFIG_HOME/goveehome/config.json."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_VERSION = 4

DEFAULTS: dict = {
    "version": CONFIG_VERSION,
    "cloud_api_key": "",
    "extra_hosts": [],            # IPs to scan directly when multicast is blocked
    "bluetooth": False,
    "rescan_interval": 30,        # seconds, 0 disables background rescans
    "devices": {},                # device id -> cached Device.to_cache()
    "device_settings": {},        # device id -> per device overrides, see device_settings()
    "gamma": 2.0,                 # LED gamma used by all light shows, 1.0 = off
    "sync": {
        "backend": "auto",
        "fps": 30,
        "smoothing": 0.04,        # seconds, 0 = instant
        "saturation": 1.15,
        "brightness": 1.0,
        "mode": "vivid",          # see sync.colors.MODES
        "edge_depth": 0.25,       # fraction of the screen used for edge zones
        "monitor": 1,             # X11 only: 0 = all monitors, 1.. = one monitor
        "black_level": 8,         # colours darker than this are sent as black
        "letterbox": True,        # ignore black bars of films
        "follow_video": True,     # fit the zones onto a video playing in a window
        "auto_boost": True,       # bring back colour when the capture is washed out
        "vividness": 4.0,         # 1 = colours as on screen, higher = purer light colours
        "channel_order": [0, 1, 2],  # fixes captures with swapped colour channels (see capture.calibrate)
        "restore_on_stop": True,
    },
    "music": {
        "mode": "spectrum",
        "palette": "rainbow",
        "colors": ["#ff0050", "#00b4ff", "#ffd200"],   # for the "custom" palette
        "sensitivity": 1.0,
        "brightness": 1.0,
        "fps": 40,
    },
    "effects": {
        "effect": "rainbow",
        "speed": 1.0,
        "brightness": 1.0,
        "color_a": "#ff5a00",
        "color_b": "#0050ff",
        "color_c": "#ff008c",
        "size": 0.3,              # width of moving parts (meteor, scanner, waves)
        "reverse": False,
        "fps": 30,
    },
    "groups": [],                 # [{"id": ..., "name": ..., "members": [device ids]}]
    "favorite_colors": [],        # ["#rrggbb", ...]
    "background": {
        "keep_running": True,     # keep a running light show going when the window closes
        "autostart": False,
        "resume_show": False,     # start the last light show again on launch
        "last_show": "",
        "resume_once": "",        # light show to start again after a restart for an update
    },
    "power": {
        "off_on_sleep": False,
        "on_on_wake": False,
    },
    "updates": {
        "auto_check": True,       # look for a new version on GitHub once a day
        "last_check": 0,
        "skipped": "",            # commit the user chose to skip
    },
    "portal_restore_token": "",
}

DEVICE_DEFAULTS: dict = {
    "name": "",
    "sync": True,                 # take part in screen sync
    "music": True,                # take part in music sync
    "effects": True,              # take part in effects
    "segments": None,             # None = model default
    "streaming": None,            # None = model default
    "layout": None,               # None = model default
    "reverse": False,
    "gradient": True,
    "gains": [1.0, 1.0, 1.0],     # white balance for light shows
}


def _migrate(raw: dict) -> dict:
    if raw.get("version", 1) < 2 and isinstance(raw.get("sync"), dict):
        # 1.0 used a per-frame smoothing factor and sent colours without gamma;
        # its tuning values don't carry over, keep only the structural ones.
        old = raw["sync"]
        raw["sync"] = {k: old[k] for k in ("backend", "restore_on_stop") if k in old}
    if raw.get("version", 1) < 3 and isinstance(raw.get("sync"), dict):
        # 1.3 averaged zones exactly and only looked at a thin strip at the
        # screen edges, which turns lights white on ordinary desktops
        if raw["sync"].get("mode") in (None, "accurate"):
            raw["sync"]["mode"] = "vivid"
        if raw["sync"].get("edge_depth", 0.15) <= 0.15:
            raw["sync"]["edge_depth"] = 0.25
    raw["version"] = CONFIG_VERSION
    return raw


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "goveehome"


def _merge(defaults: dict, values: dict) -> dict:
    out = copy.deepcopy(defaults)
    for key, value in (values or {}).items():
        if isinstance(out.get(key), dict) and isinstance(value, dict) and key not in ("devices", "device_settings"):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self._lock = threading.RLock()
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text())
            except FileNotFoundError:
                raw = {}
            except (OSError, ValueError) as exc:
                log.warning("Ignoring unreadable config %s: %s", self.path, exc)
                raw = {}
            self.data = _merge(DEFAULTS, _migrate(raw))

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True))
            os.chmod(tmp, 0o600)  # holds the API key
            tmp.replace(self.path)

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, save: bool = True) -> None:
        with self._lock:
            self.data[key] = value
            if save:
                self.save()

    @property
    def sync(self) -> dict:
        return self.data["sync"]

    def section(self, name: str) -> dict:
        return self.data[name]

    def set_in(self, section: str, key: str, value, save: bool = True) -> None:
        with self._lock:
            self.data[section][key] = value
            if save:
                self.save()

    def set_sync(self, key: str, value, save: bool = True) -> None:
        with self._lock:
            self.data["sync"][key] = value
            if save:
                self.save()

    def device_settings(self, device_id: str) -> dict:
        stored = self.data["device_settings"].get(device_id, {})
        return copy.deepcopy({**DEVICE_DEFAULTS, **stored})

    def update_device_settings(self, device_id: str, save: bool = True, **changes) -> None:
        with self._lock:
            entry = self.data["device_settings"].setdefault(device_id, {})
            entry.update(changes)
            if save:
                self.save()
