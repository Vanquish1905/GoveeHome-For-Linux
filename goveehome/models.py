"""Data types describing a light and what we know about it."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from goveehome.colors import RGB


class Transport(str, Enum):
    LAN = "lan"
    BLE = "ble"
    CLOUD = "cloud"

    @property
    def label(self) -> str:
        return {"lan": "Wi-Fi (LAN)", "ble": "Bluetooth", "cloud": "Cloud"}[self.value]


@dataclass
class DeviceState:
    on: bool | None = None
    brightness: int | None = None      # 1 - 100
    color: RGB | None = None
    kelvin: int | None = None          # 0 when in colour mode
    updated: float = 0.0

    def merge(self, **changes) -> None:
        for key, value in changes.items():
            if value is not None:
                setattr(self, key, value)
        self.updated = time.time()


@dataclass
class Device:
    id: str                             # Govee device id (looks like a MAC)
    sku: str = ""
    name: str = ""
    ip: str | None = None
    ble_address: str | None = None
    cloud: bool = False
    cloud_capabilities: list = field(default_factory=list)
    state: DeviceState = field(default_factory=DeviceState)
    last_seen: float = 0.0

    @property
    def display_name(self) -> str:
        return self.name or self.sku or self.id

    @property
    def transports(self) -> list[Transport]:
        out = []
        if self.ip:
            out.append(Transport.LAN)
        if self.ble_address:
            out.append(Transport.BLE)
        if self.cloud:
            out.append(Transport.CLOUD)
        return out

    @property
    def preferred_transport(self) -> Transport | None:
        t = self.transports
        return t[0] if t else None

    @property
    def can_stream(self) -> bool:
        """True when the device is reachable fast enough for screen sync."""
        return bool(self.ip or self.ble_address)

    def has_capability(self, instance: str) -> bool:
        return any(c.get("instance") == instance for c in self.cloud_capabilities)

    def to_cache(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "ip": self.ip,
            "ble_address": self.ble_address,
            "cloud": self.cloud,
        }

    @classmethod
    def from_cache(cls, device_id: str, data: dict) -> "Device":
        return cls(
            id=device_id,
            sku=data.get("sku", ""),
            name=data.get("name", ""),
            ip=data.get("ip"),
            ble_address=data.get("ble_address"),
            cloud=bool(data.get("cloud", False)),
        )
