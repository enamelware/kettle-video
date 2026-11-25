# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the folder dialog spike): which folder dialogs this device has, and
opening each one in folder mode.

Nothing is installed and nothing is written: each dialog is only asked to
*choose* a folder. Output is private by default: a returned folder is
described as "<place>, N levels down" (place from the storage spike's drive
list, the storage spike), never by its name. --real shows real paths, on screen only.

    python3 spikes/folder-dialog/dialogs.py            Question 1: the checks
    python3 spikes/folder-dialog/dialogs.py open NAME  open one dialog, by hand

Dialogs: portal (the desktop portal's file chooser), kdialog (KDE),
zenity (GTK), tk (Python's own Tk dialog).
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "storage"))

import dbus_session  # noqa: E402
import drives  # noqa: E402  the storage spike's drive list (the storage spike)
from common import SHOW_REAL, Redactor  # noqa: E402

TITLE = "Choose a folder (Kettle spike)"
NAMES = ["portal", "kdialog", "zenity", "tk"]
PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
PORTAL_DIR = "/usr/share/xdg-desktop-portal/portals"
TK_CHILD = (
    "import sys, tkinter, tkinter.filedialog\n"
    "root = tkinter.Tk()\n"
    "root.withdraw()\n"
    "path = tkinter.filedialog.askdirectory(parent=root, title=sys.argv[1], mustexist=True)\n"
    "print(path or '')\n"
)


def _run(cmd, timeout=5):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout + done.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, str(err)


def _portal_backends():
    """Portal back-end files that offer a file chooser, and their desktops."""
    found = []
    try:
        names = sorted(os.listdir(PORTAL_DIR))
    except OSError:
        return found
    for name in names:
        try:
            text = open(os.path.join(PORTAL_DIR, name), encoding="utf-8").read()
        except OSError:
            continue
        if "org.freedesktop.impl.portal.FileChooser" in text:
            use_in = next((line.split("=", 1)[1] for line in text.splitlines()
                           if line.startswith("UseIn=")), "")
            found.append(f"{name} ({use_in or 'any desktop'})")
    return found


def checks():
    """Question 1: one entry per dialog, with the exact check and its result."""
    out = []
    try:
        bus = dbus_session.SessionBus()
        version = bus.get_property(*PORTAL, "org.freedesktop.portal.FileChooser", "version")
        bus.close()
        portal = (True, f"FileChooser version {version}; back ends with a file chooser: "
                        f"{', '.join(_portal_backends()) or 'none listed'}")
    except (OSError, dbus_session.DBusError) as err:
        portal = (False, f"no file chooser on the session bus ({err})")
    out.append({"name": "portal", "available": portal[0],
                "check": "read the property version of org.freedesktop.portal.FileChooser on the session bus",
                "result": portal[1]})
    for name, version_flag in (("kdialog", "--version"), ("zenity", "--version")):
        path = shutil.which(name)
        if path:
            code, text = _run([name, version_flag])
            result = (True, text.splitlines()[0] if code == 0 and text else f"found, but {version_flag} failed: {text}")
        else:
            result = (False, "not installed")
        out.append({"name": name, "available": result[0],
                    "check": f"look for {name} on the PATH, then {name} {version_flag}", "result": result[1]})
    code, text = _run([sys.executable, "-c", "import tkinter; print(tkinter.TkVersion)"])
    if code != 0:
        tk = (False, "Python's tkinter is not installed")
    elif not os.environ.get("DISPLAY"):
        tk = (False, f"tkinter {text} is installed, but there is no X display (DISPLAY is empty)")
    else:
        tk = (True, f"tkinter {text}, X display available (Tk runs through XWayland under Wayland)")
    out.append({"name": "tk", "available": tk[0],
                "check": "python3 -c 'import tkinter', and an X display in DISPLAY", "result": tk[1]})
    return out


def describe(path):
    """A returned path, without names: '<place>, N levels down'."""
    if not path:
        return ""
    if SHOW_REAL:
        return path
    best = None
    for place in drives.places():
        root = place["path"].rstrip("/") or "/"
        if path == root or path.startswith(root + "/"):
            if best is None or len(root) > len(best[1]):
                best = (place["name"], root)
    if best is None:
        return f"a folder outside internal storage and the cards, {path.count('/')} levels below /"
    depth = len([p for p in path[len(best[1]):].split("/") if p])
    return f"{best[0]}, {depth} level{'s' if depth != 1 else ''} down"


