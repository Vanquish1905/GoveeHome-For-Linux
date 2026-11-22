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
    # background rescans only make sense for the long running commands
    manager.start(rescan=args.command in ("sync", "music", "effect"))
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


def _run_show(args, kind: str, source_factory, prepare=None, manager_ref: dict | None = None) -> int:
    from goveehome.sync.engine import LightEngine

    manager = _manager(args)
    if manager_ref is not None:
        manager_ref["m"] = manager
    _wait_for_devices(manager, args.timeout)
    if prepare:
        prepare(manager.config)
    ids = None
    if args.targets and args.targets != ["all"]:
        ids = [d.id for t in args.targets for d in _resolve(manager, t)]

    done = threading.Event()
    result = {"code": 0}

    def on_state(running: bool, message: str | None) -> None:
        if running:
            print(f"Running ({engine.backend_name}). Press Ctrl+C to stop.")
        else:
            if message:
                print(message, file=sys.stderr)
                result["code"] = 1
            done.set()

    engine = LightEngine(manager, lambda: source_factory(manager.config), on_state=on_state, kind=kind)
    signal.signal(signal.SIGINT, lambda *_: engine.stop(wait=False))
    signal.signal(signal.SIGTERM, lambda *_: engine.stop(wait=False))
    engine.start(ids)
    while not done.wait(0.5):
        pass
    manager.stop()
    return result["code"]


def cmd_sync(args) -> int:
    from goveehome.sync.classic import make_screen_source

    def prepare(config):
        if args.backend:
            config.sync["backend"] = args.backend
        if args.fps:
            config.sync["fps"] = args.fps
    def source(config):
        return make_screen_source(config, manager_ref["m"])
    manager_ref: dict = {}
    return _run_show(args, "sync", source, prepare, manager_ref)


def cmd_music(args) -> int:
    from goveehome.sync.music import MusicSource

    def prepare(config):
        if args.mode:
            config.section("music")["mode"] = args.mode
        if args.palette:
            config.section("music")["palette"] = args.palette
        if args.feel:
            config.section("music")["feel"] = args.feel
        if args.colors:
            try:
                hexes = ["#{:02x}{:02x}{:02x}".format(*parse_color(c)) for c in args.colors.split(";")]
            except ValueError as exc:
                raise SystemExit(str(exc))
            config.section("music")["colors"] = hexes
            config.section("music")["palette"] = "custom"
    return _run_show(args, "music", MusicSource, prepare)


def cmd_effect(args) -> int:
    from goveehome.sync import effects

    if args.name == "list":
        for category in effects.CATEGORIES:
            print(f"{category}:")
            for e in effects.EFFECTS.values():
                if e.category == category:
                    print(f"  {e.id:<14} {e.label}")
        return 0
    if args.name not in effects.EFFECTS:
        raise SystemExit(f"Unknown effect {args.name!r}. Run 'goveehome-cli effect list'.")

    def prepare(config):
        section = config.section("effects")
        section["effect"] = args.name
        if args.speed:
            section["speed"] = args.speed
        if args.brightness is not None:
            section["brightness"] = max(0.0, min(1.0, args.brightness / 100))
        if args.size is not None:
            section["size"] = max(0.05, min(1.0, args.size / 100))
        if args.reverse:
            section["reverse"] = True
        for key, value in (("color_a", args.color), ("color_b", args.color2), ("color_c", args.color3)):
            if value:
                try:
                    section[key] = "#{:02x}{:02x}{:02x}".format(*parse_color(value))
                except ValueError as exc:
                    raise SystemExit(str(exc))
    return _run_show(args, "effects", effects.EffectSource, prepare)


def cmd_update(args) -> int:
    from goveehome import updater

    current = updater.installed()
    print(f"Installed: {current.version}" + (f" ({current.short_commit})" if current.commit else "")
          + f", {current.mode}")
    try:
        info = updater.check(current)
    except updater.UpdateError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"On GitHub: {info.version} ({info.commit[:7]})")
    if not info.available and not args.force:
        print("Already up to date.")
        return 0
    for line in info.changes:
        print(f"  - {line}")
    if args.check:
        return 0
    if not current.can_update:
        print("This copy wasn't installed with install.sh; update it with your package manager.",
              file=sys.stderr)
        return 1
    try:
        updater.apply(current, info)
    except updater.UpdateError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Done. Restart GoveeHome to use the new version.")
    return 0


ANSWERS = {"r": "red", "w": "white or grey", "n": "no change", "o": "something else"}


def _ask(question: str) -> str:
    while True:
        try:
            answer = input(question + " [r]ed / [w]hite or grey / [n]o change / [o]ther: ").strip().lower()
        except EOFError:
            return "o"
        if answer[:1] in ANSWERS:
            return answer[:1]


def _show_and_ask(manager, device, streaming: bool, question: str) -> str:
    stop = threading.Event()
    thread = manager.show_test_colour(device, (255, 0, 0), streaming=streaming, seconds=30.0, stop=stop)
    time.sleep(1.0)                      # give the light a moment before asking
    answer = _ask(question)
    stop.set()
    thread.join(5)
    time.sleep(0.8)                      # let the light settle back
    return answer


