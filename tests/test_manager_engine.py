import threading
import time

from goveehome.capture.pattern import PatternCapture
from goveehome.config import Config
from goveehome.manager import DeviceManager
from goveehome.models import Device
from goveehome.sync.engine import SyncEngine


class RecordingLan:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))
        return record


def make_manager(tmp_path):
    manager = DeviceManager(Config(tmp_path / "c.json"))
    manager.lan = RecordingLan()
    return manager


def test_lan_scan_adds_device_with_model_name(tmp_path):
    m = make_manager(tmp_path)
    events = []
    m.subscribe(lambda e, d, msg: events.append(e))
    m._on_lan_scan({"ip": "10.0.0.5", "device": "AA:01", "sku": "H6199"})
    d = m.get("AA:01")
    assert d.ip == "10.0.0.5" and d.name.startswith("DreamView")
    assert "added" in events
    assert ("request_status", "10.0.0.5") in m.lan.calls


def test_user_name_survives_rediscovery(tmp_path):
    m = make_manager(tmp_path)
    m._on_lan_scan({"ip": "10.0.0.5", "device": "AA:01", "sku": "H6199"})
    m.rename(m.get("AA:01"), "Desk")
    m._on_lan_scan({"ip": "10.0.0.6", "device": "AA:01", "sku": "H6199"})
    assert m.get("AA:01").name == "Desk"
    assert m.get("AA:01").ip == "10.0.0.6"


def test_find(tmp_path):
    m = make_manager(tmp_path)
    m.devices["a"] = Device("a", name="Desk lamp", ip="10.0.0.1")
    m.devices["b"] = Device("b", name="TV backlight", ip="10.0.0.2")
    assert m.find("10.0.0.2").id == "b"
    assert m.find("desk").id == "a"
    assert m.find("nothing") is None


def test_set_color_routes_over_lan(tmp_path):
    m = make_manager(tmp_path)
    d = m.devices["a"] = Device("a", ip="10.0.0.1")
    m.set_color(d, (1, 2, 3))
    assert ("color", "10.0.0.1", (1, 2, 3)) in m.lan.calls
    assert d.state.color == (1, 2, 3)


def test_stream_uses_razer_for_capable_models(tmp_path):
    m = make_manager(tmp_path)
    tv = m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    bulb = m.devices["bulb"] = Device("bulb", sku="H6008", ip="10.0.0.2")
    m.stream(tv, [(255, 0, 0)] * 10)
    m.stream(bulb, [(255, 0, 0), (0, 0, 255)])
    names = [c[0] for c in m.lan.calls]
    assert names.count("stream_enable") == 1
    # one colour from both: the strongest colour, not a washed out mix
    sent = [c[2] for c in m.lan.calls if c[0] == "color" and c[1] == "10.0.0.2"]
    assert sent[-1] in ((255, 0, 0), (0, 0, 255))
    m.stream_stop(tv)
    assert ("stream_enable", "10.0.0.1", False) in m.lan.calls


def test_engine_drives_lights(tmp_path):
    m = make_manager(tmp_path)
    m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    m.devices["cloud"] = Device("cloud", sku="H6008", cloud=True)  # never streamed
    m.config.sync["fps"] = 30
    states, previews = [], []
    stopped = threading.Event()

    def on_state(running, msg):
        states.append((running, msg))
        if not running:
            stopped.set()

    engine = SyncEngine(m, on_preview=previews.append, on_state=on_state,
                        backend_factory=lambda name: PatternCapture())
    engine.start()
    time.sleep(0.6)
    engine.stop()
    assert stopped.wait(3)
    assert states[0] == (True, None) and states[-1] == (False, None)
    frames = [c for c in m.lan.calls if c[0] == "stream_colors"]
    assert len(frames) > 3
    assert all(c[1] == "10.0.0.1" and len(c[2]) == 15 for c in frames)
    assert previews and "cloud" not in previews[-1].targets
    assert m.lan.calls[-1] == ("stream_enable", "10.0.0.1", False)


def test_engine_reports_missing_lights(tmp_path):
    m = make_manager(tmp_path)
    result = []
    done = threading.Event()
    engine = SyncEngine(m, on_state=lambda r, msg: (result.append(msg), done.set()),
                        backend_factory=lambda name: PatternCapture())
    engine.start()
    assert done.wait(3)
    assert "No lights" in result[0]


def test_engines_are_exclusive(tmp_path):
    from goveehome.sync.effects import EffectSource
    from goveehome.sync.engine import LightEngine

    m = make_manager(tmp_path)
    m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    a = LightEngine(m, lambda: EffectSource(m.config), kind="effects")
    b = SyncEngine(m, backend_factory=lambda name: PatternCapture())
    a.start()
    time.sleep(0.3)
    b.start()
    time.sleep(0.3)
    assert b.running and not a.running
    b.stop()


def test_effect_engine_applies_gamma_and_gains(tmp_path):
    from goveehome.sync.effects import EffectSource
    from goveehome.sync.engine import LightEngine

    m = make_manager(tmp_path)
    m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    m.config.update_device_settings("tv", gains=[1.0, 1.0, 0.5])
    m.config.data["gamma"] = 1.0
    m.config.section("effects").update(effect="breathe", color_a="#ffffff", speed=0.01, brightness=1.0)
    engine = LightEngine(m, lambda: EffectSource(m.config), kind="effects")
    engine.start()
    time.sleep(0.4)
    engine.stop()
    frames = [c[2] for c in m.lan.calls if c[0] == "stream_colors"]
    r, g, b = frames[-1][0]
    assert r == g and abs(b - r / 2) <= 1


