#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The one-file installer (the one-file install work).

The release script (tools/release.py) writes this file into a desktop
launcher, install-<ARCHIVE_NAME>.desktop, which goes on every release. A
viewer downloads that one file and double-clicks it in Desktop Mode; the
file manager asks once whether to run a program it doesn't know yet, and
then this runs. What it does, in order:

  1. says what it will do and where, and asks. Nothing goes online before
     a yes (Kettle Video never goes online by itself);
  2. asks GitHub for the latest release. GitHub's "latest release" is
     never a pre-release or a draft, and an answer marked as either is
     refused anyway. On a device with Kettle Video already installed, it
     then says which version is installed and which it will install, and
     asks again;
  3. downloads that release's archive and its checksum file into a new
     temporary folder, from this repo's GitHub releases only, over HTTPS,
     and checks the archive against the checksum;
  4. takes the installer (installer/install.sh, update.py and names.env)
     from inside the checked archive and runs it on the archive: exactly
     the steps of running install.sh by hand, written once. App files are
     replaced, settings, data and logs are kept, mpv is checked and
     offered the same way;
  5. says what happened: success with the next step (Add to Steam), or a
     plain error saying nothing was installed. The temporary folder is
     removed whatever happened.

The windows come from zenity or kdialog when the desktop has one;
otherwise the same questions and lines are shown in a terminal window.
In a window, the installer's own terminal questions are asked in the
window first and their answers handed to it (the older-version question
on its input, the mpv one through KETTLE_VIDEO_MPV_ANSWER).

Standard library only. No sudo, nothing outside the viewer's home folder
and the temporary folder; Steam's files, media files and any development
copy are never touched.
"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# This app's repo on GitHub (backend/update_check.py says the same; a test
# checks it).
REPO = "enamelware/kettle-video"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_BASE = f"https://github.com/{REPO}/releases/download/"
USER_AGENT = "Kettle-Video-installer"
TIMEOUT_S = 30
CHUNK = 64 * 1024
MAX_DOWNLOAD = 500 * 1024 * 1024
MAX_ANSWER = 2_000_000
MPV_FLATPAK = "io.mpv.Mpv"
MPV_COMMAND = f"flatpak install flathub {MPV_FLATPAK}"
# Set when this program has opened itself in a terminal window.
IN_TERMINAL = "KETTLE_VIDEO_IN_TERMINAL"
# The mpv answer given in a window, handed to install.sh.
MPV_ANSWER = "KETTLE_VIDEO_MPV_ANSWER"
# Exit codes: 0 installed, 1 stopped with nothing installed, 2 the update
# failed and the previous version was put back (install.sh's own), 3 the
# viewer said no.
CANCELLED = 3

# The desktop launcher holds this program as comment lines after MARKER.
# Its Exec line runs BOOTSTRAP with the launcher's own path (%k): it reads
# the lines after MARKER, drops their "# " and runs them. BOOTSTRAP is
# written into a quoted Exec value, so it never holds a double quote, a
# backquote, a dollar sign, a backslash or a percent sign (a test checks).
MARKER = "## --- one-file installer ---"
BOOTSTRAP = ("import sys;p=sys.argv[1];L=open(p,encoding='utf-8').read().split(chr(10));"
             "i=L.index('## --- one-file installer ---');"
             "exec(compile(chr(10).join(l[2:] for l in L[i+1:]),p,'exec'),"
             "{'__name__':'__main__','LAUNCHER':p})")

NAME_KEYS = ("APP_NAME", "APP_ID", "ARCHIVE_NAME", "INSTALL_MARK")

# --- names ---
# The release script writes installer/names.env's KEY="value" lines in
# here (they are Python too). Run from the repo, names.env beside this file
# is read instead.
# --- end names ---


class Problem(Exception):
    """Stops the install before anything was placed; the message is said
    to the viewer as it is."""


# ---------------------------------------------------------------- names and places

