import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from goveehome import GITHUB_REPO, updater

OLD = "a" * 40
NEW = "b" * 40


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def github(routes):
    """Fake urlopen serving canned answers by URL substring."""
    seen = []

    def opener(req, timeout):
        seen.append(req.full_url)
        for part, answer in routes.items():
            if part in req.full_url:
                if isinstance(answer, Exception):
                    raise answer
                return Resp(answer if isinstance(answer, bytes) else json.dumps(answer).encode())
        raise AssertionError(f"unexpected request {req.full_url}")
    opener.seen = seen
    return opener


def base_routes(version="9.9.9"):
    return {
        "/commits/main": {"sha": NEW, "commit": {"committer": {"date": "2026-11-21T10:00:00Z"}}},
        "/goveehome/__init__.py": f'__version__ = "{version}"\n'.encode(),
    }


def test_version_tuple():
    assert updater.version_tuple("1.10.0") > updater.version_tuple("1.9.3")
    assert updater.version_tuple("2.0") > updater.version_tuple("1.99.99")
    assert updater.version_tuple("nonsense") == (0,)


def test_up_to_date_by_commit():
    routes = base_routes()
    info = updater.check(updater.Installed("installer", "1.0.0", NEW), github(routes))
    assert not info.available and info.version == "9.9.9"


def test_update_with_changes_from_compare():
    routes = base_routes()
    routes["/compare/"] = {"status": "ahead", "ahead_by": 2, "commits": [
        {"commit": {"message": "Older change\n\nbody"}}, {"commit": {"message": "Newest change"}}]}
    opener = github(routes)
    info = updater.check(updater.Installed("installer", "1.0.0", OLD), opener)
    assert info.available and info.ahead_by == 2
    assert info.changes == ["Newest change", "Older change"]
    assert any(f"compare/{OLD}...{NEW}" in u for u in opener.seen)


def test_unknown_commit_falls_back_to_version():
    import urllib.error
    routes = base_routes("1.0.1")
    routes["/compare/"] = urllib.error.HTTPError("u", 404, "no", {}, None)
    routes["/commits?sha=main"] = [{"commit": {"message": "Something"}}]
    info = updater.check(updater.Installed("installer", "1.0.0", OLD), github(routes))
    assert info.available and info.changes == ["Something"]
    info = updater.check(updater.Installed("installer", "1.0.1", OLD), github(routes))
    assert not info.available


def test_no_recorded_commit_uses_version():
    routes = base_routes("1.2.0")
    routes["/commits?sha=main"] = [{"commit": {"message": "x"}}]
    assert updater.check(updater.Installed("installer", "1.1.0"), github(routes)).available
    assert not updater.check(updater.Installed("installer", "1.2.0"), github(routes)).available


def test_errors_are_readable():
    import urllib.error
    with pytest.raises(updater.UpdateError, match="private"):
        updater.check(updater.Installed("other", "1.0"),
                      github({"/commits/main": urllib.error.HTTPError("u", 404, "x", {}, None)}))
    with pytest.raises(updater.UpdateError, match="reach GitHub"):
        updater.check(updater.Installed("other", "1.0"),
                      github({"/commits/main": urllib.error.URLError("offline")}))


def test_installed_detection(tmp_path):
    venv = tmp_path / "prefix" / "share" / "goveehome" / "venv"
    venv.mkdir(parents=True)
    (venv.parent / "installed.json").write_text(json.dumps({"commit": OLD, "prefix": str(tmp_path / "prefix")}))
    inst = updater.installed(str(venv), package_dir=tmp_path / "x" / "goveehome")
    assert inst.mode == "installer" and inst.commit == OLD and inst.prefix == tmp_path / "prefix"
    assert inst.can_update and inst.short_commit == "aaaaaaa"

    plain = updater.installed(str(tmp_path / "usr"), package_dir=tmp_path / "site" / "goveehome")
    assert plain.mode == "other" and not plain.can_update


def test_checkout_detection(tmp_path):
    repo = tmp_path / "repo"
    (repo / "goveehome").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f").write_text("x")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True, env=env)
    inst = updater.installed(str(tmp_path / "usr"), package_dir=repo / "goveehome")
    assert inst.mode == "checkout" and len(inst.commit) == 40
    (repo / "f").write_text("changed")
    with pytest.raises(updater.UpdateError, match="local changes"):
        updater.apply(inst, updater.UpdateInfo("1", NEW, available=True), lambda line: None)


def _tarball(files: dict[str, str], top="GoveeHome-For-Linux-" + NEW) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extract_rejects_path_traversal(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater._safe_extract(_tarball({"../../evil": "x"}, top=""), tmp_path)


def test_extract_rejects_foreign_archives(tmp_path):
    with pytest.raises(updater.UpdateError, match="doesn't look like"):
        updater._safe_extract(_tarball({"README": "hi"}), tmp_path)


def test_apply_runs_the_new_installer_in_update_mode(tmp_path):
    record = tmp_path / "record.txt"
    script = f'#!/bin/bash\necho "args=$*" > "{record}"\necho "prefix=$PREFIX" >> "{record}"\n' \
             f'echo "commit=$GOVEEHOME_COMMIT" >> "{record}"\necho installing\n'
    data = _tarball({"install.sh": script})
    app_dir = tmp_path / "prefix" / "share" / "goveehome"
    inst = updater.Installed("installer", "1.0.0", OLD, app_dir, tmp_path / "prefix")
    lines = []
    updater.apply(inst, updater.UpdateInfo("2.0.0", NEW, available=True), lines.append,
                  opener=github({"codeload.github.com/" + GITHUB_REPO + "/tar.gz/" + NEW: data}))
    out = record.read_text()
    assert "args=--update" in out
    assert f"prefix={tmp_path / 'prefix'}" in out
    assert f"commit={NEW}" in out
    assert "installing" in lines


def test_apply_reports_installer_failure(tmp_path):
    data = _tarball({"install.sh": "#!/bin/bash\necho broken >&2\nexit 3\n"})
    inst = updater.Installed("installer", "1.0.0", OLD, tmp_path, tmp_path)
    with pytest.raises(updater.UpdateError, match="exit code 3"):
        updater.apply(inst, updater.UpdateInfo("2.0.0", NEW), lambda line: None,
                      opener=github({"codeload": data}))


def test_package_managed_copies_are_not_touched():
    with pytest.raises(updater.UpdateError, match="package manager"):
        updater.apply(updater.Installed("other", "1.0"), updater.UpdateInfo("2", NEW), lambda line: None)
