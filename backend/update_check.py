# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Check for updates (the never-online work), from Settings › About only.

Kettle Video never goes online by itself: nothing here runs at launch, on a
timer or in the background. The server calls check() only when the viewer
chooses "Check for updates", and it makes exactly one request:

- a release install (and any copy that isn't a git checkout) asks GitHub's
  release information for this app's repo for the latest release, and only
  that: GitHub never answers it with a pre-release or a draft, and there is
  no switch or setting to ask for one (the release flow work). The
  request carries nothing about the viewer, the device or the library: no
  cookies, no identifiers, only a plain user agent with the app's name and
  version. GitHub sees the device's IP address and that version.
- a development install (a git checkout without the installer's mark: the
  development devices) asks the copy's own remote for its main branch instead
  (git ls-remote, which changes nothing in the copy). Pulling it, and
  Update and restart, are backend/app_update.py (the Update and restart work).

It gives up after TIMEOUT_S and never retries by itself. Errors are said in
plain words, never as raw messages.

"Last checked" is kept on the device, in the data folder, and changes only
after a check that got an answer. Reading it never goes online.

Pure logic apart from fetch_latest() and remote_main(), which the tests
replace with stand-ins.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from backend import app_paths

# This app's repo on GitHub (see CLAUDE.md).
REPO = "enamelware/kettle-video"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT_S = 10
STATE_FILE = "update_check.json"
BRANCH = "main"

# The words the row shows ("Checking…" is the page's own, in settings.js).
NO_CONNECTION = "Couldn't check: no connection"
TRY_LATER = "Couldn't check right now. Try again later."
NEVER = "never"
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


class CheckFailed(Exception):
    """A check that got no usable answer. offline: no connection at all."""

    def __init__(self, why: str, offline: bool = False):
        super().__init__(why)
        self.offline = offline


# --- Which kind of copy ---

def is_development(root: Path) -> bool:
    """A git checkout that the installer didn't place: compares with main."""
    root = Path(root)
    return (root / ".git").exists() and not app_paths.is_installed(root)


# --- Versions ---

def parse_version(text: str):
    """(numbers, is_release) for "v1.2.3" or "1.2.3-dev", else None. A
    pre-release ("-dev") comes before the release with the same numbers."""
    found = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:[-+].*)?", (text or "").strip())
    if not found:
        return None
    numbers = tuple(int(n) for n in found.group(1).split("."))
    numbers += (0,) * (3 - len(numbers))
    return numbers, "-" not in text.strip().lstrip("v").split("+", 1)[0]


def is_newer(latest: str, current: str) -> bool:
    new, now = parse_version(latest), parse_version(current)
    if new is None:
        return False
    if now is None:
        return True
    return new > now


def plain_version(tag: str) -> str:
    return (tag or "").strip().lstrip("v")


# --- The release check ---

def user_agent(version: str) -> str:
    return f"Kettle-Video/{version}"


def latest_request(version: str) -> urllib.request.Request:
    """The one request a release check makes. Nothing but the question and a
    plain user agent: no cookies, no identifiers."""
    return urllib.request.Request(LATEST_URL, method="GET", headers={
        "User-Agent": user_agent(version),
        "Accept": "application/vnd.github+json",
    })


def _offline(reason) -> bool:
    """No connection at all: the name can't be looked up, or there is no
    network to send it on."""
    if isinstance(reason, socket.gaierror):
        return True
    if isinstance(reason, OSError) and reason.errno in (101, 113):  # unreachable
        return True
    return False


