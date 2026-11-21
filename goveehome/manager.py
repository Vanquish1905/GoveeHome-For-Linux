"""Keeps the list of lights and routes commands to the best transport.

Order of preference is LAN, then Bluetooth, then the cloud. Callbacks fire on
worker threads; GUI code must hop back to its main loop itself.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from goveehome import skus
from goveehome.colors import RGB
from goveehome.config import Config
from goveehome.models import Device, Transport
from goveehome.protocol import ble, lan
from goveehome.protocol.cloud import CloudClient, CloudError

log = logging.getLogger(__name__)

Listener = Callable[[str, "Device | None", "str | None"], None]

STREAM_GAP = 3.0   # resend "streaming on" only after this long without frames


class DeviceManager:
    def __init__(self, config: Config):
        self.config = config
        self.devices: dict[str, Device] = {}
        self._lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="govee-io")
        self.lan = lan.LanClient(on_scan=self._on_lan_scan, on_status=self._on_lan_status)
        self.ble = ble.BleClient()
        self.cloud: CloudClient | None = None
        self._stream_state: dict[str, dict] = {}
        self._ble_pending: list = []
        self.active_engine = None       # the light show currently running, if any
        self._rescan_stop = threading.Event()
        self._rescan_thread: threading.Thread | None = None
        self._load_cache()
        self.set_api_key(config.get("cloud_api_key", ""), save=False)

    # listeners -------------------------------------------------------------
    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _emit(self, event: str, device: Device | None = None, message: str | None = None) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, device, message)
            except Exception:
                log.exception("listener failed")

    def _error(self, message: str) -> None:
        log.warning(message)
        self._emit("error", None, message)

    # lifecycle ---------------------------------------------------------------
    def start(self, rescan: bool = True) -> None:
        if not self.lan.start():
            self._error(self.lan.error or "LAN control is unavailable")
        if self.config.get("bluetooth") and not self.ble.start():
            self._error("Bluetooth is enabled but the 'bleak' package is missing")
        self.discover()
        interval = int(self.config.get("rescan_interval", 0) or 0)
        if rescan and interval > 0 and not self._rescan_thread:
            self._rescan_thread = threading.Thread(
                target=self._rescan_loop, args=(interval,), name="govee-rescan", daemon=True)
            self._rescan_thread.start()

    def stop(self, wait: bool = False) -> None:
        """Shut down. wait=True lets queued cloud/Bluetooth requests finish first."""
        self._rescan_stop.set()
        for device_id in list(self._stream_state):
            device = self.devices.get(device_id)
            if device:
                self.stream_stop(device)
        self._pool.shutdown(wait=wait, cancel_futures=not wait)
        if wait:
            for fut in list(self._ble_pending):
                try:
                    fut.result(timeout=15)
                except Exception:
                    pass
        self.lan.stop()
        self.ble.stop()
        self._save_cache()

    def _rescan_loop(self, interval: int) -> None:
        while not self._rescan_stop.wait(interval):
            self.lan.scan(self.config.get("extra_hosts", []))
            for device in self.list():
                if device.ip:
                    self.lan.request_status(device.ip)

    # cache -------------------------------------------------------------------
    def _load_cache(self) -> None:
        for device_id, data in (self.config.get("devices") or {}).items():
            device = Device.from_cache(device_id, data)
            custom = self.config.device_settings(device_id).get("name")
            if custom:
                device.name = custom
            self.devices[device_id] = device

    def _save_cache(self) -> None:
        with self._lock:
            self.config.set("devices", {d.id: d.to_cache() for d in self.devices.values()})

    def list(self) -> list[Device]:
        with self._lock:
            return sorted(self.devices.values(), key=lambda d: d.display_name.lower())

    def get(self, device_id: str) -> Device | None:
        return self.devices.get(device_id)

    def find(self, query: str) -> Device | None:
        """Resolve a CLI style target: id, IP, BLE address or (partial) name."""
        q = query.strip().lower()
        devices = self.list()
        for d in devices:
            if q in (d.id.lower(), (d.ip or "").lower(), (d.ble_address or "").lower()):
                return d
        for d in devices:
            if d.display_name.lower() == q:
                return d
        matches = [d for d in devices if q in d.display_name.lower()]
        return matches[0] if len(matches) == 1 else None

    def forget(self, device: Device) -> None:
        with self._lock:
            self.devices.pop(device.id, None)
        self._save_cache()
        self._emit("removed", device)

    def rename(self, device: Device, name: str) -> None:
        device.name = name.strip()
        self.config.update_device_settings(device.id, name=device.name)
        self._save_cache()
        self._emit("updated", device)

    # groups ----------------------------------------------------------------
    def groups(self) -> list[dict]:
        return list(self.config.get("groups") or [])

    def group(self, group_id: str) -> dict | None:
        return next((g for g in self.groups() if g["id"] == group_id), None)

    def group_devices(self, group: dict) -> list[Device]:
        return [d for d in (self.devices.get(i) for i in group.get("members", [])) if d is not None]

    def save_group(self, name: str, members: list[str], group_id: str | None = None) -> dict:
        import uuid
        groups = self.groups()
        entry = next((g for g in groups if g["id"] == group_id), None) if group_id else None
        if entry is None:
            entry = {"id": "group-" + uuid.uuid4().hex[:8]}
            groups.append(entry)
        entry["name"] = name.strip() or "Group"
        entry["members"] = list(members)
        self.config.set("groups", groups)
        self._emit("groups", None)
        return entry

    def delete_group(self, group_id: str) -> None:
        self.config.set("groups", [g for g in self.groups() if g["id"] != group_id])
        self._emit("groups", None)

    # discovery -------------------------------------------------------------
    def discover(self) -> None:
        self.lan.scan(self.config.get("extra_hosts", []))
        if self.cloud:
            self._pool.submit(self._discover_cloud)
        if self.config.get("bluetooth") and ble.available():
            self._pool.submit(self._discover_ble)

    def add_host(self, ip: str) -> None:
        hosts = list(self.config.get("extra_hosts", []))
        if ip not in hosts:
            hosts.append(ip)
            self.config.set("extra_hosts", hosts)
        self.lan.scan([ip])

    def _upsert(self, device_id: str, **fields) -> Device:
        with self._lock:
            device = self.devices.get(device_id)
            created = device is None
            if created:
                device = Device(id=device_id)
                custom = self.config.device_settings(device_id).get("name")
                if custom:
                    device.name = custom
                self.devices[device_id] = device
            for key, value in fields.items():
                if key == "name" and self.config.device_settings(device_id).get("name"):
                    continue  # user picked a name, keep it
                if value not in (None, ""):
                    setattr(device, key, value)
            device.last_seen = time.time()
        self._emit("added" if created else "updated", device)
        if created:
            self._save_cache()
        return device

    def _on_lan_scan(self, data: dict) -> None:
        device_id = data.get("device") or data.get("ip")
        sku = data.get("sku", "")
        existing = self.devices.get(device_id)
        name = None if existing and existing.name else skus.lookup(sku).name
        device = self._upsert(device_id, sku=sku, ip=data.get("ip"), name=name)
        self.lan.request_status(device.ip)

    def _on_lan_status(self, ip: str, data: dict) -> None:
        with self._lock:
            device = next((d for d in self.devices.values() if d.ip == ip), None)
        if device is None:
            return
        device.state.merge(**lan.parse_status(data))
        device.last_seen = time.time()
        self._emit("updated", device)

    def _discover_cloud(self) -> None:
        try:
            items = self.cloud.list_devices()
        except CloudError as exc:
            self._error(str(exc))
            return
        for item in items:
            if item.get("type") not in (None, "devices.types.light"):
                continue
            device = self._upsert(item["device"], sku=item.get("sku", ""), name=item.get("deviceName"),
                                  cloud=True)
            device.cloud_capabilities = item.get("capabilities") or []
            if not device.ip:
                self._pool.submit(self._refresh_cloud_state, device)
        self._save_cache()

    def _discover_ble(self) -> None:
        try:
            found = self.ble.scan()
        except Exception as exc:
            self._error(f"Bluetooth scan failed: {exc}")
            return
        for address, name in found:
            device_id = "ble:" + address
            sku = ble.sku_from_name(name)
            self._upsert(device_id, sku=sku, ble_address=address,
                         name=skus.lookup(sku).name if sku else name)
        self._save_cache()

    def set_api_key(self, key: str, save: bool = True) -> None:
        key = (key or "").strip()
        self.cloud = CloudClient(key) if key else None
        if save:
            self.config.set("cloud_api_key", key)

    def test_api_key(self, key: str) -> int:
        """Returns the number of devices on the account or raises CloudError."""
        return len(CloudClient(key).list_devices())

    # state -----------------------------------------------------------------
    def refresh(self, device: Device) -> None:
        if device.ip:
            self.lan.request_status(device.ip)
        elif device.cloud and self.cloud:
            self._pool.submit(self._refresh_cloud_state, device)

    def _refresh_cloud_state(self, device: Device) -> None:
        try:
            device.state.merge(**self.cloud.get_state(device.sku, device.id))
        except CloudError as exc:
            self._error(f"{device.display_name}: {exc}")
            return
        self._emit("updated", device)

    # control -----------------------------------------------------------------
    def _dispatch(self, device: Device, lan_fn, ble_packet, cloud_fn) -> None:
        transport = device.preferred_transport
        if transport is Transport.LAN:
            lan_fn(device.ip)
            # Ask for the real state shortly after so the UI stays honest.
            threading.Timer(0.6, self.lan.request_status, args=(device.ip,)).start()
        elif transport is Transport.BLE:
            try:
                fut = self.ble.write(device.ble_address, ble_packet)
                self._ble_pending.append(fut)

                def done(f):
                    if f in self._ble_pending:
                        self._ble_pending.remove(f)
                    if not f.cancelled() and f.exception():
                        self._error(f"{device.display_name}: Bluetooth write failed")
                fut.add_done_callback(done)
            except RuntimeError as exc:
                self._error(str(exc))
        elif transport is Transport.CLOUD and self.cloud:
            def run():
                try:
                    cloud_fn(device.sku, device.id)
                except CloudError as exc:
                    self._error(f"{device.display_name}: {exc}")
            self._pool.submit(run)
        else:
            self._error(f"{device.display_name} is not reachable right now")

    def set_power(self, device: Device, on: bool) -> None:
        device.state.merge(on=on)
        self._dispatch(device, lambda ip: self.lan.turn(ip, on), ble.power_packet(on),
                       lambda sku, did: self.cloud.turn(sku, did, on))
        self._emit("updated", device)

    def set_brightness(self, device: Device, value: int) -> None:
        value = max(1, min(100, int(value)))
        device.state.merge(brightness=value)
        self._dispatch(device, lambda ip: self.lan.brightness(ip, value), ble.brightness_packet(value),
                       lambda sku, did: self.cloud.brightness(sku, did, value))
        self._emit("updated", device)

    def set_color(self, device: Device, rgb: RGB) -> None:
        rgb = tuple(int(c) for c in rgb)
        device.state.merge(color=rgb, kelvin=0, on=True)
        mode = skus.lookup(device.sku).ble_color_mode
        self._dispatch(device, lambda ip: self.lan.color(ip, rgb), ble.color_packet(rgb, mode),
                       lambda sku, did: self.cloud.color(sku, did, rgb))
        self._emit("updated", device)

    def set_kelvin(self, device: Device, kelvin: int) -> None:
        device.state.merge(kelvin=int(kelvin), on=True)
        from goveehome.colors import kelvin_to_rgb
        approx = kelvin_to_rgb(kelvin)
        mode = skus.lookup(device.sku).ble_color_mode
        self._dispatch(device, lambda ip: self.lan.kelvin(ip, kelvin), ble.color_packet(approx, mode),
                       lambda sku, did: self.cloud.kelvin(sku, did, kelvin))
        self._emit("updated", device)

    def load_scenes(self, device: Device, callback: Callable[[list[dict]], None]) -> None:
        """Cloud scenes plus the user's DIY scenes, passed to callback on a worker thread."""
        if not (self.cloud and device.cloud):
            callback([])
            return

        def run():
            scenes: list[dict] = []
            try:
                scenes = self.cloud.scenes(device.sku, device.id)
            except CloudError as exc:
                self._error(f"{device.display_name}: {exc}")
            try:
                scenes += self.cloud.diy_scenes(device.sku, device.id)
            except CloudError:
                pass  # many lights have no DIY scenes, that's not worth a message
            callback(scenes)
        self._pool.submit(run)

    def _cloud(self, device: Device, fn) -> None:
        if not (self.cloud and device.cloud):
            self._error("This needs the Govee API key (Preferences)")
            return

        def run():
            try:
                fn(self.cloud)
            except CloudError as exc:
                self._error(f"{device.display_name}: {exc}")
        self._pool.submit(run)

    def set_scene(self, device: Device, scene) -> None:
        if isinstance(scene, dict) and "instance" in scene:
            value, instance = scene["value"], scene["instance"]
        else:
            value, instance = scene, "lightScene"
        self._cloud(device, lambda c: c.set_scene(device.sku, device.id, value, instance))

    def set_segment_color(self, device: Device, segments: list[int], rgb: RGB) -> None:
        self._cloud(device, lambda c: c.segment_color(device.sku, device.id, segments, rgb))

    def set_music_mode(self, device: Device, mode: int, sensitivity: int) -> None:
        self._cloud(device, lambda c: c.music_mode(device.sku, device.id, mode, sensitivity))

    def set_toggle(self, device: Device, instance: str, on: bool) -> None:
        self._cloud(device, lambda c: c.toggle(device.sku, device.id, instance, on))

    # streaming (screen sync) -------------------------------------------------
    def stream_settings(self, device: Device) -> dict:
        settings = self.config.device_settings(device.id)
        info = skus.lookup(device.sku)
        if settings["segments"] is None:
            settings["segments"] = self.default_segments(device)
        if settings["streaming"] is None:
            settings["streaming"] = info.streaming
        if not settings["layout"]:
            settings["layout"] = info.layout
        if not device.ip:
            settings["streaming"] = False
        # "segments" stays the number of screen zones even without streaming:
        # screen sync looks at all of them and turns them into one good colour
        return settings

    @staticmethod
    def default_segments(device: Device) -> int:
        from goveehome.protocol.cloud import segment_count
        return skus.segment_count(device.sku, segment_count(device.cloud_capabilities))

    def stream(self, device: Device, colors: Sequence[RGB], settings: dict | None = None) -> None:
        settings = settings or self.stream_settings(device)
        now = time.monotonic()
        entry = self._stream_state.get(device.id)
        if entry is None:
            entry = self._stream_state[device.id] = {
                "last_frame": None,
                "color": device.state.color,
                "kelvin": device.state.kelvin,
            }
            if device.state.on is False:
                self.set_power(device, True)
        if settings["streaming"] and device.ip:
            # Switch streaming on once. Repeating it while frames flow makes
            # some lights blink; only after a pause (the light may have left
            # streaming mode by itself) is it sent again.
            last = entry["last_frame"]
            if last is None or now - last > STREAM_GAP:
                self.lan.stream_enable(device.ip, True)
            entry["last_frame"] = now
            self.lan.stream_colors(device.ip, colors, settings.get("gradient", True))
            return
        if len(colors) > 1:
            from goveehome.sync.colors import combine
            avg = tuple(int(round(v)) for v in combine(np.asarray(colors, dtype=np.float32))[0])
        else:
            avg = tuple(int(v) for v in colors[0])
        if avg == (0, 0, 0):
            # some lights ignore an all-zero colour and keep the old one
            avg = (1, 1, 1)
        entry["last_frame"] = now
        if device.ip:
            self.lan.color(device.ip, avg)
        elif device.ble_address:
            try:
                self.ble.write(device.ble_address, ble.color_packet(avg, skus.lookup(device.sku).ble_color_mode))
            except RuntimeError:
                pass

    def stream_stop(self, device: Device, restore: bool = True) -> None:
        entry = self._stream_state.pop(device.id, None)
        if entry is None:
            return
        settings = self.stream_settings(device)
        if settings["streaming"] and device.ip:
            # the light falls back to whatever it showed before streaming
            self.lan.stream_enable(device.ip, False)
            return
        if not restore:
            return
        if entry["kelvin"]:
            self.set_kelvin(device, entry["kelvin"])
        elif entry["color"]:
            self.set_color(device, entry["color"])

    @staticmethod
    def identify_colors(settings: dict) -> list[RGB]:
        """Test colours that show whether the mounting matches the screen.

        Every segment gets the colour of the screen area it takes its light
        from: red on the left, blue on the right (bright in the upper half, dim
        in the lower half), green at the top, yellow at the bottom. With a
        correct setup the light shows exactly that.
        """
        from goveehome.sync.zones import layout_rects
        n = settings["segments"] if settings["streaming"] else 1
        rects = layout_rects(settings["layout"] or "whole", n, 0.15, settings.get("reverse", False))
        if n == 1 or all(r == (0.0, 0.0, 1.0, 1.0) for r in rects):
            frame = [(40, 40, 40)] * n
            frame[0] = (255, 0, 0)
            if n > 1:
                frame[-1] = (0, 0, 255)
            return frame
        out = []
        for x0, y0, x1, y1 in rects:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if cy < 0.25 and 0.25 < cx < 0.75:
                out.append((0, 255, 0))
            elif cy > 0.75 and 0.25 < cx < 0.75:
                out.append((255, 200, 0))
            else:
                # sides: bright in the upper half, dim in the lower half
                level = 1.0 if cy < 0.5 else 0.15
                base = (255, 0, 0) if cx < 0.5 else (0, 0, 255)
                out.append(tuple(int(c * level) for c in base))
        return out

    def identify(self, device: Device, settings: dict | None = None, seconds: float = 8.0) -> None:
        """Show the test colours above for a few seconds, then restore the light."""
        settings = settings or self.stream_settings(device)

        def run():
            frame = self.identify_colors(settings)
            end = time.monotonic() + seconds
            blink = False
            while time.monotonic() < end:
                if len(frame) == 1:
                    blink = not blink
                    out = [(255, 0, 0) if blink else (1, 1, 1)]
                else:
                    out = frame
                self.stream(device, out, {**settings, "gradient": False})
                time.sleep(0.4)
            self.stream_stop(device, restore=True)
        threading.Thread(target=run, name="govee-identify", daemon=True).start()

    @property
    def streaming_devices(self) -> list[str]:
        return list(self._stream_state)
