import json
import os
import stat

from goveehome.config import Config


def test_defaults_and_round_trip(tmp_path):
    path = tmp_path / "c.json"
    c = Config(path)
    assert c.sync["fps"] == 30
    c.set("cloud_api_key", "secret")
    c.update_device_settings("AA", layout="top")
    c2 = Config(path)
    assert c2["cloud_api_key"] == "secret"
    assert c2.device_settings("AA")["layout"] == "top"
    assert c2.device_settings("BB")["sync"] is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_new_defaults_merge_into_old_files(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"version": 2, "sync": {"fps": 45}}))
    c = Config(path)
    assert c.sync["fps"] == 45
    assert c.sync["mode"] == "accurate"
    assert c.section("music")["mode"] == "spectrum"


def test_old_tuning_is_reset(tmp_path):
    """1.0 settings (per frame smoothing, no gamma) don't mean the same any more."""
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"sync": {"fps": 20, "smoothing": 0.5, "mode": "vivid", "monitor": 0,
                                         "backend": "x11"}, "cloud_api_key": "k"}))
    c = Config(path)
    assert c.sync["smoothing"] == 0.04 and c.sync["mode"] == "accurate" and c.sync["monitor"] == 1
    assert c.sync["backend"] == "x11" and c["cloud_api_key"] == "k"
    assert c["version"] == 2


def test_device_settings_are_copies(tmp_path):
    c = Config(tmp_path / "c.json")
    c.device_settings("a")["gains"][0] = 0.1
    assert c.device_settings("a")["gains"] == [1.0, 1.0, 1.0]


def test_broken_file_is_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{nope")
    assert Config(path).sync["fps"] == 30