def read_names_text(text):
    """{KEY: value} from names.env's KEY="value" lines."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"')
    return out


def names():
    """The app's names: written in by the release, or names.env beside
    this file."""
    found = {key: globals()[key] for key in NAME_KEYS if isinstance(globals().get(key), str)}
    if len(found) == len(NAME_KEYS):
        return found
    here = globals().get("__file__")
    if here:
        env_file = Path(here).resolve().parent / "names.env"
        if env_file.is_file():
            found = read_names_text(env_file.read_text(encoding="utf-8"))
    missing = [key for key in NAME_KEYS if not found.get(key)]
    if missing:
        raise Problem("This file is missing its names. Download it again from the release page.")
    return {key: found[key] for key in NAME_KEYS}


def app_dir(app_id, environ):
    """Where install.sh puts the app files (install.sh's place(), and
    backend/app_paths.py, say the same)."""
    data_home = environ.get("XDG_DATA_HOME") or ""
    if not data_home.startswith("/"):
        data_home = os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".local/share")
    return Path(data_home) / app_id / "app"


def installed_version(folder, mark):
    """The installed copy's version: None when nothing is installed, "" when
    one is but its version can't be read."""
    folder = Path(folder)
    if not (folder / mark).is_file():
        return None
    try:
        return (folder / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------- GitHub

def default_open(request, timeout):
    """The standard library's own web client, with no cookie store."""
    return urllib.request.build_opener().open(request, timeout=timeout)


def _request(url, accept):
    # Nothing but the question and a plain user agent: no cookies, no
    # identifiers.
    return urllib.request.Request(url, method="GET", headers={
        "User-Agent": USER_AGENT, "Accept": accept})


def _offline(reason):
    """No connection at all: the name can't be looked up, or there is no
    network to send it on (backend/update_check.py's rule)."""
    if isinstance(reason, socket.gaierror):
        return True
    return isinstance(reason, OSError) and reason.errno in (101, 113)


def _no_connection(app):
    return Problem("There's no internet connection, so the latest release of "
                   f"{app['APP_NAME']} couldn't be downloaded. Connect to the internet, "
                   "then open this file again.")


def _unreachable(why):
    return Problem(f"GitHub couldn't be reached right now ({why}). Try again later.")


def _ask_github(open_url, url, accept, app):
    """open_url's answer, or Problem in plain words."""
    try:
        return open_url(_request(url, accept), TIMEOUT_S)
    except urllib.error.HTTPError as exc:  # rate-limited, missing, down
        exc.close()
        raise _unreachable(f"GitHub answered {exc.code}")
    except urllib.error.URLError as exc:
        if _offline(exc.reason):
            raise _no_connection(app)
        raise _unreachable(f"no answer: {type(exc.reason).__name__}")
    except (TimeoutError, socket.timeout):
        raise _unreachable("no answer in time")
    except OSError as exc:
        if _offline(exc):
            raise _no_connection(app)
        raise _unreachable(f"no answer: {type(exc).__name__}")


def latest_release(open_url, app):
    """The latest full release: {"version", "archive", "checksum", "file",
    "size"}. Raises Problem."""
    answer = _ask_github(open_url, LATEST_URL, "application/vnd.github+json", app)
    try:
        with answer:
            data = json.loads(answer.read(MAX_ANSWER).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, OSError):
        raise _unreachable("its answer couldn't be read")
    nothing = Problem(f"GitHub's latest release of {app['APP_NAME']} has nothing this file "
                      "can install.")
    if not isinstance(data, dict) or data.get("draft") is not False \
            or data.get("prerelease") is not False:
        raise nothing
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9][0-9A-Za-z.+-]*", tag):
        raise nothing
    version = tag[1:]
    wanted = f"{app['ARCHIVE_NAME']}-{version}.tar.gz"
    found = {}
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        url, name = asset.get("browser_download_url"), asset.get("name")
        if not isinstance(url, str) or url != f"{DOWNLOAD_BASE}{tag}/{name}":
            continue
        if name == wanted:
            found["archive"] = url
            found["size"] = asset.get("size") if isinstance(asset.get("size"), int) else None
        elif name == wanted + ".sha256":
            found["checksum"] = url
    if "archive" not in found or "checksum" not in found:
        raise nothing
    return {**found, "version": version, "file": wanted}


def download(open_url, url, dest, app, progress=lambda done, total: None,
             limit=MAX_DOWNLOAD):
    """One file from this repo's GitHub releases into dest. Raises Problem."""
    if not url.startswith(DOWNLOAD_BASE):
        raise _unreachable("not a release address")
    answer = _ask_github(open_url, url, "application/octet-stream", app)
    try:
        with answer, open(dest, "wb") as out:
            total = answer.headers.get("Content-Length") if answer.headers else None
            total = int(total) if total and str(total).isdigit() else None
            done = 0
            progress(done, total)
            while True:
                piece = answer.read(CHUNK)
                if not piece:
                    break
                done += len(piece)
                if done > limit:
                    raise _unreachable("the download is bigger than any release")
                out.write(piece)
                progress(done, total)
    except (TimeoutError, socket.timeout):
        raise _unreachable("the download stopped part way")
    except OSError as exc:
        if _offline(exc):
            raise _no_connection(app)
        raise _unreachable(f"the download stopped part way: {type(exc).__name__}")
    if total is not None and done != total:
        raise _unreachable("the download stopped part way")


