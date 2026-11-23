import json
import os

from goveehome import __version__, updater
from goveehome.config import KEEP_BACKUPS, Config


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


MINE = {"version": 7, "app_version": "1.0.0",
        "segment_presets": [{"name": "Mine", "colours": ["#ff0000"]}],
        "animations": [{"id": "a", "name": "Blink", "frames": [["#ff0000"]]}],
        "schedules": [{"id": "s", "time": "07:00"}], "cloud_api_key": "k"}


def test_new_version_keeps_everything_and_makes_one_backup(tmp_path):
    path = tmp_path / "goveehome" / "config.json"
    write(path, MINE)
    c = Config(path)
    for key in ("segment_presets", "animations", "schedules", "cloud_api_key"):
        assert c.get(key) == MINE[key]
    backups = c.backups()
    assert len(backups) == 1 and f"before-{__version__}" in backups[0].name
    assert json.loads(backups[0].read_text())["app_version"] == "1.0.0"
    assert json.loads(path.read_text())["app_version"] == __version__
    Config(path)
    Config(path)
    assert len(c.backups()) == 1                     # not again on every start


def test_damaged_file_is_kept_and_the_backup_is_used(tmp_path):
    path = tmp_path / "goveehome" / "config.json"
    write(path, MINE)
    c = Config(path)
    c.backup("manual")
    path.write_text('{"segment_presets": [')        # cut off half way
    c = Config(path)
    assert c.get("segment_presets") == MINE["segment_presets"]
    assert any(p.name.startswith("config.broken-") for p in path.parent.iterdir())


def test_backups_are_limited_and_restore_works(tmp_path):
    path = tmp_path / "goveehome" / "config.json"
    write(path, MINE)
    c = Config(path)
    for i in range(KEEP_BACKUPS + 5):
        dest = c.backup(f"n{i}")
        os.utime(dest, (1000 + i, 1000 + i))
    assert len(c.backups()) == KEEP_BACKUPS
    old = c.backups()[-1]
    c.set("segment_presets", [])
    c.restore(old)
    assert c.get("segment_presets") == MINE["segment_presets"]
    assert Config(path).get("segment_presets") == MINE["segment_presets"]
    try:
        bad = tmp_path / "bad.json"
        bad.write_text("nope")
        c.restore(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("restored junk")


def test_update_backs_up_first(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    write(tmp_path / "goveehome" / "config.json", MINE)
    lines = []
    updater.backup_settings(lines.append)
    assert any("before-update" in p.name for p in (tmp_path / "goveehome" / "backups").iterdir())
    assert lines and "Backed up" in lines[0]


def test_saving_is_atomic(tmp_path):
    path = tmp_path / "goveehome" / "config.json"
    c = Config(path)
    c.set("segment_presets", MINE["segment_presets"])
    assert not path.with_suffix(".tmp").exists()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
