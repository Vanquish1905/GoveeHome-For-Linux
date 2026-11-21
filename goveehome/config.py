"""Settings stored as JSON in $XDG_CONFIG_HOME/goveehome/config.json."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "cloud_api_key": "",
    "extra_hosts": [],            # IPs to scan directly when multicast is blocked
    "bluetooth": False,
    "rescan_interval": 30,        # seconds, 0 disables background rescans
    "devices": {},                # device id -> cached Device.to_cache()
    "device_settings": {},        # device id -> per device overrides, see device_settings()
    "sync": {
        "backend": "auto",
        "fps": 20,
        "smoothing": 0.5,         # 0 = instant, 1 = very slow
        "saturation": 1.3,
        "brightness": 1.0,
        "mode": "vivid",          # "average" or "vivid"
        "edge_depth": 0.18,       # fraction of the screen used for edge zones
        "monitor": 0,             # 0 = all monitors / whatever the portal picked
        "black_level": 6,         # colours darker than this are sent as black
        "restore_on_stop": True,
    },
    "portal_restore_token": "",
}

DEVICE_DEFAULTS: dict = {
    "name": "",
    "sync": True,                 # take part in screen sync
    "segments": None,             # None = model default
    "streaming": None,            # None = model default
    "layout": None,               # None = model default
    "reverse": False,
    "gradient": True,
}


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
            self.data = _merge(DEFAULTS, raw)

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

    def set_sync(self, key: str, value, save: bool = True) -> None:
        with self._lock:
            self.data["sync"][key] = value
            if save:
                self.save()

    def device_settings(self, device_id: str) -> dict:
        stored = self.data["device_settings"].get(device_id, {})
        return {**DEVICE_DEFAULTS, **stored}

    def update_device_settings(self, device_id: str, save: bool = True, **changes) -> None:
        with self._lock:
            entry = self.data["device_settings"].setdefault(device_id, {})
            entry.update(changes)
            if save:
                self.save()
