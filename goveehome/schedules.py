"""Schedules: turn lights on or off, set a colour or a scene, wake up with a sunrise.

They run while the app runs (also in the background), like the schedules in
the Govee app but on this computer. A schedule is a dict:

    {"id": "s1", "name": "Wake up", "enabled": True,
     "time": "07:00", "days": [0, 1, 2, 3, 4],      # Monday = 0
     "target": "all" | "group:<id>" | "<device id>",
     "action": "on" | "off" | "color" | "brightness" | "sunrise" | "sunset" | "segments" | "show",
     "value": ...}                                   # see ACTIONS

Runs are matched to the minute. A schedule whose minute passed while the
computer slept is not caught up later.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from collections.abc import Callable

from goveehome.colors import parse_color

log = logging.getLogger(__name__)

ACTIONS = {
    "on": "Turn on",
    "off": "Turn off",
    "color": "Set a colour",
    "brightness": "Set the brightness",
    "sunrise": "Sunrise (slowly brighter)",
    "sunset": "Sunset (slowly darker, then off)",
    "segments": "Segment colours (a preset)",
    "show": "Start a light show",
}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# sunrise: from a deep red glow to warm white
SUNRISE = [(255, 30, 0), (255, 90, 10), (255, 150, 60), (255, 200, 140)]


def new_schedule(**fields) -> dict:
    out = {"id": uuid.uuid4().hex[:8], "name": "", "enabled": True, "time": "07:00",
           "days": list(range(7)), "target": "all", "action": "on", "value": None}
    out.update(fields)
    return out


def parse_time(text: str) -> tuple[int, int]:
    h, m = (int(x) for x in str(text).strip().split(":", 1))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"not a time: {text!r}")
    return h, m


def is_due(schedule: dict, now: dt.datetime) -> bool:
    if not schedule.get("enabled", True) or now.weekday() not in schedule.get("days", []):
        return False
    try:
        h, m = parse_time(schedule.get("time", ""))
    except ValueError:
        return False
    return now.hour == h and now.minute == m


def next_run(schedule: dict, now: dt.datetime) -> dt.datetime | None:
    if not schedule.get("enabled", True) or not schedule.get("days"):
        return None
    try:
        h, m = parse_time(schedule["time"])
    except (ValueError, KeyError):
        return None
    for days in range(8):
        day = now + dt.timedelta(days=days)
        when = day.replace(hour=h, minute=m, second=0, microsecond=0)
        if when.weekday() in schedule["days"] and when > now:
            return when
    return None


def describe(schedule: dict, value_label: str = "") -> str:
    days = schedule.get("days", [])
    if sorted(days) == list(range(7)):
        when = "Every day"
    elif sorted(days) == list(range(5)):
        when = "Weekdays"
    elif sorted(days) == [5, 6]:
        when = "Weekends"
    elif not days:
        when = "Never"
    else:
        when = ", ".join(DAY_NAMES[d] for d in sorted(days))
    text = f"{when} at {schedule.get('time', '?')} · {ACTIONS.get(schedule.get('action'), '?')}"
    return f"{text} {value_label}".strip()


def ramp_colour(t: float, reverse: bool = False) -> tuple[tuple[int, int, int], int]:
    """Colour and brightness of a sunrise at t (0..1); sunset is the same backwards."""
    if reverse:
        t = 1 - t
    t = max(0.0, min(1.0, t))
    pos = t * (len(SUNRISE) - 1)
    k = min(int(pos), len(SUNRISE) - 2)
    f = pos - k
    rgb = tuple(int(round(a + (b - a) * f)) for a, b in zip(SUNRISE[k], SUNRISE[k + 1]))
    return rgb, max(1, int(round(1 + 99 * t ** 1.6)))


class Scheduler:
    """Checks the schedules a few times a minute and runs the ones that are due."""

    def __init__(self, config, manager, start_show: Callable[[str], None] | None = None,
                 clock: Callable[[], dt.datetime] = dt.datetime.now):
        self.config = config
        self.manager = manager
        self.start_show = start_show
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._done: set[tuple[str, str]] = set()
        self._ramps: dict[str, threading.Event] = {}

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="schedules", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for ev in self._ramps.values():
            ev.set()

    def _loop(self) -> None:
        while not self._stop.wait(10):
            try:
                self.tick()
            except Exception:   # a broken schedule must not stop the others
                log.exception("schedule failed")

    def tick(self) -> list[str]:
        now = self.clock()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        ran = []
        for schedule in list(self.config.get("schedules") or []):
            key = (schedule.get("id", ""), stamp)
            if key in self._done or not is_due(schedule, now):
                continue
            self._done.add(key)
            self.run(schedule)
            ran.append(schedule.get("id", ""))
        # forget old minutes
        self._done = {k for k in self._done if k[1] == stamp}
        return ran

    def targets(self, schedule: dict) -> list:
        target = schedule.get("target", "all")
        if target == "all":
            return self.manager.list()
        if target.startswith("group:"):
            group = self.manager.group(target[6:])
            return self.manager.group_devices(group) if group else []
        device = self.manager.get(target)
        return [device] if device else []

    def run(self, schedule: dict) -> None:
        action, value = schedule.get("action"), schedule.get("value")
        devices = self.targets(schedule)
        log.info("schedule %s: %s on %d lights", schedule.get("name") or schedule.get("id"), action, len(devices))
        if action == "show":
            if self.start_show and value:
                self.start_show(str(value))
            return
        if action in ("sunrise", "sunset"):
            minutes = float(value or 15)
            self._ramp(schedule.get("id", ""), devices, minutes, action == "sunset")
            return
        for d in devices:
            if action == "on":
                self.manager.set_power(d, True)
            elif action == "off":
                self.manager.set_power(d, False)
            elif action == "color" and value:
                self.manager.set_color(d, parse_color(value))
            elif action == "brightness" and value:
                self.manager.set_power(d, True)
                self.manager.set_brightness(d, int(value))
            elif action == "segments" and value:
                from goveehome import segments as seg
                preset = next((p["colours"] for p in self.config.get("segment_presets") or []
                               if p.get("name") == value), value)
                self.manager.paint_segments(d, seg.preset_colours(preset, self.manager.segment_count(d)))

    def _ramp(self, key: str, devices, minutes: float, reverse: bool) -> None:
        old = self._ramps.pop(key, None)
        if old:
            old.set()
        stop = self._ramps[key] = threading.Event()
        steps = 60
        pause = max(0.5, minutes * 60 / steps)

        def run():
            for d in devices:
                self.manager.set_power(d, True)
            last = None
            for i in range(steps + 1):
                if stop.is_set() or self._stop.is_set():
                    return
                rgb, level = ramp_colour(i / steps, reverse)
                if (rgb, level) != last:
                    for d in devices:
                        self.manager.set_color(d, rgb)
                        self.manager.set_brightness(d, level)
                    last = (rgb, level)
                if i < steps:
                    stop.wait(pause)
            if reverse and not stop.is_set():
                for d in devices:
                    self.manager.set_power(d, False)
            self._ramps.pop(key, None)
        threading.Thread(target=run, name=f"ramp-{key}", daemon=True).start()

