#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Install or update the app files from a release archive (the installer's update step).

The one place that places the app's files: installer/install.sh calls it
for a first install and for an update, and the app's "Update and restart"
(the Update and restart work, backend/app_update.py) calls it too, so the checks and the rollback
are written once.

    python3 -I installer/update.py install ARCHIVE --app-dir DIR --mark NAME [--name NAME]

    ARCHIVE    the release archive; its checksum file (ARCHIVE.sha256) sits
               beside it
    --app-dir  where the app files go (~/.local/share/kettle-video/app)
    --mark     the installed copy's mark file (INSTALL_MARK in names.env)
    --name     the app's name, for the messages (APP_NAME)

Exit status: 0 installed or updated; 1 stopped before anything changed;
2 the update failed and the previous version was put back; 3 the person
said no to installing an older version (nothing changed).

How the files are laid out. Each version is unpacked into its own folder
in versions/, next to the app folder, and the app folder is a shortcut
(symlink) to the current one:

    ~/.local/share/kettle-video/app        -> versions/0.3.0-1a2b3c
    ~/.local/share/kettle-video/versions/  one folder per version
    ~/.local/share/kettle-video/data/      never touched here

Switching versions replaces that shortcut in a single step (a rename), so
after a power cut at any moment the app folder is either the old version or
the new one, complete, never a mix. A leftover folder from an interrupted
run is cleared by the next one. An install made before this layout (the installer work:
the app folder a plain folder) is moved into versions/ by the first update.

The order, for an update:
  1. the archive is checked against its checksum, and its contents (one top
     folder, nothing pointing outside it) — before anything is touched;
  2. it is unpacked into versions/ beside the installed version;
  3. both versions are printed; an older one is installed only after a yes;
  4. the app folder is switched to the new version;
  5. the new version must start cleanly (started_cleanly below);
  6. only then is the previous version removed. If 2, 4 or 5 fails, the app
     folder is switched back to the previous version and the message says so.

Settings, data and logs live outside the app files (backend/app_paths.py),
so nothing here reads or writes them. Standard library only, and this file
imports nothing from the app: the release script writes it into the
install.sh it puts next to the archive (tools/release.py), so the installer
works on its own. No sudo, nothing outside the app's own folders.
"""

from __future__ import annotations

import argparse
import collections
import errno
import fcntl
import hashlib
import io
import json
import os
import posixpath
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Mapping, Optional

VERSIONS = "versions"
# Files every release has; an archive without them isn't the app.
REQUIRED = ("launch.sh", "backend/server.py", "VERSION")
# How long the new version has to answer on its first start.
START_TIMEOUT = 30.0
# Launch options that would change what the first start does (the fresh start mode, the sizing spike).
START_ENV_DROPPED = ("KETTLE_PRETEND_NO_MPV", "KETTLE_DEV_UPDATE",
                     "KETTLE_LAUNCH_LOG", "KETTLE_SIZE_READOUT")
# The first start runs as a fresh start (the fresh start mode): the settings file is read,
# but the server gets an empty data folder of its own (deleted when it
# closes) and never opens the real one, which it would otherwise tidy as it
# starts (Continue watching).
START_ENV_SET = {"KETTLE_FRESH_START": "1"}

INSTALLED, UPDATED, STOPPED, ROLLED_BACK, DECLINED = (
    "installed", "updated", "stopped", "rolled back", "declined")
EXIT_CODES = {INSTALLED: 0, UPDATED: 0, STOPPED: 1, ROLLED_BACK: 2, DECLINED: 3}


class Stop(Exception):
    """Something found before anything changed, said in plain words."""


class Failed(Exception):
    """A step that went wrong after placing had started, in plain words."""


@dataclass(frozen=True)
class Result:
    outcome: str
    old_version: Optional[str]
    new_version: Optional[str]
    message: str

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]


def _checkpoint(step: str) -> None:
    """Called between the steps; the tests use it to cut the power there."""


# ---------------------------------------------------------------- versions

def version_key(text: str):
    """Sort key for VERSION's text: 0.10.0 after 0.9.0, and a pre-release
    (0.2.0-dev) before its release (0.2.0)."""
    main, _, pre = text.strip().partition("-")
    numbers = [int(n) for n in re.findall(r"\d+", main)][:4]
    numbers += [0] * (4 - len(numbers))
    return (tuple(numbers), 0 if pre else 1, pre)


def is_older(new: str, old: str) -> bool:
    return version_key(new) < version_key(old)


def _read_version(folder: Path) -> Optional[str]:
    try:
        lines = (folder / "VERSION").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return lines[0].strip() if lines and lines[0].strip() else None


# ---------------------------------------------------------------- the archive

def read_checked(archive: Path) -> bytes:
    """The archive's bytes, once they match its checksum file. The bytes
    checked are the bytes unpacked, so the file can't change in between."""
    archive = Path(archive)
    if not archive.is_file():
        raise Stop(f"the archive {archive} isn't there.")
    sum_file = Path(f"{archive}.sha256")
    if not sum_file.is_file():
        raise Stop(f"the checksum file {sum_file.name} isn't next to the archive. "
                   "Download it from the same release.")
    try:
        first = sum_file.read_text(encoding="utf-8").splitlines()
        data = archive.read_bytes()
    except (OSError, UnicodeDecodeError):
        raise Stop("the archive or its checksum file can't be read.")
    expected = first[0].split()[0].lower() if first and first[0].split() else ""
    if not expected or expected != hashlib.sha256(data).hexdigest():
        raise Stop("the archive doesn't match its checksum: it is damaged or not the one "
                   "released. Download both files again.")
    return data


