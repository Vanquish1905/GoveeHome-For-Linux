"""Govee developer cloud API (v1, "router" API).

Used for lights that don't support LAN control and for things only the cloud
knows about: the device list with names from the phone app, and scenes.
Requires a free API key, which Govee e-mails you after requesting it in the
phone app (Profile -> Settings -> Apply for API Key).

The cloud is rate limited (10 000 requests per day per key), so it is never
used for screen sync.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid

from goveehome.colors import RGB, rgb_to_int, int_to_rgb

log = logging.getLogger(__name__)

BASE_URL = "https://openapi.api.govee.com/router/api/v1"
TIMEOUT = 10

CAP_ON_OFF = "devices.capabilities.on_off"
CAP_RANGE = "devices.capabilities.range"
CAP_COLOR = "devices.capabilities.color_setting"
CAP_SCENE = "devices.capabilities.dynamic_scene"


class CloudError(Exception):
    pass


def parse_state(capabilities: list[dict]) -> dict:
    """Map the capability list of a /device/state reply to DeviceState kwargs."""
    out: dict = {}
    for cap in capabilities or []:
        instance = cap.get("instance")
        value = (cap.get("state") or {}).get("value")
        if value in (None, ""):
            continue
        if instance == "powerSwitch":
            out["on"] = bool(value)
        elif instance == "brightness":
            out["brightness"] = int(value)
        elif instance == "colorRgb":
            out["color"] = int_to_rgb(int(value))
        elif instance == "colorTemperatureK":
            out["kelvin"] = int(value)
    return out


class CloudClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, opener=None):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self._open = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Govee-API-Key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "goveehome-linux",
            },
        )
        try:
            with self._open(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise CloudError("The API key was rejected") from exc
            if exc.code == 429:
                raise CloudError("Too many cloud requests, try again later") from exc
            raise CloudError(f"Cloud request failed ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError(f"Cannot reach the Govee cloud: {exc}") from exc
        except ValueError as exc:
            raise CloudError("Unexpected reply from the Govee cloud") from exc
        code = payload.get("code", 200)
        if code != 200:
            raise CloudError(payload.get("message") or f"Cloud error {code}")
        return payload

    @staticmethod
    def _envelope(sku: str, device: str, **extra) -> dict:
        return {"requestId": str(uuid.uuid4()), "payload": {"sku": sku, "device": device, **extra}}

    def list_devices(self) -> list[dict]:
        return list(self._request("GET", "/user/devices").get("data") or [])

    def get_state(self, sku: str, device: str) -> dict:
        reply = self._request("POST", "/device/state", self._envelope(sku, device))
        caps = ((reply.get("payload") or {}).get("capabilities")) or []
        return parse_state(caps)

    def control(self, sku: str, device: str, cap_type: str, instance: str, value) -> None:
        self._request("POST", "/device/control", self._envelope(
            sku, device, capability={"type": cap_type, "instance": instance, "value": value}))

    def turn(self, sku: str, device: str, on: bool) -> None:
        self.control(sku, device, CAP_ON_OFF, "powerSwitch", 1 if on else 0)

    def brightness(self, sku: str, device: str, value: int) -> None:
        self.control(sku, device, CAP_RANGE, "brightness", max(1, min(100, int(value))))

    def color(self, sku: str, device: str, rgb: RGB) -> None:
        self.control(sku, device, CAP_COLOR, "colorRgb", rgb_to_int(rgb))

    def kelvin(self, sku: str, device: str, kelvin: int) -> None:
        self.control(sku, device, CAP_COLOR, "colorTemperatureK", int(kelvin))

    def scenes(self, sku: str, device: str) -> list[dict]:
        """Return [{'name': ..., 'value': {...}}] usable with set_scene()."""
        reply = self._request("POST", "/device/scenes", self._envelope(sku, device))
        out = []
        for cap in (reply.get("payload") or {}).get("capabilities") or []:
            if cap.get("instance") != "lightScene":
                continue
            for option in (cap.get("parameters") or {}).get("options") or []:
                if "name" in option and "value" in option:
                    out.append({"name": option["name"], "value": option["value"]})
        return out

    def set_scene(self, sku: str, device: str, value) -> None:
        self.control(sku, device, CAP_SCENE, "lightScene", value)
