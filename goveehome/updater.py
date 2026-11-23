"""Updates from the project's GitHub repository.

How the running copy was installed decides how it is updated:

* ``installer``: put in place by install.sh (a virtual environment in
  ~/.local/share/goveehome/venv). The newest commit of the main branch is
  downloaded and its own install.sh runs in update mode, which upgrades the
  existing environment and records the installed commit.
* ``checkout``: running straight from a git clone. Updated with
  ``git pull --ff-only``.
* ``other``: e.g. an RPM. We can tell that an update exists, but installing
  it is up to the package manager.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from goveehome import GITHUB_REPO, __version__

log = logging.getLogger(__name__)

BRANCH = "main"
API = "https://api.github.com/repos/" + GITHUB_REPO
RAW = "https://raw.githubusercontent.com/" + GITHUB_REPO
TARBALL = "https://codeload.github.com/" + GITHUB_REPO + "/tar.gz/"
TIMEOUT = 15
INSTALL_INFO = "installed.json"


class UpdateError(Exception):
    pass


@dataclass
class Installed:
    mode: str                      # "installer", "checkout" or "other"
    version: str
    commit: str | None = None
    path: Path | None = None       # app dir (installer) or repository (checkout)
    prefix: Path | None = None     # PREFIX that install.sh used

    @property
    def can_update(self) -> bool:
        return self.mode in ("installer", "checkout")

    @property
    def short_commit(self) -> str:
        return self.commit[:7] if self.commit else ""


@dataclass
class UpdateInfo:
    version: str
    commit: str
    date: str = ""
    available: bool = False
    changes: list[str] = field(default_factory=list)   # newest first, first lines only
    ahead_by: int | None = None


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:4]) or (0,)


# finding out what is installed ---------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, timeout=30).stdout.strip()


def installed(prefix_path: str | None = None, package_dir: Path | None = None) -> Installed:
    prefix = Path(prefix_path or sys.prefix).resolve()
    package_dir = (package_dir or Path(__file__).resolve().parent)
    if prefix.name == "venv" and prefix.parent.name == "goveehome":
        app_dir = prefix.parent
        info = {}
        try:
            info = json.loads((app_dir / INSTALL_INFO).read_text())
        except (OSError, ValueError):
            pass
        # .../<PREFIX>/share/goveehome/venv
        return Installed("installer", __version__, info.get("commit") or None, app_dir,
                         Path(info["prefix"]) if info.get("prefix") else app_dir.parent.parent)
    repo = package_dir.parent
    if (repo / ".git").exists() and shutil.which("git"):
        try:
            return Installed("checkout", __version__, _git(repo, "rev-parse", "HEAD"), repo)
        except (subprocess.SubprocessError, OSError):
            pass
    return Installed("other", __version__)


# talking to GitHub -----------------------------------------------------------------

def _get(url: str, opener=None, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "goveehome-updater"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("The repository wasn't found on GitHub. Is it private?") from exc
        if exc.code == 403:
            raise UpdateError("GitHub refused the request (too many checks?). Try again in an hour.") from exc
        raise UpdateError(f"GitHub answered with error {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Can't reach GitHub: {getattr(exc, 'reason', exc)}") from exc


def _json(url: str, opener=None):
    try:
        return json.loads(_get(url, opener))
    except ValueError as exc:
        raise UpdateError("Unexpected answer from GitHub") from exc


def check(current: Installed, opener=None) -> UpdateInfo:
    head = _json(f"{API}/commits/{BRANCH}", opener)
    sha = head["sha"]
    date = (head.get("commit", {}).get("committer") or {}).get("date", "")
    source = _get(f"{RAW}/{sha}/goveehome/__init__.py", opener, accept="text/plain").decode("utf-8", "replace")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    version = match.group(1) if match else "?"
    info = UpdateInfo(version=version, commit=sha, date=date)

    if current.commit:
        if current.commit == sha:
            return info
        try:
            cmp = _json(f"{API}/compare/{current.commit}...{sha}", opener)
            info.ahead_by = int(cmp.get("ahead_by", 0))
            info.available = cmp.get("status") in ("ahead", "diverged") and info.ahead_by > 0
            info.changes = [c["commit"]["message"].splitlines()[0]
                            for c in reversed(cmp.get("commits") or [])][:30]
        except UpdateError:
            # our commit isn't on GitHub (local work); go by version number
            info.available = version_tuple(version) > version_tuple(current.version)
    else:
        info.available = version_tuple(version) > version_tuple(current.version)
    if info.available and not info.changes:
        commits = _json(f"{API}/commits?sha={BRANCH}&per_page=10", opener)
        info.changes = [c["commit"]["message"].splitlines()[0] for c in commits]
    return info


# installing --------------------------------------------------------------------

def _safe_extract(data: bytes, target: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        root = target.resolve()
        for member in tar.getmembers():
            dest = (target / member.name).resolve()
            if not str(dest).startswith(str(root) + os.sep):
                raise UpdateError("The download contains unexpected paths")
            if member.issym() or member.islnk():
                raise UpdateError("The download contains links")
        try:
            tar.extractall(target, filter="data")
        except TypeError:  # Python < 3.12
            tar.extractall(target)
    tops = [p for p in target.iterdir() if p.is_dir()]
    if len(tops) != 1 or not (tops[0] / "install.sh").exists():
        raise UpdateError("The download doesn't look like GoveeHome")
    return tops[0]


def _run(cmd: list[str], log_line: Callable[[str], None], env: dict | None = None,
         cwd: Path | None = None) -> None:
    log_line("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    assert proc.stdout is not None
    for line in proc.stdout:
        log_line(line.rstrip())
    if proc.wait() != 0:
        raise UpdateError(f"{os.path.basename(cmd[0]) if cmd[0] != 'bash' else cmd[1]} failed "
                          f"(exit code {proc.returncode})")


def backup_settings(log_line: Callable[[str], None] = print) -> None:
    from goveehome.config import Config
    try:
        dest = Config().backup("before-update")
    except Exception as exc:     # a backup problem must not block the update
        log_line(f"Couldn't back up the settings: {exc}")
        return
    if dest is not None:
        log_line(f"Backed up your settings to {dest}")


def apply(current: Installed, info: UpdateInfo, log_line: Callable[[str], None] = print,
          opener=None) -> None:
    """Install `info` over `current`. Raises UpdateError with a readable message.

    Settings, lights, presets and animations live in ~/.config/goveehome, which an
    update never touches; a copy is still put into its backups folder first.
    """
    backup_settings(log_line)
    if current.mode == "checkout":
        if _git(current.path, "status", "--porcelain", "--untracked-files=no"):
            raise UpdateError("The checkout has local changes; commit or stash them first")
        _run(["git", "-C", str(current.path), "pull", "--ff-only", "origin", BRANCH], log_line)
        return
    if current.mode != "installer":
        raise UpdateError("This copy wasn't installed with install.sh; update it with your package manager")

    log_line(f"Downloading {GITHUB_REPO} at {info.commit[:7]}…")
    data = _get(TARBALL + info.commit, opener, accept="application/octet-stream")
    with tempfile.TemporaryDirectory(prefix="goveehome-update-") as tmp:
        src = _safe_extract(data, Path(tmp))
        env = {**os.environ,
               "PREFIX": str(current.prefix),
               "GOVEEHOME_COMMIT": info.commit,
               "GOVEEHOME_SOURCE": f"github:{GITHUB_REPO}"}
        # install.sh uses python3 to create things; make sure it's the system one
        env.pop("VIRTUAL_ENV", None)
        venv_bin = str(current.path / "venv" / "bin") if current.path else ""
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != venv_bin)
        _run(["bash", str(src / "install.sh"), "--update"], log_line, env=env, cwd=src)
    log_line("Update installed.")


def launcher() -> list[str]:
    """Command that starts the GUI again after an update."""
    candidates = [Path(sys.prefix) / "bin" / "goveehome", Path(shutil.which("goveehome") or "")]
    for c in candidates:
        if c.name == "goveehome" and c.exists() and os.access(c, os.X_OK):
            return [str(c)]
    return [sys.executable, "-m", "goveehome"]