def _inside(path: str, top: str) -> bool:
    return path == top or path.startswith(top + "/")


def check_members(data: bytes, app_name: str):
    """(top folder, members) if every entry is a file, folder or shortcut
    inside one top folder; otherwise Stop."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            members = tar.getmembers()
    except (tarfile.TarError, OSError, EOFError):
        raise Stop("the archive can't be read.")
    top = None
    for member in members:
        name = posixpath.normpath(member.name)
        if member.name.startswith("/") or name == ".." or name.startswith("../"):
            raise Stop("the archive holds a path outside its own folder.")
        first = name.split("/", 1)[0]
        if top is None:
            top = first
        elif first != top:
            raise Stop(f"the archive isn't a {app_name} release: it holds more than one "
                       "top folder.")
        if member.issym():
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname))
            if member.linkname.startswith("/") or not _inside(target, top):
                raise Stop("the archive holds a path outside its own folder.")
        elif not (member.isfile() or member.isdir()):
            raise Stop(f"the archive isn't a {app_name} release: it holds something that "
                       "is neither a file nor a folder.")
    if not top or top == ".":
        raise Stop("the archive is empty.")
    return top, members


def _unpack(data: bytes, members, into: Path) -> None:
    """Write the checked entries under into/: plain files and folders with
    ordinary permissions, and the shortcuts check_members allowed."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in members:
            path = into / posixpath.normpath(member.name)
            if member.isdir():
                path.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            if member.issym():
                os.symlink(member.linkname, path)
                continue
            with tar.extractfile(member) as source, open(path, "wb") as out:
                shutil.copyfileobj(source, out)
            path.chmod(0o755 if member.mode & 0o111 else 0o644)


# ---------------------------------------------------------------- the layout

def current_version_folder(app_dir: Path, mark: str):
    """("none", None), ("link", folder in versions/) or ("folder", app_dir)
    for an install made before versions/ existed. Stop for anything this
    installer didn't make."""
    app_dir = Path(app_dir)
    versions = app_dir.parent / VERSIONS
    if app_dir.is_symlink():
        target = Path(os.path.realpath(app_dir))
        if target.parent == Path(os.path.realpath(versions)):
            if target.is_dir() and (target / mark).is_file():
                return "link", target
            # Ours, but its version folder is gone: installed afresh.
            return "none", None
    elif not app_dir.exists():
        return "none", None
    elif app_dir.is_dir() and (app_dir / mark).is_file():
        return "folder", app_dir
    raise Stop(f"{app_dir} is already there and wasn't made by this installer, so it is "
               "left alone. Move it away and run the install again.")


