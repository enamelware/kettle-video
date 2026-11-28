# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Say on screen why Kettle couldn't start (the start-up problem screen).

In Gaming Mode there is no terminal, so a start-up failure that only went
into the log looked like the app opening and closing again. launch.sh uses
this module in two ways:

  python3 -m backend.startup_error text REASON LOGFILE
      prints the message as plain lines, for a system dialog when there is
      no Firefox to show the page in;
  python3 -m backend.startup_error serve REASON LOGFILE PORT
      serves the message page (ui/startup-error.html) on 127.0.0.1:PORT
      until the page asks to close (A or B), then ends, so the launcher
      closes Firefox as it does when the app quits.

REASON is one of REASONS. The module imports nothing from the app beyond the
settings reader, which it only uses to name a settings mistake: whatever
stopped the app's own server from starting must not stop this one too.

Back to main (the "Try a branch" work): on a development copy on a branch
that couldn't start, the page also offers Back to main, so a device is never
stuck on a broken branch. Its parts are imported only when needed, and if
they fail the page simply doesn't offer it.
"""

import json
import os
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NO_FIREFOX = "no-firefox"
BACKEND_STOPPED = "backend-stopped"
BACKEND_SILENT = "backend-silent"
REASONS = (NO_FIREFOX, BACKEND_STOPPED, BACKEND_SILENT)

PAGE = "/startup-error.html"
# The only files the page may ask for, by these exact paths, with their types.
FILES = {
    PAGE: ("ui/startup-error.html", "text/html; charset=utf-8"),
    "/js/startup_error.js": ("ui/js/startup_error.js", "text/javascript; charset=utf-8"),
    "/css/tokens.css": ("ui/css/tokens.css", "text/css; charset=utf-8"),
    "/css/defaults.css": ("ui/css/defaults.css", "text/css; charset=utf-8"),
    "/vendor/enamel/tokens/enamel.css": ("vendor/enamel/tokens/enamel.css", "text/css; charset=utf-8"),
    "/vendor/enamel/components/enamel-components.css":
        ("vendor/enamel/components/enamel-components.css", "text/css; charset=utf-8"),
}

TITLE = "Kettle couldn't start."
SETTINGS_FIX = "Fix it in settings.json, in Kettle's folder, then start Kettle again."


def settings_problem(root: Path = REPO, environ=None):
    """The settings reader's own plain sentence when settings.json has a
    mistake, else None. Anything unexpected also counts as None: the
    message then stays general rather than failing."""
    try:
        from backend import app_paths
        from backend.settings import SettingsError, load_settings
        load_settings(root, app_paths.for_app(root, environ))
    except SettingsError as exc:
        return str(exc)
    except Exception:
        return None
    return None


def _shown_folder(folder: Path, home: Path):
    """A folder as the message may show it: from ~ when it is in the home
    folder, so no user name is shown; None anywhere else."""
    try:
        return "~/" + Path(folder).relative_to(home).as_posix()
    except ValueError:
        return None


def places(root: Path = REPO, environ=None) -> tuple:
    """Where to fix settings.json and where the logs are, as the message
    says them: in Kettle's folder for a development copy, in the home
    folder's standard places for an installed copy (the installer work)."""
    from backend import app_paths
    environ = os.environ if environ is None else environ
    paths = app_paths.for_app(root, environ)
    if not paths.installed:
        return "in Kettle's folder", "in the logs folder in Kettle's folder"
    home = Path(environ.get("HOME") or Path.home())
    config = _shown_folder(paths.settings_file.parent, home)
    logs = _shown_folder(paths.logs_dir, home)
    return (f"in {config}" if config else "in Kettle Video's settings folder (see the README)",
            f"in {logs}" if logs else "in Kettle Video's logs folder (see the README)")


def lines(reason: str, log_file: str, root: Path = REPO, environ=None) -> list:
    """The message, one sentence or two per line: what went wrong, what to
    do, where the log is. Never a full path: only the log's own name, and
    for an installed copy its folder from ~."""
    settings_place, logs_place = places(root, environ)
    if reason == NO_FIREFOX:
        what = ["Kettle shows its screens in Firefox, and Firefox isn't installed.",
                "Install Firefox from Discover in Desktop Mode, then start Kettle again."]
    elif reason == BACKEND_SILENT:
        what = ["Kettle took too long to get ready.",
                "Start Kettle again. If it keeps happening, restart the device."]
    else:
        problem = settings_problem(root, environ)
        if problem:
            what = ["Your settings have a mistake: " + problem,
                    SETTINGS_FIX.replace("in Kettle's folder", settings_place)]
        else:
            what = ["Kettle stopped while it was getting ready.", "Start Kettle again."]
    log_name = Path(log_file).name
    return [TITLE, *what,
            f"The details are in {log_name}, {logs_place}. "
            "Attach it if you report this on GitHub."]


