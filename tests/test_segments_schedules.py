import base64
import datetime as dt
import json

from goveehome import schedules as sch
from goveehome import segments as seg
from goveehome.config import Config
from goveehome.manager import DeviceManager
from goveehome.models import Device
from goveehome.protocol import lan


class Lan:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


def xor_ok(packet):
    x = 0
    for b in packet[:-1]:
        x ^= b
    return len(packet) == 20 and x == packet[-1]


def test_colour_packet_layout():
    p = seg.colour_packet([0, 2, 9], (255, 16, 1), 15)
    assert xor_ok(p)
    assert list(p[:7]) == [0x33, 0x05, 0x15, 0x01, 255, 16, 1]
    assert list(p[7:12]) == [0, 0, 0, 0, 0]
    assert p[12] == 0b00000101 and p[13] == 0b00000010
    # long lights get more mask bytes
    p = seg.colour_packet([40], (1, 2, 3), 48)
    assert p[12 + 5] == 1 and xor_ok(p)
    b = seg.brightness_packet([1], 150, 15)
    assert list(b[:5]) == [0x33, 0x05, 0x15, 0x02, 100] and b[5] == 0b10 and xor_ok(b)


def test_one_packet_per_colour():
    red, blue = (255, 0, 0), (0, 0, 255)
    packets = seg.packets([red, red, blue, None, red])
    assert len(packets) == 2
    assert packets[0][12] == 0b10011 and packets[1][12] == 0b100


def test_pt_real_message_wraps_packets():
    p = seg.colour_packet([0], (1, 2, 3), 10)
    msg = json.loads(lan.pt_real_message([p]))
    assert msg["msg"]["cmd"] == "ptReal"
    assert base64.b64decode(msg["msg"]["data"]["command"][0]) == p


def test_fills_and_presets():
    g = seg.fill("gradient", 5, (0, 0, 0), (200, 100, 0))
    assert g[0] == (0, 0, 0) and g[-1] == (200, 100, 0) and g[2] == (100, 50, 0)
    assert seg.fill("alternate", 4, (1, 1, 1), (2, 2, 2)) == [(1, 1, 1), (2, 2, 2)] * 2
    m = seg.fill("mirror", 5, (0, 0, 0), (100, 0, 0))
    assert m[0] == m[-1] and m[1] == m[-2]
    assert len(seg.fill("rainbow", 7)) == 7
    out = seg.apply_fill([None] * 6, {1, 4}, "alternate", (9, 9, 9), (8, 8, 8))
    assert out == [None, (9, 9, 9), None, None, (8, 8, 8), None]
    assert seg.preset_colours("Christmas", 4) == [(255, 0, 0), (0, 192, 0)] * 2
    assert len(seg.preset_colours("Rainbow", 15)) == 15
    assert seg.preset_colours(["#000000", "#ffffff"], 3)[1] == (128, 128, 128)


def test_parse_spec():
    assert seg.parse_spec("1-3=red", 10) == [([0, 1, 2], (255, 0, 0))]
    assert seg.parse_spec("2,5=#00ff00", 10)[0][0] == [1, 4]
    assert seg.parse_spec("all=blue", 3)[0][0] == [0, 1, 2]
    for bad in ("11=red", "red", "1=notacolour"):
        try:
            seg.parse_spec(bad, 10)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_paint_over_lan_and_remember(tmp_path):
    m = DeviceManager(Config(tmp_path / "c.json"))
    m.lan = Lan()
    d = m.devices["d"] = Device("d", sku="H6199", ip="10.0.0.9")
    m.config.update_device_settings("d", segments=6)
    colours = [(255, 0, 0)] * 3 + [None] * 3
    assert m.paint_segments(d, colours)
    names = [c[0] for c in m.lan.calls]
    assert names[:2] == ["turn", "pt_real"]
    packets = m.lan.calls[1][2]
    assert len(packets) == 1 and packets[0][12] == 0b111
    assert m.painted_segments(d)[:3] == [(255, 0, 0)] * 3 and m.painted_segments(d)[3] is None
    # painting more keeps the earlier colours
    m.paint_segments(d, [None] * 5 + [(0, 0, 255)])
    assert m.painted_segments(d)[0] == (255, 0, 0) and m.painted_segments(d)[5] == (0, 0, 255)


def test_paint_needs_a_route(tmp_path):
    m = DeviceManager(Config(tmp_path / "c.json"))
    m.lan = Lan()
    d = m.devices["d"] = Device("d", sku="H6199")
    assert m.segment_routes(d) == []
    assert not m.paint_segments(d, [(1, 2, 3)] * 4)


def test_schedule_timing():
    s = sch.new_schedule(time="07:30", days=[0, 2])
    monday = dt.datetime(2026, 11, 23, 7, 30, 20)
    assert monday.weekday() == 0
    assert sch.is_due(s, monday)
    assert not sch.is_due(s, monday.replace(minute=31))
    assert not sch.is_due(s, monday + dt.timedelta(days=1))
    assert sch.next_run(s, monday) == dt.datetime(2026, 11, 25, 7, 30)
    assert not sch.is_due({**s, "enabled": False}, monday)
    assert sch.describe(sch.new_schedule(days=[0, 1, 2, 3, 4], action="off")).startswith("Weekdays at 07:00")


def test_sunrise_ramp():
    start, lo = sch.ramp_colour(0)
    end, hi = sch.ramp_colour(1)
    assert lo == 1 and hi == 100 and start[0] == 255 and end[2] > start[2]
    assert sch.ramp_colour(0.3, reverse=True) == sch.ramp_colour(0.7)


def test_scheduler_runs_once_per_minute(tmp_path):
    m = DeviceManager(Config(tmp_path / "c.json"))
    m.lan = Lan()
    m.devices["a"] = Device("a", sku="H6008", ip="10.0.0.1")
    m.devices["b"] = Device("b", sku="H6008", ip="10.0.0.2")
    group = m.save_group("Desk", ["b"])
    now = dt.datetime(2026, 11, 23, 22, 0, 5)
    m.config.set("schedules", [
        sch.new_schedule(id="off", time="22:00", action="off"),
        sch.new_schedule(id="col", time="22:00", action="color", value="#00ff00", target=f"group:{group['id']}"),
        sch.new_schedule(id="later", time="22:01", action="on"),
    ])
    s = sch.Scheduler(m.config, m, clock=lambda: now)
    assert sorted(s.tick()) == ["col", "off"]
    assert s.tick() == []                      # not twice in the same minute
    turns = [c for c in m.lan.calls if c[0] == "turn"]
    assert {c[1] for c in turns} == {"10.0.0.1", "10.0.0.2"} and all(c[2] is False for c in turns)
    assert ("color", "10.0.0.2", (0, 255, 0)) in m.lan.calls
    assert not any(c[0] == "color" and c[1] == "10.0.0.1" for c in m.lan.calls)