def _point_app_at(app_dir: Path, folder: Path) -> None:
    """Make app_dir a shortcut to folder in one step: a new shortcut is
    made beside it, then renamed over it."""
    temporary = app_dir.with_name(f".{app_dir.name}-{secrets.token_hex(4)}")
    os.symlink(os.path.relpath(folder, app_dir.parent), temporary)
    try:
        os.replace(temporary, app_dir)
    except OSError:
        temporary.unlink()
        raise


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _clear_others(versions: Path, keep: Path) -> None:
    """Remove every folder in versions/ but the current one: the previous
    version, and anything left by an interrupted run."""
    for entry in versions.iterdir():
        if entry.name != keep.name:
            try:
                _remove(entry)
            except OSError:
                pass  # tried again by the next update


def _lock(versions: Path) -> int:
    """One install or update at a time."""
    handle = os.open(versions, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        raise Stop("another install or update is running. Wait for it to finish, then try "
                   "again.")
    return handle


# ---------------------------------------------------------------- the first start

class _PageFiles(HTMLParser):
    """The stylesheets and scripts a page links, on its own server."""

    def __init__(self):
        super().__init__()
        self.files = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        link = None
        if tag == "script":
            link = attrs.get("src")
        elif tag == "link" and "stylesheet" in (attrs.get("rel") or "").split():
            link = attrs.get("href")
        if link and not re.match(r"^([a-z][a-z0-9+.-]*:|//)", link, re.I):
            self.files.append("/" + link.lstrip("/"))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _ask(port: int, path: str, method: str = "GET", timeout: float = 5.0):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method,
        data=b"{}" if method == "POST" else None,
        headers={"Content-Type": "application/json"} if method == "POST" else {})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return answer.status, answer.read()