def check_checksum(archive, sums):
    """Raises Problem unless sums (the .sha256 file) names archive and its
    SHA-256 matches."""
    mismatch = Problem("The download doesn't match its checksum, so it may be damaged or "
                       "changed on the way. Try again later.")
    try:
        first = Path(sums).read_text(encoding="utf-8").splitlines()[0].split()
    except (OSError, IndexError, UnicodeDecodeError):
        raise mismatch
    if len(first) != 2 or first[1].lstrip("*") != Path(archive).name \
            or not re.fullmatch(r"[0-9a-fA-F]{64}", first[0]):
        raise mismatch
    digest = hashlib.sha256()
    with open(archive, "rb") as data:
        for piece in iter(lambda: data.read(CHUNK), b""):
            digest.update(piece)
    if digest.hexdigest() != first[0].lower():
        raise mismatch


INSTALLER_FILES = ("install.sh", "update.py", "names.env")


def extract_installer(archive, into):
    """The installer's three files, from inside the checked archive, into
    into/installer/. Returns install.sh's path. Raises Problem."""
    top = Path(archive).name[:-len(".tar.gz")]
    folder = Path(into) / "installer"
    folder.mkdir()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for name in INSTALLER_FILES:
                member = tar.getmember(f"{top}/installer/{name}")
                if not member.isfile():
                    raise KeyError(name)
                (folder / name).write_bytes(tar.extractfile(member).read())
    except (KeyError, OSError, tarfile.TarError, EOFError):
        raise Problem("This release can't be installed with the one file. Use the other "
                      "way to install in the README instead.")
    return folder / "install.sh"


def is_older(updater, new, old):
    """update.py's own rule, from the checked archive's update.py."""
    spec = importlib.util.spec_from_file_location("kettle_video_one_file_update", updater)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return bool(module.is_older(new, old))
    finally:
        sys.modules.pop(spec.name, None)


def mpv_state(which=shutil.which, run=subprocess.run):
    """install.sh's mpv check: "found", "missing" or "no-flatpak"."""
    if which("mpv"):
        return "found"
    flatpak = which("flatpak")
    if not flatpak:
        return "no-flatpak"
    checked = run([flatpak, "info", MPV_FLATPAK], stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL)
    return "found" if checked.returncode == 0 else "missing"


# ---------------------------------------------------------------- what the viewer sees

class TerminalUI:
    """Short plain lines in a terminal. pause: wait for Enter before the
    window closes (when this program opened the window itself)."""

    terminal = True

    def __init__(self, pause=False, write=None, read=None):
        self.pause = pause
        self.write = write or (lambda text: print(text, flush=True))
        self.read = read or input
        self._last = None

    def ask(self, text, yes, no):
        self.write("")
        self.write(text)
        try:
            answer = self.read(f"{yes}? [y/N] ")
        except EOFError:
            answer = ""
        return answer.strip().lower() in ("y", "yes")

    def step(self, text, percent=None):
        line = text if percent is None else f"{text} {percent // 25 * 25}%"
        if line != self._last:
            self.write(f"  {line}")
            self._last = line

    def hide(self):
        self._last = None

    def info(self, text):
        self.write("")
        self.write(text)

    error = info

    def finish(self):
        if self.pause:
            self.write("")
            try:
                self.read("Press Enter to close this window.")
            except EOFError:
                pass


