import json
import os
import stat

from goveehome.config import Config


def test_defaults_and_round_trip(tmp_path):
    path = tmp_path / "c.json"
    c = Config(path)
    assert c.sync["fps"] == 20
    c.set("cloud_api_key", "secret")
    c.update_device_settings("AA", layout="top")
    c2 = Config(path)
    assert c2["cloud_api_key"] == "secret"
    assert c2.device_settings("AA")["layout"] == "top"
    assert c2.device_settings("BB")["sync"] is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_new_defaults_merge_into_old_files(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"sync": {"fps": 30}}))
    c = Config(path)
    assert c.sync["fps"] == 30
    assert c.sync["mode"] == "vivid"


def test_broken_file_is_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{nope")
    assert Config(path).sync["fps"] == 20