def started_cleanly(app_dir: Path, environ: Optional[Mapping[str, str]] = None,
                    timeout: float = START_TIMEOUT):
    """(True, "") if the version in app_dir starts cleanly, else (False, why).

    Started cleanly means, with no person needed: the app's server starts
    from app_dir on a free port, reads this person's settings file without
    a mistake, and keeps running; within `timeout` seconds its page answers
    with HTML; every stylesheet and script the page links answers too; and
    the app answers a question (/api/onboarding). It is then asked to close.
    It runs as a fresh start (START_ENV_SET), so its data folder is an empty
    temporary one: the person's data folder is never opened. No window
    opens, nothing plays, nothing is scanned, and the settings file is only
    read."""
    env = {k: v for k, v in (os.environ if environ is None else environ).items()
           if k not in START_ENV_DROPPED}
    env.update(START_ENV_SET)
    port = _free_port()
    env["KETTLE_VIDEO_PORT"] = str(port)
    env["KETTLE_VIDEO_LAUNCH_START"] = f"{time.time():.3f}"
    try:
        server = subprocess.Popen([sys.executable, "-m", "backend.server"], cwd=app_dir,
                                  env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
    except OSError as problem:
        return False, f"it couldn't be started ({problem.strerror or problem})."
    # Its output is read as it comes (so it never waits on a full pipe);
    # only the last lines are kept, to say why it stopped.
    last_lines = collections.deque(maxlen=5)
    reader = threading.Thread(target=lambda: last_lines.extend(
        line.decode("utf-8", "replace").strip() for line in server.stdout), daemon=True)
    reader.start()

    def said():
        reader.join(2)
        lines = [line for line in last_lines if line]
        return f" It said: {lines[-1]}" if lines else ""

    try:
        deadline = time.monotonic() + timeout
        page = None
        while page is None:
            if server.poll() is not None:
                return False, "it stopped as soon as it started." + said()
            if time.monotonic() > deadline:
                return False, f"it didn't answer within {int(timeout)} seconds."
            try:
                status, page = _ask(port, "/")
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        if status != 200 or b"<html" not in page.lower():
            return False, "its page didn't load."
        files = _PageFiles()
        files.feed(page.decode("utf-8", "replace"))
        for path in files.files:
            try:
                status, _ = _ask(port, path)
            except (OSError, urllib.error.URLError):
                status = None
            if status != 200:
                return False, f"its page didn't load: {path.lstrip('/')} is missing."
        try:
            status, body = _ask(port, "/api/onboarding")
            json.loads(body)
        except (OSError, urllib.error.URLError, ValueError):
            return False, "it didn't answer once its page had loaded." + said()
        return True, ""
    finally:
        try:
            _ask(port, "/api/shutdown", "POST", timeout=2.0)
        except (OSError, urllib.error.URLError):
            pass
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        reader.join(2)
        server.stdout.close()


# ---------------------------------------------------------------- install or update

def install(archive: Path, app_dir: Path, mark: str, app_name: str = "Kettle Video",
            confirm_older: Optional[Callable[[str, str], bool]] = None,
            say: Callable[[str], None] = print,
            start_check: Callable = started_cleanly,
            environ: Optional[Mapping[str, str]] = None) -> Result:
    """Install the archive's version into app_dir, or update the version
    there. confirm_older(old, new) is asked before going back to an older
    version (no answer means no). Every outcome is a Result with a plain
    message, which has also been said."""
    app_dir = Path(app_dir)

    def done(outcome, old, new, message):
        if message:
            say(message)
        return Result(outcome, old, new, message)

    # Which version is installed, if any, for the messages.
    try:
        kind, previous = current_version_folder(app_dir, mark)
        old = _read_version(previous) if previous else None
    except Stop:
        old = None

    # 1. Checks, before anything is touched.
    try:
        say(f"Checking {Path(archive).name} against its checksum")
        data = read_checked(archive)
        say("  The checksum matches.")
        top, members = check_members(data, app_name)
        kind, previous = current_version_folder(app_dir, mark)
    except Stop as problem:
        return done(STOPPED, old, None, _stopped(problem, app_name, old))

    versions = app_dir.parent / VERSIONS
    made = [folder for folder in (app_dir.parent, versions) if not folder.exists()]
    try:
        versions.mkdir(parents=True, exist_ok=True)
        handle = _lock(versions)
    except Stop as problem:
        return done(STOPPED, old, None, _stopped(problem, app_name, old))
    except OSError as problem:
        return done(STOPPED, old, None, _stopped(
            Stop(f"couldn't make {versions} ({problem.strerror})."), app_name, old))
    try:
        result = _place(data, top, members, app_dir, versions, kind, previous, old, mark,
                        app_name, confirm_older, say, start_check, environ, done)
    finally:
        os.close(handle)
    if result.outcome in (STOPPED, DECLINED):
        # Folders this run made and left empty go again.
        for folder in reversed(made):
            try:
                folder.rmdir()
            except OSError:
                pass
    return result


def _stopped(problem, app_name, old):
    if old:
        return (f"Update stopped: {problem}\n"
                f"Nothing was changed: {app_name} {old} is still installed.")
    return f"Install stopped: {problem}\nNothing was installed or changed."


def _place(data, top, members, app_dir, versions, kind, previous, old, mark, app_name,
           confirm_older, say, start_check, environ, done):
    stage = None
    new_folder = None
    new = None
    switched = False
    moved_old_folder = False
    try:
        # 2. Unpack beside the installed version.
        stage = Path(tempfile.mkdtemp(prefix=".unpack-", dir=versions))
        _checkpoint("unpacking")
        _unpack(data, members, stage)
        unpacked = stage / top
        new = _read_version(unpacked)
        if new is None or not all((unpacked / name).is_file() for name in REQUIRED):
            raise Stop(f"the archive isn't a {app_name} release.")

        # 3. Which versions.
        if old:
            say(f"Installed now: {app_name} {old}")
            say(f"This archive:  {app_name} {new}")
            if is_older(new, old):
                say(f"Warning: {new} is older than the {old} you have. Going back is "
                    "possible, but a newer version may have saved your library in a way "
                    "an older one doesn't fully read.")
                if not (confirm_older and confirm_older(old, new)):
                    _remove(stage)
                    return done(DECLINED, old, new,
                                f"Nothing was changed: {app_name} {old} is still installed.")
            elif new == old:
                say("That is the version you have; its app files are put in again.")

        (unpacked / mark).write_text(
            f"{app_name} installed copy, version {new}.\n"
            "Its settings, data and logs live outside this folder.\n", encoding="utf-8")
        (unpacked / "launch.sh").chmod(0o755)
        new_folder = versions / _folder_name(new)
        os.rename(unpacked, new_folder)
        _remove(stage)
        stage = None
        _checkpoint("unpacked")
        # Everything on disk before the switch, so a power cut can't leave
        # the switch done but the files not yet written.
        os.sync()

        # 4. Switch.
        if kind == "folder":
            # The first update of an install made before versions/: its plain
            # folder moves into versions/ (the only moment the app folder is
            # missing, between two renames), then becomes a shortcut.
            moved = versions / _folder_name(old or "previous")
            os.rename(app_dir, moved)
            previous = moved
            moved_old_folder = True
            _checkpoint("moved the old folder")
        _point_app_at(app_dir, new_folder)
        switched = True
        os.sync()
        _checkpoint("switched")
        say(f"  App files placed in {app_dir}")

        # 5. The first start.
        if previous is not None:
            say(f"Checking that {app_name} {new} starts cleanly")
            ok, why = start_check(app_dir, environ)
            _checkpoint("checked")
            if not ok:
                raise Failed(f"{app_name} {new} didn't start cleanly: {why}")
            say("  It started cleanly.")

        # 6. The previous version goes only now.
        _clear_others(versions, new_folder)
    except Stop as problem:
        _undo(stage, new_folder, app_dir, previous, switched, moved_old_folder)
        return done(STOPPED, old, new, _stopped(problem, app_name, old))
    except (Failed, OSError, tarfile.TarError) as problem:
        why = problem if isinstance(problem, Failed) else _plain(problem)
        put_back = _undo(stage, new_folder, app_dir, previous, switched, moved_old_folder)
        if not old:
            return done(STOPPED, None, new,
                        f"Install stopped: {why}\nNothing was installed or changed.")
        if put_back:
            return done(ROLLED_BACK, old, new,
                        f"The update to {new} didn't work: {why}\n"
                        f"Rolled back: {app_name} {old} is installed again, as it was. Your "
                        "settings, library and logs were not touched.")
        return done(ROLLED_BACK, old, new,
                    f"The update to {new} didn't work: {why}\n"
                    f"{app_name} {old} couldn't be put back either. Run the installer again "
                    f"with the {old} archive. Your settings, library and logs were not touched.")
    if old:
        return done(UPDATED, old, new, f"Updated {app_name} from {old} to {new}.")
    return done(INSTALLED, None, new, "")


def _plain(problem: Exception) -> str:
    if isinstance(problem, OSError):
        if problem.errno == errno.ENOSPC:
            return "the disk is full."
        return f"a file couldn't be written ({problem.strerror or problem})."
    return "the archive couldn't be unpacked."


def _folder_name(version: str) -> str:
    """A version's folder in versions/: its version, plus a few random
    letters so installing the same version again never meets the old one."""
    return f"{re.sub(r'[^A-Za-z0-9._-]', '_', version)[:40]}-{secrets.token_hex(3)}"


def _undo(stage, new_folder, app_dir, previous, switched, moved_old_folder=False) -> bool:
    """Put the previous version back (if the switch happened) and remove the
    new one. True once the app folder is the previous version again (or,
    for a first install, gone)."""
    put_back = True
    try:
        if switched:
            if previous is not None:
                _point_app_at(app_dir, previous)
            else:
                app_dir.unlink()
            os.sync()
        elif moved_old_folder:
            # Moved into versions/ but the shortcut wasn't made: move it back.
            os.rename(previous, app_dir)
            os.sync()
    except OSError:
        put_back = False
    for leftover in (stage, new_folder if put_back else None):
        if leftover is not None:
            try:
                _remove(leftover)
            except OSError:
                pass  # cleared by the next run
    return put_back


# ---------------------------------------------------------------- command line

def _ask_older(old: str, new: str) -> bool:
    """Ask on the terminal. One line is read, a byte at a time, so the
    installer's later questions get their own answers."""
    print(f"Install {new} anyway? [y/N] ", end="", flush=True)
    answer = b""
    while True:
        try:
            byte = os.read(0, 1)
        except OSError:
            break
        if not byte or byte == b"\n":
            break
        answer += byte
    print()
    return answer.decode("utf-8", "replace").strip().lower() in ("y", "yes")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="update.py",
                                     description="Install or update the app files.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("install")
    run.add_argument("archive")
    run.add_argument("--app-dir", required=True)
    run.add_argument("--mark", required=True)
    run.add_argument("--name", default="Kettle Video")
    args = parser.parse_args(argv)
    say = lambda text: print(text, flush=True)  # noqa: E731
    result = install(Path(args.archive), Path(args.app_dir), args.mark, args.name,
                     confirm_older=_ask_older, say=say)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