def back_to_main_offer(reason: str, root: Path = REPO, environ=None):
    """The branch a development copy is on, when the page should offer Back
    to main (the "Try a branch" work): the app itself stopped or never got
    ready, settings.json has no mistake (main would have it too), and the
    copy isn't on main. None otherwise, and whenever anything unexpected
    happens: a branch that can't start may have broken these parts too."""
    if reason not in (BACKEND_STOPPED, BACKEND_SILENT):
        return None
    try:
        from backend import try_branch, update_check
        if not update_check.is_development(root) or settings_problem(root, environ):
            return None
        branch = try_branch.current_branch(root, update_check._git)
        if branch == try_branch.MAIN:
            return None
        return branch or try_branch.head(root, update_check._git)[:7]
    except Exception:
        return None


def back_to_main(root: Path = REPO, environ=None, git=None, now=None) -> dict:
    """Back to main from this page: {"ok", "text"}, the plain words to show.
    Never online; nothing changed unless ok."""
    failed = "Couldn't go back to main. Nothing was changed."
    try:
        from datetime import datetime
        from backend import app_paths, try_branch, update_check
        from backend.settings import load_settings
        failed = try_branch.BACK_AT_START_FAILED
        environ = os.environ if environ is None else environ
        if not update_check.is_development(root):
            return {"ok": False, "text": failed}
        paths = app_paths.for_app(root, environ)
        settings = load_settings(root, paths)
        text = try_branch.back_to_main_at_start(
            root, git or update_check._git, Path(settings.get("data_dir") or paths.logs_dir),
            paths.settings_file, [settings.get("movies_path"), settings.get("tv_path")], environ,
            (now or datetime.now)())
        return {"ok": True, "text": text}
    except Exception as exc:
        said = str(exc) if type(exc).__name__ == "Refused" else failed
        return {"ok": False, "text": said}


def make_handler(reason: str, log_file: str, port: int, root: Path, stop, environ=None):
    expected_host = f"127.0.0.1:{port}"
    message = {"lines": lines(reason, log_file, root, environ),
               "back_to_main": back_to_main_offer(reason, root, environ)}
    switched = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, format, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

        def _send(self, status, body: bytes, kind: str):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status, data):
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def do_GET(self):
            if self.headers.get("Host") != expected_host:
                return self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            path = PAGE if self.path == "/" else self.path
            if path == "/api/startup-error":
                return self._send_json(HTTPStatus.OK, message)
            if path not in FILES:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            name, kind = FILES[path]
            try:
                body = (root / name).read_bytes()
            except OSError:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            self._send(HTTPStatus.OK, body, kind)

        def do_POST(self):
            if self.headers.get("Host") != expected_host:
                return self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.path == "/api/close":
                print("start-up message closed", flush=True)
                self._send_json(HTTPStatus.OK, {"ok": True})
                return stop()
            if self.path == "/api/back-to-main":
                # Only where the page offered it, and once.
                if not message["back_to_main"] or not switched.acquire(blocking=False):
                    return self._send_json(HTTPStatus.CONFLICT, {"ok": False, "text": ""})
                answer = back_to_main(root, environ)
                print(f"start-up message: back to main from {message['back_to_main']}: "
                      f"{'done' if answer['ok'] else answer['text']}", flush=True)
                if answer["ok"]:
                    message["back_to_main"] = None
                else:
                    switched.release()
                return self._send_json(HTTPStatus.OK, answer)
            if self.path == "/api/shown":
                print("start-up message shown", flush=True)
                return self._send_json(HTTPStatus.OK, {"ok": True})
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def serve(reason: str, log_file: str, port: int, root: Path = REPO) -> None:
    httpd_ref = {}

    def stop():
        threading.Thread(target=httpd_ref["server"].shutdown, daemon=True).start()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(reason, log_file, port, root, stop))
    httpd_ref["server"] = httpd
    print(f"start-up message on http://127.0.0.1:{port}/ ({reason})", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def main(argv) -> int:
    if len(argv) >= 3 and argv[0] == "text" and argv[1] in REASONS:
        print("\n\n".join(lines(argv[1], argv[2])))
        return 0
    if len(argv) == 4 and argv[0] == "serve" and argv[1] in REASONS and argv[3].isdigit():
        serve(argv[1], argv[2], int(argv[3]))
        return 0
    print("usage: python3 -m backend.startup_error text REASON LOGFILE | serve REASON LOGFILE PORT",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
