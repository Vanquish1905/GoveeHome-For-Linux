"""Govee LAN API.

Lights with "LAN Control" switched on in the phone app listen for JSON over
UDP:

* discovery: multicast ``scan`` to 239.255.255.250:4001
* replies:   the light answers on UDP port 4002 of the asking machine
* commands:  unicast to <light ip>:4003

Nothing here needs an account or internet access.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
from collections.abc import Callable, Sequence

from goveehome.colors import RGB, clamp
from goveehome.protocol import razer

log = logging.getLogger(__name__)

MULTICAST_GROUP = "239.255.255.250"
SCAN_PORT = 4001
LISTEN_PORT = 4002
CONTROL_PORT = 4003


def build_message(cmd: str, data: dict | None = None) -> bytes:
    return json.dumps({"msg": {"cmd": cmd, "data": data or {}}}, separators=(",", ":")).encode()


def parse_message(payload: bytes) -> tuple[str, dict] | None:
    try:
        msg = json.loads(payload.decode("utf-8", "replace"))["msg"]
        return str(msg["cmd"]), dict(msg.get("data") or {})
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def scan_message() -> bytes:
    return build_message("scan", {"account_topic": "reserve"})


def turn_message(on: bool) -> bytes:
    return build_message("turn", {"value": 1 if on else 0})


def brightness_message(value: int) -> bytes:
    return build_message("brightness", {"value": clamp(value, 1, 100)})


def color_message(rgb: RGB) -> bytes:
    r, g, b = (clamp(c) for c in rgb)
    return build_message("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


def kelvin_message(kelvin: int) -> bytes:
    k = clamp(kelvin, 2000, 9000)
    return build_message("colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": k})


def status_message() -> bytes:
    return build_message("devStatus", {})


def razer_message(frame: bytes) -> bytes:
    return build_message("razer", {"pt": razer.encode(frame)})


def pt_real_message(packets: Sequence[bytes]) -> bytes:
    """Bluetooth style packets for the light, sent over the LAN."""
    import base64
    return build_message("ptReal", {"command": [base64.b64encode(p).decode() for p in packets]})


def parse_status(data: dict) -> dict:
    """Turn a devStatus reply into DeviceState keyword arguments."""
    out: dict = {}
    if "onOff" in data:
        out["on"] = bool(data["onOff"])
    if "brightness" in data:
        out["brightness"] = int(data["brightness"])
    color = data.get("color")
    if isinstance(color, dict):
        out["color"] = (int(color.get("r", 0)), int(color.get("g", 0)), int(color.get("b", 0)))
    if "colorTemInKelvin" in data:
        out["kelvin"] = int(data["colorTemInKelvin"])
    return out


ScanCallback = Callable[[dict], None]
StatusCallback = Callable[[str, dict], None]


class LanClient:
    """Owns the UDP sockets and a background receive thread."""

    def __init__(self, on_scan: ScanCallback | None = None, on_status: StatusCallback | None = None,
                 interface_ip: str = "0.0.0.0"):
        self.on_scan = on_scan
        self.on_status = on_status
        self.interface_ip = interface_ip
        self._rx: socket.socket | None = None
        self._tx: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self.error: str | None = None

    # lifecycle -----------------------------------------------------------
    def start(self) -> bool:
        if self._running.is_set():
            return True
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        try:
            rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            rx.bind((self.interface_ip, LISTEN_PORT))
            try:
                mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
                rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass  # replies are unicast anyway
            rx.settimeout(0.5)
        except OSError as exc:
            self.error = f"Cannot listen on UDP port {LISTEN_PORT}: {exc}"
            log.warning(self.error)
            return False
        self._rx = rx
        self.error = None
        self._running.set()
        self._thread = threading.Thread(target=self._receive_loop, name="govee-lan-rx", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
        for sock in (self._rx, self._tx):
            if sock:
                sock.close()
        self._rx = self._tx = None

    @property
    def listening(self) -> bool:
        return self._running.is_set()

    # sending -------------------------------------------------------------
    def _send(self, payload: bytes, address: tuple[str, int]) -> None:
        if self._tx is None:
            self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self._tx.sendto(payload, address)
        except OSError as exc:
            log.debug("send to %s failed: %s", address, exc)

    def scan(self, extra_hosts: Sequence[str] = ()) -> None:
        msg = scan_message()
        self._send(msg, (MULTICAST_GROUP, SCAN_PORT))
        for host in extra_hosts:
            self._send(msg, (host, SCAN_PORT))

    def send(self, ip: str, payload: bytes) -> None:
        self._send(payload, (ip, CONTROL_PORT))

    def turn(self, ip: str, on: bool) -> None:
        self.send(ip, turn_message(on))

    def brightness(self, ip: str, value: int) -> None:
        self.send(ip, brightness_message(value))

    def color(self, ip: str, rgb: RGB) -> None:
        self.send(ip, color_message(rgb))

    def kelvin(self, ip: str, kelvin: int) -> None:
        self.send(ip, kelvin_message(kelvin))

    def request_status(self, ip: str) -> None:
        self.send(ip, status_message())

    def pt_real(self, ip: str, packets: Sequence[bytes]) -> None:
        # a few packets per message, lights drop very long messages
        for i in range(0, len(packets), 8):
            self.send(ip, pt_real_message(packets[i:i + 8]))

    def stream_enable(self, ip: str, enabled: bool) -> None:
        self.send(ip, razer_message(razer.enable_frame(enabled)))

    def stream_colors(self, ip: str, colors: Sequence[RGB], gradient: bool = False) -> None:
        self.send(ip, razer_message(razer.color_frame(colors, gradient)))

    # receiving -----------------------------------------------------------
    def _receive_loop(self) -> None:
        assert self._rx is not None
        while self._running.is_set():
            try:
                payload, (host, _port) = self._rx.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_message(payload)
            if not parsed:
                continue
            cmd, data = parsed
            try:
                if cmd == "scan" and self.on_scan:
                    data.setdefault("ip", host)
                    self.on_scan(data)
                elif cmd == "devStatus" and self.on_status:
                    self.on_status(host, data)
            except Exception:  # never let a callback kill the thread
                log.exception("LAN callback failed")