def test_identify_shows_the_screen_sides(tmp_path):
    m = make_manager(tmp_path)
    tv = m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    m.identify(tv, seconds=0.3)
    time.sleep(0.6)
    frame = [c[2] for c in m.lan.calls if c[0] == "stream_colors"][0]
    # TV backlight: starts bottom left (dim red), goes up (bright red), across
    # the top (green) and down the right (bright then dim blue)
    assert frame[0] == (38, 0, 0) and frame[-1] == (0, 0, 38)
    assert (255, 0, 0) in frame and (0, 255, 0) in frame and (0, 0, 255) in frame
    assert ("stream_enable", "10.0.0.1", False) in m.lan.calls


def test_identify_for_light_bars(tmp_path):
    from goveehome.manager import DeviceManager
    colors = DeviceManager.identify_colors({"segments": 12, "streaming": True, "layout": "bars",
                                            "reverse": False})
    assert colors[:3] == [(255, 0, 0)] * 3 and colors[3:6] == [(38, 0, 0)] * 3
    assert colors[6:9] == [(0, 0, 255)] * 3 and colors[9:] == [(0, 0, 38)] * 3


def test_streaming_is_switched_on_once(tmp_path):
    m = make_manager(tmp_path)
    tv = m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.1")
    for _ in range(50):
        m.stream(tv, [(1, 2, 3)] * 15)
    assert [c[0] for c in m.lan.calls].count("stream_enable") == 1


def test_h6056_defaults(tmp_path):
    m = make_manager(tmp_path)
    bars = m.devices["bars"] = Device("bars", sku="H6056", ip="10.0.0.3")
    s = m.stream_settings(bars)
    assert s["segments"] == 12 and s["layout"] == "bars" and s["streaming"]
    # the cloud reports 15 segments for it, only 12 exist
    bars.cloud_capabilities = [{"instance": "segmentedColorRgb", "parameters": {"fields": [
        {"fieldName": "segment", "elementRange": {"min": 0, "max": 14}}]}}]
    assert m.stream_settings(bars)["segments"] == 12


def test_black_colour_commands_are_not_ignored(tmp_path):
    m = make_manager(tmp_path)
    bulb = m.devices["b"] = Device("b", sku="H6008", ip="10.0.0.4")
    m.stream(bulb, [(0, 0, 0)])
    assert ("color", "10.0.0.4", (1, 1, 1)) in m.lan.calls


def test_groups(tmp_path):
    m = make_manager(tmp_path)
    m.devices["a"] = Device("a", ip="10.0.0.1")
    m.devices["b"] = Device("b", ip="10.0.0.2")
    events = []
    m.subscribe(lambda e, d, msg: events.append(e))
    g = m.save_group("Desk", ["a", "gone"])
    assert [d.id for d in m.group_devices(g)] == ["a"]
    m.save_group("Desk area", ["a", "b"], g["id"])
    assert len(m.groups()) == 1 and m.group(g["id"])["name"] == "Desk area"
    m.delete_group(g["id"])
    assert m.groups() == [] and events.count("groups") == 3


def test_streaming_is_only_assumed_where_it_is_known_to_work(tmp_path):
    m = make_manager(tmp_path)
    neon = m.devices["neon"] = Device("neon", sku="H61A0", ip="10.0.0.5")
    tv = m.devices["tv"] = Device("tv", sku="H6199", ip="10.0.0.6")
    assert m.stream_settings(neon)["streaming"] is False
    assert m.stream_settings(tv)["streaming"] is True


def test_colour_test_modes_and_saving(tmp_path):
    import threading
    m = make_manager(tmp_path)
    neon = m.devices["neon"] = Device("neon", sku="H61A0", ip="10.0.0.5")
    stop = threading.Event()
    t = m.show_test_colour(neon, (255, 0, 0), streaming=True, seconds=10, stop=stop)
    time.sleep(0.4)
    stop.set()
    t.join(2)
    names = [c[0] for c in m.lan.calls]
    assert "stream_colors" in names and ("stream_enable", "10.0.0.5", False) in m.lan.calls
    m.lan.calls.clear()
    m.show_test_colour(neon, (255, 0, 0), streaming=False, seconds=0.4, wait=True)
    assert ("color", "10.0.0.5", (255, 0, 0)) in m.lan.calls
    assert not any(c[0] == "stream_colors" for c in m.lan.calls)
    m.set_streaming(neon, True)
    assert m.stream_settings(neon)["streaming"] is True


def test_cli_colour_test_turns_streaming_off_when_only_plain_colours_work(tmp_path, monkeypatch):
    from goveehome import cli
    m = make_manager(tmp_path)
    neon = m.devices["neon"] = Device("neon", sku="H61A0", ip="10.0.0.5")
    m.set_streaming(neon, True)
    answers = iter(["w", "r"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    result = cli.colour_test(m, neon)
    assert "plain colours work" in result
    assert m.stream_settings(neon)["streaming"] is False
