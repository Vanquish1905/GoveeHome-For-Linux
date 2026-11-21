"""Command line interface: goveehome-cli."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time

from goveehome import __version__, capture
from goveehome.colors import parse_color
from goveehome.config import Config
from goveehome.manager import DeviceManager


def _manager(args) -> DeviceManager:
    config = Config()
    for host in args.host or []:
        if host not in config["extra_hosts"]:
            config["extra_hosts"].append(host)
    manager = DeviceManager(config)
    # background rescans only make sense for the long running sync command
    manager.start(rescan=args.command == "sync")
    return manager


def _wait_for_devices(manager: DeviceManager, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.1)


def _resolve(manager: DeviceManager, target: str):
    if target == "all":
        return manager.list()
    device = manager.find(target)
    if device is None:
        # an IP that wasn't found by multicast: ask it directly
        if target.count(".") == 3:
            manager.lan.scan([target])
            _wait_for_devices(manager, 1.5)
            device = manager.find(target)
    if device is None:
        raise SystemExit(f"No light matches {target!r}. Run 'goveehome-cli list' to see what was found.")
    return [device]


def cmd_list(args) -> int:
    manager = _manager(args)
    _wait_for_devices(manager, args.timeout)
    devices = manager.list()
    if not devices:
        print("No lights found.")
        print("Check that 'LAN Control' is enabled for the light in the Govee Home phone app,")
        print("and that UDP port 4002 is allowed by the firewall (see SETUP.md).")
        manager.stop()
        return 1
    width = max(len(d.display_name) for d in devices)
    for d in devices:
        via = ", ".join(t.value for t in d.transports) or "offline"
        st = d.state
        power = "on " if st.on else "off" if st.on is False else " ? "
        color = "#{:02x}{:02x}{:02x}".format(*st.color) if st.color else "       "
        print(f"{d.display_name:<{width}}  {d.sku:<6}  {power}  {color}  {d.ip or d.ble_address or '':<17}  {via}")
    manager.stop()
    return 0


def _each(args, fn) -> int:
    manager = _manager(args)
    _wait_for_devices(manager, args.timeout)
    for device in _resolve(manager, args.target):
        fn(manager, device)
    time.sleep(0.4)  # let UDP / BLE / cloud requests leave
    manager.stop(wait=True)
    return 0


def cmd_on(args) -> int:
    return _each(args, lambda m, d: m.set_power(d, True))


def cmd_off(args) -> int:
    return _each(args, lambda m, d: m.set_power(d, False))


def cmd_brightness(args) -> int:
    return _each(args, lambda m, d: m.set_brightness(d, args.value))


def cmd_color(args) -> int:
    try:
        rgb = parse_color(" ".join(args.color) if len(args.color) == 1 else ",".join(args.color))
    except ValueError as exc:
        raise SystemExit(str(exc))
    return _each(args, lambda m, d: m.set_color(d, rgb))


def cmd_temp(args) -> int:
    return _each(args, lambda m, d: m.set_kelvin(d, args.kelvin))


def cmd_sync(args) -> int:
    from goveehome.sync.engine import SyncEngine

    manager = _manager(args)
    _wait_for_devices(manager, args.timeout)
    if args.backend:
        manager.config.sync["backend"] = args.backend
    if args.fps:
        manager.config.sync["fps"] = args.fps
    ids = None
    if args.targets and args.targets != ["all"]:
        ids = [d.id for t in args.targets for d in _resolve(manager, t)]

    done = threading.Event()
    result = {"code": 0}

    def on_state(running: bool, message: str | None) -> None:
        if running:
            print(f"Screen sync running ({engine.backend_name}). Press Ctrl+C to stop.")
        else:
            if message:
                print(message, file=sys.stderr)
                result["code"] = 1
            done.set()

    engine = SyncEngine(manager, on_state=on_state)
    signal.signal(signal.SIGINT, lambda *_: engine.stop(wait=False))
    signal.signal(signal.SIGTERM, lambda *_: engine.stop(wait=False))
    engine.start(ids)
    while not done.wait(0.5):
        pass
    manager.stop()
    return result["code"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="goveehome-cli", description="Control Govee lights from the terminal.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true", help="print debug output")
    p.add_argument("--host", action="append", metavar="IP",
                   help="also ask this IP directly (when multicast discovery is blocked)")
    p.add_argument("-t", "--timeout", type=float, default=2.0, help="seconds to wait for lights to answer")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list lights").set_defaults(func=cmd_list)

    for name, func, text in (("on", cmd_on, "turn on"), ("off", cmd_off, "turn off")):
        s = sub.add_parser(name, help=text)
        s.add_argument("target", help="name, IP, id or 'all'")
        s.set_defaults(func=func)

    s = sub.add_parser("brightness", help="set brightness 1-100")
    s.add_argument("target")
    s.add_argument("value", type=int)
    s.set_defaults(func=cmd_brightness)

    s = sub.add_parser("color", help="set a colour: '#ff8800', 'ff8800', 'red' or '255 136 0'")
    s.add_argument("target")
    s.add_argument("color", nargs="+")
    s.set_defaults(func=cmd_color)

    s = sub.add_parser("temp", help="set white temperature in Kelvin (2000-9000)")
    s.add_argument("target")
    s.add_argument("kelvin", type=int)
    s.set_defaults(func=cmd_temp)

    s = sub.add_parser("sync", help="mirror the screen colours to lights until stopped")
    s.add_argument("targets", nargs="*", help="lights to use (default: all with sync enabled in the app)")
    s.add_argument("--backend", choices=[b for b in capture.BACKENDS if b != "auto"])
    s.add_argument("--fps", type=int)
    s.set_defaults(func=cmd_sync)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