class KDialogUI:
    """Windows from kdialog. Its progress window is moved by D-Bus calls,
    best effort: if they fail, the window just doesn't move."""

    terminal = False

    def __init__(self, title, run=subprocess.run):
        self.title = title
        self.run = run
        self.bar = None

    def _dialog(self, *args):
        return self.run(["kdialog", "--title", self.title, *args])

    def ask(self, text, yes, no):
        self.hide()
        return self._dialog("--yes-label", yes, "--no-label", no, "--yesno", text).returncode == 0

    def _call(self, *args):
        if self.bar:
            self.run(["dbus-send", "--session", f"--dest={self.bar[0]}", self.bar[1], *args],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _set(self, name, value):
        self._call("org.freedesktop.DBus.Properties.Set",
                   "string:org.kde.kdialog.ProgressDialog", f"string:{name}",
                   f"variant:int32:{value}")

    def step(self, text, percent=None):
        if self.bar is None:
            made = self.run(["kdialog", "--title", self.title, "--progressbar", text, "100"],
                            capture_output=True, text=True)
            parts = (made.stdout or "").split()
            self.bar = (parts[0], parts[1]) if made.returncode == 0 and len(parts) == 2 else ()
        else:
            self._call("org.kde.kdialog.ProgressDialog.setLabelText", f"string:{text}")
        if percent is None:
            self._set("maximum", 0)  # a moving bar: no end known
        else:
            self._set("maximum", 100)
            self._set("value", percent)

    def hide(self):
        self._call("org.kde.kdialog.ProgressDialog.close")
        self.bar = None

    def info(self, text):
        self.hide()
        self._dialog("--msgbox", text)

    def error(self, text):
        self.hide()
        self._dialog("--error", text)

    def finish(self):
        self.hide()


class ZenityUI:
    """Windows from zenity."""

    terminal = False

    def __init__(self, title, run=subprocess.run, popen=subprocess.Popen):
        self.title = title
        self.run = run
        self.popen = popen
        self.bar = None
        self.moving = None

    def _dialog(self, kind, text, *more):
        return self.run(["zenity", kind, "--title", self.title, "--width", "460",
                         "--text", html.escape(text, quote=False), *more])

    def ask(self, text, yes, no):
        self.hide()
        return self._dialog("--question", text, "--ok-label", yes,
                            "--cancel-label", no).returncode == 0

    def step(self, text, percent=None):
        moving = percent is None
        if self.bar is not None and self.moving != moving:
            self.hide()
        if self.bar is None:
            self.bar = self.popen(["zenity", "--progress", "--title", self.title, "--width",
                                   "460", "--no-cancel", *(["--pulsate"] if moving else [])],
                                  stdin=subprocess.PIPE, text=True)
            self.moving = moving
        try:
            self.bar.stdin.write(f"# {html.escape(text, quote=False)}\n")
            if not moving:
                self.bar.stdin.write(f"{min(percent, 99)}\n")
            self.bar.stdin.flush()
        except (OSError, ValueError):
            pass

    def hide(self):
        if self.bar is not None:
            try:
                self.bar.terminate()
                self.bar.wait(5)
            except (OSError, subprocess.SubprocessError):
                pass
            self.bar = None

    def info(self, text):
        self.hide()
        self._dialog("--info", text)

    def error(self, text):
        self.hide()
        self._dialog("--error", text)

    def finish(self):
        self.hide()


def choose_ui(title, environ, which=shutil.which, isatty=None):
    """A window if the desktop has zenity or kdialog, else this terminal;
    None when there is neither (the caller opens a terminal window)."""
    if environ.get(IN_TERMINAL) == "1":
        return TerminalUI(pause=True)
    if environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"):
        # zenity first, as for the app's start-up message (docs/spec.md).
        if which("zenity"):
            return ZenityUI(title)
        if which("kdialog"):
            return KDialogUI(title)
    if (isatty or sys.stdin.isatty)():
        return TerminalUI()
    return None


TERMINALS = (("konsole", ["-e"]), ("gnome-terminal", ["--"]),
             ("xfce4-terminal", ["-x"]), ("xterm", ["-e"]))


def open_in_terminal(argv, environ, which=shutil.which, popen=subprocess.Popen):
    """Runs argv again in a terminal window. False if there is none."""
    for name, flag in TERMINALS:
        found = which(name)
        if found:
            popen([found, *flag, *argv], env={**environ, IN_TERMINAL: "1"})
            return True
    return False


# ---------------------------------------------------------------- the install

def _installer_tail(output, count=8):
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def _summary(output):
    """install.sh's closing summary, from its "Done." line."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Done. "):
            return "\n".join(lines[i:]).strip()
    return output.strip()


def install(ui, open_url=default_open, environ=None, run=subprocess.run,
            which=shutil.which, temp_parent=None, euid=os.geteuid):
    """The whole install, said through ui. Returns the exit code."""
    environ = dict(os.environ if environ is None else environ)
    try:
        app = names()
    except Problem as problem:
        ui.error(str(problem))
        return 1
    name = app["APP_NAME"]
    folder = app_dir(app["APP_ID"], environ)
    if euid() == 0:
        ui.error(f"Open this file as yourself, not as root. {name} installs into your own "
                 "home folder and never needs a password.\n\nNothing was installed.")
        return 1
    if not ui.ask(f"This installs {name} in your home folder:\n{folder}\n\n"
                  f"It first asks GitHub for the latest release of {name} and downloads it "
                  f"from github.com/{REPO}. GitHub sees your IP address; nothing else "
                  "about you is sent.\n\nIt needs no password and never changes the "
                  "system or Steam's own files.", "Continue", "Cancel"):
        return CANCELLED

    old = installed_version(folder, app["INSTALL_MARK"])
    temp = Path(tempfile.mkdtemp(prefix=f"{app['APP_ID']}-install-", dir=temp_parent))
    try:
        ui.step("Asking GitHub for the latest release…")
        release = latest_release(open_url, app)
        new = release["version"]
        if old is not None:
            was = f"{name} {old}" if old else f"An earlier version of {name}"
            if not ui.ask(f"{was} is installed.\nThis installs {name} {new} in its place.\n\n"
                          "Your settings, library and Continue watching are kept, and "
                          "the folders you chose stay chosen.", f"Install {new}", "Cancel"):
                return CANCELLED
        archive = temp / release["file"]
        sums = temp / (release["file"] + ".sha256")
        label = f"Downloading {name} {new}…"

        def moved(done, total):
            ui.step(label, None if not total else min(100, done * 100 // total))

        download(open_url, release["archive"], archive, app, moved)
        download(open_url, release["checksum"], sums, app, limit=4096)
        ui.step("Checking the download…")
        check_checksum(archive, sums)
        script = extract_installer(archive, temp)

        env = {key: value for key, value in environ.items() if key != MPV_ANSWER}
        older = ""
        if not ui.terminal:
            if old and is_older(script.parent / "update.py", new, old):
                if not ui.ask(f"The installed version, {old}, is newer than the latest "
                              f"release, {new}. Install {new} anyway?",
                              f"Install {new}", f"Keep {old}"):
                    ui.info(f"Nothing was changed: {name} {old} is still installed.")
                    return CANCELLED
                older = "y\n"
            if mpv_state(which, run) == "missing":
                yes = ui.ask(f"mpv isn't installed. {name} plays every film and episode in "
                             "mpv, so it needs it.\n\nIt can be installed from Flathub now, "
                             f"with this command:\n{MPV_COMMAND}\n\nInstall mpv now?",
                             "Install mpv", "Not now")
                env[MPV_ANSWER] = "yes" if yes else "no"
            ui.step(f"Installing {name} {new}…")
            done = run(["bash", str(script), str(archive)], input=older, env=env,
                       capture_output=True, text=True)
            output = (done.stdout or "") + (done.stderr or "")
        else:
            ui.hide()
            done = run(["bash", str(script), str(archive)], env=env)
            output = ""
        ui.hide()
    except Problem as problem:
        ui.hide()
        kept = f"Nothing was changed: {name} {old} is still installed." if old \
            else "Nothing was installed."
        ui.error(f"{problem}\n\n{kept}")
        return 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    if done.returncode == 0:
        if not ui.terminal:
            ui.info(_summary(output))
        return 0
    if not ui.terminal:
        ui.error(f"{name} {new} wasn't installed.\n\n{_installer_tail(output)}")
    return done.returncode


def relaunch_argv():
    """How to start this program again: from the desktop launcher, or from
    this file."""
    launcher = globals().get("LAUNCHER")
    python = sys.executable or "python3"
    if launcher:
        return [python, "-I", "-c", BOOTSTRAP, launcher]
    return [python, "-I", str(Path(globals()["__file__"]).resolve())]


def main():
    try:
        title = f"Install {names()['APP_NAME']}"
    except Problem:
        title = "Install"
    ui = choose_ui(title, os.environ)
    if ui is None:
        if open_in_terminal(relaunch_argv(), os.environ):
            return 0
        print("No window or terminal could be opened. Run this file from a terminal.")
        return 1
    try:
        return install(ui)
    finally:
        ui.finish()


if __name__ == "__main__":
    sys.exit(main())