def _subprocess_dialog(cmd, close_after, cancel_codes=(1,)):
    """Runs a dialog program; stdout is the folder. close_after (seconds):
    stop it after that long, as the automatic check does."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as err:
        return {"result": "error", "detail": str(err)}
    try:
        out, err = proc.communicate(timeout=close_after)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.communicate()
        return {"result": "closed by the script", "seconds": round(time.monotonic() - started, 1),
                "detail": f"still open after {close_after} s"}
    seconds = round(time.monotonic() - started, 1)
    path = out.strip()
    if proc.returncode == 0 and path:
        return {"result": "path", "path": path, "seconds": seconds}
    if proc.returncode in cancel_codes or (proc.returncode == 0 and not path):
        return {"result": "cancel", "seconds": seconds}
    return {"result": "error", "seconds": seconds,
            "detail": f"exit {proc.returncode}: {err.strip().splitlines()[-1] if err.strip() else ''}"}


def _portal_dialog(close_after):
    started = time.monotonic()
    try:
        bus = dbus_session.SessionBus()
    except (OSError, dbus_session.DBusError) as err:
        return {"result": "error", "detail": str(err)}
    token = "kettle" + uuid.uuid4().hex[:12]
    sender = bus.unique_name.lstrip(":").replace(".", "_")
    handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    try:
        bus.add_match(f"type='signal',interface='org.freedesktop.portal.Request',"
                      f"member='Response',path='{handle}'")
        options = {"handle_token": ("s", token), "directory": ("b", True), "modal": ("b", True)}
        # No parent window: the page can't name Firefox's window to the portal.
        bus.call(*PORTAL, "org.freedesktop.portal.FileChooser", "OpenFile",
                 "ssa{sv}", ("", TITLE, options))
        answer = bus.wait_signal(handle, "Response", close_after if close_after else 24 * 3600)
        seconds = round(time.monotonic() - started, 1)
        if answer is None:
            bus.call(PORTAL[0], handle, "org.freedesktop.portal.Request", "Close")
            return {"result": "closed by the script", "seconds": seconds,
                    "detail": f"still open after {close_after} s"}
        code, results = answer
        if code == 0:
            uris = results.get("uris", [])
            path = urllib.parse.unquote(urllib.parse.urlparse(uris[0]).path) if uris else ""
            return {"result": "path", "path": path, "seconds": seconds,
                    "detail": "a file:// address" if uris and uris[0].startswith("file://") else f"{uris[:1]}"}
        return {"result": "cancel" if code == 1 else "error", "seconds": seconds,
                "detail": f"portal response code {code}"}
    except (OSError, dbus_session.DBusError) as err:
        return {"result": "error", "seconds": round(time.monotonic() - started, 1), "detail": str(err)}
    finally:
        bus.close()


def open_dialog(name, close_after=None):
    """Opens one dialog in folder mode, starting in the home folder. Returns
    a record: result (path / cancel / closed by the script / error)."""
    home = os.path.expanduser("~")
    if name == "portal":
        record = _portal_dialog(close_after)
    elif name == "kdialog":
        record = _subprocess_dialog(["kdialog", "--title", TITLE, "--getexistingdirectory", home], close_after)
    elif name == "zenity":
        record = _subprocess_dialog(["zenity", "--file-selection", "--directory", f"--title={TITLE}",
                                     f"--filename={home}/"], close_after)
    elif name == "tk":
        record = _subprocess_dialog([sys.executable, "-c", TK_CHILD, TITLE], close_after)
    else:
        record = {"result": "error", "detail": f"unknown dialog {name!r}"}
    record["dialog"] = name
    if "path" in record:
        record["where"] = describe(record.pop("path") if not SHOW_REAL else record["path"])
    return record


def main():
    args = [a for a in sys.argv[1:] if a != "--real"]
    if args[:1] == ["open"] and len(args) == 2:
        print(json.dumps(open_dialog(args[1]), indent=2))
        return
    for entry in checks():
        mark = "yes" if entry["available"] else "no "
        print(f"{mark}  {entry['name']:8} {entry['result']}\n      check: {entry['check']}")


if __name__ == "__main__":
    main()