def fetch_latest(version: str, timeout: float = TIMEOUT_S) -> dict:
    """GitHub's answer for the latest release, as a dict. Raises CheckFailed.
    The standard library's own web client, with no cookie store."""
    opener = urllib.request.build_opener()
    try:
        with opener.open(latest_request(version), timeout=timeout) as answer:
            data = json.loads(answer.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:  # rate-limited, not public yet, down
        exc.close()
        raise CheckFailed(f"GitHub answered {exc.code}")
    except urllib.error.URLError as exc:
        raise CheckFailed(f"no answer ({type(exc.reason).__name__})", _offline(exc.reason))
    except (TimeoutError, socket.timeout):
        raise CheckFailed("no answer in time")
    except OSError as exc:
        raise CheckFailed(f"no answer ({type(exc).__name__})", _offline(exc))
    except (ValueError, UnicodeDecodeError):
        raise CheckFailed("an answer that isn't release information")
    if not isinstance(data, dict):
        raise CheckFailed("an answer that isn't release information")
    return data


def download_size(release: dict, archive_name: str, version: str) -> Optional[int]:
    """The release archive's size in bytes, from the same answer, or None."""
    wanted = f"{archive_name}-{version}.tar.gz"
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == wanted and isinstance(asset.get("size"), int):
            return asset["size"]
    return None


def release_result(release: dict, current: str, archive_name: str) -> dict:
    # GitHub's latest release is never a pre-release or a draft; an answer
    # marked as either is never offered (the release flow work).
    if release.get("prerelease") is True or release.get("draft") is True:
        raise CheckFailed("an answer that isn't a full release")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or parse_version(tag) is None:
        raise CheckFailed("an answer with no version")
    latest = plain_version(tag)
    if not is_newer(latest, current):
        return {"state": "current", "text": f"Up to date (v{current})"}
    notes = release.get("body") if isinstance(release.get("body"), str) else ""
    return {"state": "newer", "text": f"Version {latest} is available", "version": latest,
            "notes": notes, "download_size": download_size(release, archive_name, latest)}


# --- The development check ---

def _git(root: Path, args: list, timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    # Never wait for a password or a host-key question: no one can answer
    # them with a controller.
    env.setdefault("GIT_SSH_COMMAND", f"ssh -o BatchMode=yes -o ConnectTimeout={int(timeout)}")
    proc = subprocess.Popen(["git", *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise CheckFailed("no answer in time")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


OFFLINE_WORDS = ("could not resolve", "temporary failure in name resolution",
                 "network is unreachable", "no route to host", "name or service not known")


def remote_main(root: Path, timeout: float = TIMEOUT_S) -> str:
    """The commit the copy's remote has on main. Changes nothing here."""
    if shutil.which("git") is None:
        raise CheckFailed("git not found")
    remote = _git(root, ["remote"], timeout).stdout.split()
    if not remote:
        raise CheckFailed("no remote")
    name = "origin" if "origin" in remote else remote[0]
    done = _git(root, ["ls-remote", "--quiet", name, f"refs/heads/{BRANCH}"], timeout)
    if done.returncode != 0:
        said = done.stderr.lower()
        raise CheckFailed("the remote didn't answer", any(w in said for w in OFFLINE_WORDS))
    found = done.stdout.split()
    if not found:
        raise CheckFailed(f"no {BRANCH} on the remote")
    return found[0]


def development_result(root: Path, remote_commit: str, current: str) -> dict:
    head = _git(root, ["rev-parse", "HEAD"], TIMEOUT_S).stdout.strip()
    if remote_commit == head:
        return {"state": "current", "text": f"Up to date (v{current}, {head[:7]})"}
    # Main is behind or level with this copy (a branch built on it).
    behind = _git(root, ["merge-base", "--is-ancestor", remote_commit, "HEAD"], TIMEOUT_S)
    if behind.returncode == 0:
        return {"state": "current", "text": f"Up to date (v{current}, {head[:7]})"}
    return {"state": "newer", "text": f"A newer version is on {BRANCH} ({remote_commit[:7]})",
            "development": True}


# --- Last checked ---

def load_last_checked(data_dir: Path) -> Optional[date]:
    try:
        stored = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
        return date.fromisoformat(stored["last_checked"])
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


def save_last_checked(data_dir: Path, day: date) -> None:
    path = Path(data_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"last_checked": day.isoformat()}) + "\n", encoding="utf-8")
    os.replace(temp, path)


def last_checked_text(day: Optional[date], today: date) -> str:
    if day is None:
        return f"Last checked: {NEVER}"
    if day == today:
        return "Last checked: today"
    if day == today - timedelta(days=1):
        return "Last checked: yesterday"
    return f"Last checked: {day.day} {MONTHS[day.month - 1]} {day.year}"


# --- The check ---

def check(root: Path, data_dir: Path, current: str, today: date,
          fetch: Optional[Callable] = None, remote: Optional[Callable] = None) -> dict:
    """One check, as the viewer asked for it. Returns the row's result:
    {state: current | newer | error, text, ...}, plus last_checked (the
    words under the row's label) and log (one line for the launch log, with
    nothing private in it)."""
    fetch = fetch or fetch_latest
    remote = remote or remote_main
    archive_name = app_paths.names(Path(root)).get("ARCHIVE_NAME") or app_paths.DEFAULT_APP_ID
    development = is_development(root)
    try:
        if development:
            result = development_result(root, remote(root), current)
        else:
            release = fetch(current)
            result = release_result(release, current, archive_name)
            if result["state"] == "newer":
                # For Update and restart (the Update and restart work), from the same answer: the
                # server keeps it and never sends it to the page.
                result["release"] = release
    except CheckFailed as exc:
        result = {"state": "error", "text": NO_CONNECTION if exc.offline else TRY_LATER,
                  "log": f"update check: couldn't check ({exc})"}
    else:
        result["log"] = f"update check: {'main' if development else 'latest release'}: {result['state']}"
        try:
            save_last_checked(data_dir, today)
        except OSError as exc:
            result["log"] += f" (couldn't keep the date: {type(exc).__name__})"
    result["last_checked"] = last_checked_text(load_last_checked(data_dir), today)
    result["development"] = development
    return result