def colour_test(manager, device) -> str:
    """Find out how a light takes colours; saves the result. Returns a summary line."""
    name = f"{device.display_name} ({device.sku})"
    if not device.ip:
        return f"{name}: no LAN connection, colour test skipped"
    print(f"\n{name}: colour test. Look at the light.")
    print("  1/2: sending RED with segment streaming…")
    first = _show_and_ask(manager, device, True, "  What does the light show?")
    if first == "r":
        manager.set_streaming(device, True)
        return f"{name}: segment streaming works, it is now on (a colour per segment)"
    print("  2/2: sending RED as a plain colour…")
    second = _show_and_ask(manager, device, False, "  What does the light show now?")
    if second == "r":
        manager.set_streaming(device, False)
        return (f"{name}: segment streaming showed {ANSWERS[first]}, plain colours work. "
                "Segment streaming is now off for it; screen sync sends one colour.")
    return (f"{name}: streaming showed {ANSWERS[first]}, plain colour showed {ANSWERS[second]}. "
            "Check that LAN Control is on in the Govee app and the light is not in a scene.")


def cmd_test_light(args) -> int:
    manager = _manager(args)
    _wait_for_devices(manager, args.timeout)
    results = [colour_test(manager, d) for d in _resolve(manager, args.target)]
    manager.stop(wait=True)
    print("\nResult:")
    print("\n".join("- " + r for r in results))
    return 0


def check_capture_colours(config) -> None:
    """Show red, green and blue fullscreen, capture them and fix a swapped channel order."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk
        if not Gtk.init_check():
            raise RuntimeError("no display")
    except Exception as exc:
        print(f"Capture colour check skipped ({exc}).")
        return
    from goveehome import capture
    from goveehome.capture import calibrate

    loop = GLib.MainLoop()
    result: dict = {}

    def open_backend():
        backend = capture.create(config.sync.get("backend", "auto"), config)
        backend.open()
        return backend

    def done(order, message, measured):
        result.update(order=order, message=message)
        loop.quit()
        return False

    print("\nChecking capture colours: the screen turns red, green and blue for a few seconds…")
    GLib.idle_add(lambda: (calibrate.run_check(open_backend, lambda line: print("  " + line), done), False)[1])
    loop.run()
    order = result.get("order")
    if order is None:
        print("  " + result.get("message", "no result"))
        return
    config.set_sync("channel_order", list(order))
    if tuple(order) == (0, 1, 2):
        print("  Capture colours are correct.")
    else:
        print(f"  Capture had {result['message']}. Fixed: screen sync now corrects it.")


def cmd_diagnose(args) -> int:
    from goveehome import diagnostics
    config = Config()
    if args.backend:
        config.sync["backend"] = args.backend
    print(diagnostics.run_capture_check(config, args.seconds))
    if not args.no_colour_check:
        check_capture_colours(config)
    manager = _manager(args)
    _wait_for_devices(manager, args.timeout)
    print("")
    print("Lights:")
    print("\n".join(diagnostics.light_lines(manager)))
    if sys.stdin.isatty() and not args.no_test:
        try:
            go = input("\nTest which colours your lights really show? This takes ~10 s per light. [Y/n] ")
        except EOFError:
            go = "n"
        if go.strip().lower() in ("", "y", "yes", "j", "ja"):
            results = [colour_test(manager, d) for d in manager.list() if d.ip]
            print("\nColour test:")
            print("\n".join("- " + r for r in results))
    manager.stop(wait=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="goveehome-cli", description="Control Govee lights from the terminal.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true", help="print debug output")
    p.add_argument("--host", action="append", metavar="IP",
                   help="also ask this IP directly (when multicast discovery is blocked)")
    p.add_argument("-t", "--timeout", type=float, default=2.0, help="seconds to wait for lights to answer")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list lights").set_defaults(func=cmd_list)

    s = sub.add_parser("diagnose", help="check screen capture and lights, print a report")
    s.add_argument("--backend", choices=[b for b in capture.BACKENDS if b != "auto"])
    s.add_argument("--seconds", type=float, default=4.0)
    s.add_argument("--no-test", action="store_true", help="skip the colour test of the lights")
    s.add_argument("--no-colour-check", action="store_true",
                   help="skip checking that the capture delivers the right colours")
    s.set_defaults(func=cmd_diagnose)

    s = sub.add_parser("test-light", help="find out how a light shows colours and set it up")
    s.add_argument("target", help="name, IP, id or 'all'")
    s.set_defaults(func=cmd_test_light)

    s = sub.add_parser("update", help="update GoveeHome to the newest version on GitHub")
    s.add_argument("--check", action="store_true", help="only show whether an update exists")
    s.add_argument("--force", action="store_true", help="reinstall even when up to date")
    s.set_defaults(func=cmd_update)

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

    from goveehome.sync.music import MODES as MUSIC_MODES, PALETTES
    s = sub.add_parser("music", help="lights react to the music playing on this PC")
    s.add_argument("targets", nargs="*", help="lights to use (default: all with music enabled in the app)")
    s.add_argument("--mode", choices=list(MUSIC_MODES))
    s.add_argument("--palette", choices=list(PALETTES))
    s.add_argument("--feel", choices=["flowing", "jumpy"])
    s.add_argument("--colors", metavar="'#ff0000;#00ff00;...'",
                   help="your own colours, separated by ';' (uses the custom palette)")
    s.set_defaults(func=cmd_music)

    s = sub.add_parser("effect", help="run a built-in effect ('effect list' shows them)")
    s.add_argument("name", help="effect id, or 'list'")
    s.add_argument("targets", nargs="*", help="lights to use (default: all with effects enabled in the app)")
    s.add_argument("--speed", type=float)
    s.add_argument("--brightness", type=int, metavar="PERCENT")
    s.add_argument("--color", help="first colour (effects that use your colours)")
    s.add_argument("--color2", help="second colour")
    s.add_argument("--color3", help="third colour")
    s.add_argument("--size", type=int, metavar="PERCENT", help="size of moving parts")
    s.add_argument("--reverse", action="store_true", help="run the other way")
    s.set_defaults(func=cmd_effect)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
