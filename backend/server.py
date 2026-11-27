# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""HTTP entrypoint. The only module in backend/ that touches sockets/HTTP.

Run as: python3 -m backend.server
"""

import json
import os
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend import (
    app_paths, app_update, continue_watching, folder_dialog, folder_finder, launch_options, library_index, movie_fixture, mpv,
    onboarding, parsed_library, resume_positions, scanner, settings_screen, size_readout, update_check,
    vendor_path,
)
from backend.settings import SettingsError, load_settings, read_mpv_command, repo_root

DEFAULT_PORT = 8756
# Closing the app while a film plays (the server shutdown check): how long to wait for mpv
# to quit and for its stop to be saved before the server goes anyway.
PLAYBACK_CLOSE_WAIT = 2.0
SCAN_BUSY = "Rescan unavailable while playing"
# This server's own id (the Update and restart work): after Update and restart the page
# waits for a server with a different one, then reloads.
BOOT_ID = secrets.token_hex(8)
REMOVE_FAILED = "Couldn't remove the missing items. The saved library is unchanged."
# Parts of mpv's result that hold file locations: never sent to the page.
PRIVATE_RESULT_KEYS = ("log", "log_tail")
# What the page may report about its screen wake lock during a film (the
# screen wake lock fix); anything else is refused, so the log only ever gets these words.
WAKE_LOCK_STATES = ("held", "lost", "refused", "unsupported", "released")
# The design system's two stylesheets (the first design system step) and its behaviour script
# for the picker (the picker confirm work), vendored outside ui/: the only files under
# vendor/ the page may ask for, by these exact paths, with their types.
ENAMEL_URL = "/vendor/enamel/"
ENAMEL_FILES = {
    "tokens/enamel.css": "text/css; charset=utf-8",
    "components/enamel-components.css": "text/css; charset=utf-8",
    "components/enamel-components.js": "text/javascript; charset=utf-8",
}


def _json_bytes(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


def _log(line: str) -> None:
    print(line, flush=True)


def _launch_start() -> float:
    """When launch.sh started (it passes the time), else now."""
    try:
        return float(os.environ["KETTLE_VIDEO_LAUNCH_START"])
    except (KeyError, ValueError):
        return time.time()


def make_handler(ui_dir: Path, logs_dir: Path, settings: dict, httpd_ref: dict, port: int, options=None,
                 settings_file=None, mpv_setting_file=None, installed=False, app_id=None):
    """options: this launch's launch_options.LaunchOptions (the fresh start mode).
    Without it (most tests), normal use: no fresh start, mpv looked for.
    settings_file: the settings.json that onboarding saves the folders to
    (the folder choice screens); in fresh start, the session's own (the fresh start onboarding work). Without it
    (most tests) nothing is ever written.
    mpv_setting_file: the real settings.json, even in fresh start, which Look
    again reads mpv_command from (the mpv missing screen); only ever read. Without it, Look
    again uses the setting from launch.
    installed, app_id: an installed copy keeps mpv's resume positions in a
    folder of its own (the each-copy-its-own-data work, backend/resume_positions.py).
    Without them (most tests, a development copy), mpv's own folder."""
    expected_host = f"127.0.0.1:{port}"
    fresh_start = options is not None and options.fresh_start
    # Fresh start: mpv keeps its resume positions in the fresh folder.
    watch_later_dir = options.watch_later_dir if options is not None else None
    pretend_no_mpv = options is not None and options.pretend_no_mpv
    play_lock = threading.Lock()
    play_state = {"state": "idle", "last_result": None}
    # The film playing now, for closing the app (the server shutdown check): not sent to the page.
    playback = {"thread": None, "socket": None}
    closing = threading.Event()
    page_loaded = threading.Event()
    started_at = _launch_start()
    # The saved library (the saved library work): loaded now, never scanned at start. A
    # scan runs only when asked, one at a time, and swaps in when it's done.
    # Tests pass settings without data_dir; their logs folder is temporary.
    data_dir = Path(settings.get("data_dir") or logs_dir)
    index_path = data_dir / library_index.FILE_NAME
    # The installed copy's own resume positions (the each-copy-its-own-data work): an
    # update from the shared layout carries mpv's over; a brand-new install doesn't.
    own_resume = installed and bool(app_id) and not fresh_start
    if own_resume:
        try:
            resume_positions.note_first_launch(data_dir, index_path.exists())
        except OSError as exc:
            _log(f"resume positions: couldn't note this launch ({type(exc).__name__})")
    roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
    library_lock = threading.Lock()
    library = {"index": library_index.load(index_path, _log), "answer": None}
    scan_state = {"state": "idle", "files_done": 0, "files_total": 0, "last_result": None}
    # Developer only (the sizing spike): the page sends its sizes once, at start.
    size_readout_on = settings.get(size_readout.SETTING) is True
    size_readout_lock = threading.Lock()
    size_readout_done = {"done": False}
    # Check for updates (the never-online work): one at a time, only when asked.
    update_lock = threading.Lock()
    # Update and restart, Pull the latest version (the Update and restart work): only after a
    # check, a yes, and never while a film plays. The restart's message for
    # the page, read once (it came from the server before the restart).
    updater = app_update.Updater(
        ui_dir.parent, _log, restart=lambda root, note: request_restart(httpd_ref, root, note),
        is_playing=lambda: play_state["state"] == "playing")
    update_note = {"text": httpd_ref.pop("update_note", None)}
    update_note_lock = threading.Lock()
    # Onboarding (the folder finder): the last search for folders with videos. Its
    # full paths stay here; the page picks a folder by its id (the folder choice screens). Every
    # folder found this session is kept by its id, so a choice made before
    # Look again still counts.
    folder_search_lock = threading.Lock()
    folder_search = {"last": None, "paths": {}, "problems": {}}
    # Where Kettle writes its own files: never inside a media folder (the first onboarding review fixes).
    own_folders = [logs_dir, data_dir] + ([Path(settings_file).parent] if settings_file else [])

    def keep_found(suggestions, picked=False):
        """The folders found: each one's path by its id, and why it can't be
        chosen, if so. Call holding folder_search_lock."""
        for s in suggestions:
            s.problem = s.problem or onboarding.own_files_problem(s.path, own_folders, picked)
            folder_search["paths"][s.id] = s.path
            folder_search["problems"][s.id] = s.problem

    # "Browse somewhere else" (the Browse somewhere else work): the system's folder dialog open now.
    dialog_lock = threading.Lock()
    dialog = {"process": None}

    def close_dialog():
        with dialog_lock:
            if dialog["process"] is not None:
                folder_dialog.close(dialog["process"])

    def detect_mpv():
        """mpv's status, or "not installed" when the launch option says to
        pretend (the fresh start mode): the same answer as a device without mpv."""
        if pretend_no_mpv:
            return {"available": False, "install_hint": mpv.INSTALL_HINT}
        return mpv.detect(settings["mpv_command"])

    def read_mpv_setting_again():
        """Look again (the mpv missing screen): mpv_command as the file says now, as the
        screen may have just asked for it to be fixed. The sentence to show
        if the file can't be read at the moment, else None."""
        if pretend_no_mpv or mpv_setting_file is None:
            return None
        try:
            settings["mpv_command"] = read_mpv_command(mpv_setting_file)
        except SettingsError as exc:
            return str(exc)
        return None

    # Continue watching (the Continue watching work): a resume feature, so off with resume
    # (true unless settings.json says otherwise, as load_settings fills in).
    resume_on = settings.get("resume", True)
    watching_lock = threading.Lock()
    # A folder left empty (the folder choice screens) is not set: it is never a media folder.
    watching = continue_watching.ContinueWatching(data_dir, [r for r in roots.values() if r], _log)

    def prune_watching(index):
        """Items gone from the saved library leave the carousel too."""
        try:
            with watching_lock:
                watching.prune(index, roots)
        except Exception as exc:
            _log(f"continue watching: couldn't update the saved list ({type(exc).__name__})")

    prune_watching(library["index"])
    with watching_lock:
        watching.clean_pictures()

    def save_stop(target, rel, capture_dir):
        """After mpv: keep what the quit script saved. Returns the stamp
        to shrink the picture with, or None. Runs before the page is told
        mpv has closed, so the carousel it fetches is already up to date."""
        started = time.perf_counter()
        try:
            record = json.loads((capture_dir / "record.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None  # mpv ended without the script (a crash, a kill)
        except (OSError, ValueError):
            _log("continue watching: mpv's record can't be read")
            return None
        if not isinstance(record, dict):
            return None
        frame = capture_dir / "frame.jpg"
        frame = frame if record.get("frame_saved") is True and frame.is_file() else None
        try:
            with watching_lock:
                stamp = watching.record_stop(target, rel, record, frame, time.time())
        except Exception as exc:
            _log(f"continue watching: couldn't save the stop ({type(exc).__name__})")
            return None
        _log(f"continue watching: stop saved in {(time.perf_counter() - started) * 1000:.0f} ms")
        return stamp

    def shrink_picture(command, key, stamp, capture_dir):
        """In the background, once the viewer is back in the list: the small
        picture replaces the full-size frame shown meanwhile."""
        started = time.perf_counter()
        try:
            small = mpv.shrink_frame(command, capture_dir / "frame.jpg", capture_dir)
            with watching_lock:
                watching.replace_picture(key, stamp, small)
            if small is None:
                _log("continue watching: the small picture couldn't be made; the full-size frame is kept")
            else:
                _log(f"continue watching: small picture made in {time.perf_counter() - started:.1f} s")
        except Exception as exc:
            _log(f"continue watching: the small picture failed ({type(exc).__name__})")
        finally:
            shutil.rmtree(capture_dir, ignore_errors=True)

    def finish_playback():
        """Before the server stops: a playing film is asked to quit as B
        does, so mpv saves its resume position and the frame, and the stop
        is kept before the server goes (the server shutdown check, docs/decisions.md). A
        folder dialog still open closes too, so nothing is left running
        (the Browse somewhere else work)."""
        closing.set()
        close_dialog()
        with play_lock:
            thread, control = playback["thread"], playback["socket"]
        if thread is None or not thread.is_alive():
            return
        if control is None or not mpv.ask_to_quit(control):
            _log("closing while a film plays: mpv couldn't be asked to quit")
        thread.join(PLAYBACK_CLOSE_WAIT)
        if thread.is_alive():
            _log(f"closing while a film plays: mpv didn't close within {PLAYBACK_CLOSE_WAIT:g} s")
        else:
            _log("closing while a film plays: mpv closed and the stop was kept")

    httpd_ref["finish_playback"] = finish_playback

    def start_scan():
        """Starts a scan unless one is running or a film plays (the quick rescan and Remove work).
        The answer the page gets, and the HTTP status for it."""
        with play_lock:
            playing = play_state["state"] == "playing"
        if playing:
            return HTTPStatus.CONFLICT, {"started": False, "busy": True, "error": SCAN_BUSY}
        with library_lock:
            started = scan_state["state"] != "scanning"
            if started:
                scan_state.update(state="scanning", files_done=0, files_total=0)
                threading.Thread(target=run_scan, daemon=True).start()
            status = dict(scan_state)
        return HTTPStatus.OK, {"started": started, **status}

    def run_scan():
        def progress(done, total):
            with library_lock:
                scan_state["files_done"] = min(done, total)
                scan_state["files_total"] = total

        with library_lock:
            previous = library["index"]
        try:
            index = library_index.full_scan(roots, previous, progress)
            library_index.save(index_path, index)
        except Exception as exc:
            # Only the kind of error: its text could hold a full path.
            _log(f"library scan failed ({type(exc).__name__}); the saved library is unchanged")
            result = {"ok": False, "error": "Couldn't scan the library. The saved library is unchanged."}
            index = None
        else:
            _log(library_index.summary(index))
            result = {"ok": True, "message": library_index.scan_message(previous, index)}
        with library_lock:
            if index is not None:
                library["index"] = index
                library["answer"] = None
            scan_state["state"] = "idle"
            scan_state["last_result"] = result

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ui_dir), **kwargs)

        def end_headers(self):
            # Make Firefox check for newer UI files on every load; without it
            # the kiosk profile kept showing old CSS (the Brand v0.1 work).
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, format, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

        def _send_json(self, status: int, data: dict):
            body = _json_bytes(data)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _host_ok(self) -> bool:
            return self.headers.get("Host") == expected_host

        def do_GET(self):
            if not self._host_ok():
                return self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.path == "/api/mpv-status":
                return self._handle_mpv_status()
            if self.path == "/api/library":
                return self._handle_library()
            if self.path == "/api/library/parsed":
                return self._handle_parsed_library()
            if urlsplit(self.path).path == "/api/library/parsed":
                return self._handle_parsed_library(self._fixture_count())
            if self.path == "/api/library/scan/status":
                return self._handle_scan_status()
            if self.path == "/api/status":
                return self._handle_status()
            if self.path == "/api/dev":
                # Fresh start only: the page shows its marker (the fresh start mode).
                fresh = {"fresh_start": True} if fresh_start else {}
                # Size readout on only (the sizing spike): the page sends its sizes.
                readout = {"size_readout": True} if size_readout_on else {}
                return self._send_json(HTTPStatus.OK, {**fresh, **readout})
            if self.path == "/api/continue":
                return self._handle_continue()
            if self.path == "/api/updates/status":
                return self._send_json(HTTPStatus.OK, {**updater.status(), "boot": BOOT_ID})
            if self.path == "/api/onboarding/folders":
                return self._handle_find_folders()
            if self.path == "/api/onboarding":
                return self._send_json(HTTPStatus.OK, {"needed": onboarding.needed(settings)})
            if self.path == "/api/onboarding/result":
                return self._handle_scan_result()
            if self.path == "/api/settings":
                return self._handle_settings()
            if urlsplit(self.path).path == "/api/settings/licence":
                return self._handle_licence()
            if urlsplit(self.path).path.startswith("/api/continue/picture/"):
                return self._handle_picture()
            if urlsplit(self.path).path.startswith(ENAMEL_URL):
                return self._handle_enamel()
            return super().do_GET()

        def do_POST(self):
            if not self._host_ok():
                return self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                return self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.path == "/api/play":
                return self._handle_play()
            if self.path == "/api/mpv-status/look-again":
                return self._handle_mpv_look_again()
            if self.path == "/api/library/scan":
                return self._handle_scan()
            if self.path == "/api/library/remove-missing":
                return self._handle_remove_missing()
            if self.path == "/api/continue/remove":
                return self._handle_continue_remove()
            if self.path == "/api/shutdown":
                return self._handle_shutdown()
            if self.path == "/api/wake-lock":
                return self._handle_wake_lock()
            if self.path == "/api/onboarding/choose":
                return self._handle_choose_folders()
            if self.path == "/api/onboarding/browse":
                return self._handle_browse()
            if self.path == "/api/updates/check":
                return self._handle_update_check()
            if self.path == "/api/updates/install":
                return self._handle_update_install()
            if self.path == "/api/updates/pull":
                return self._handle_update_start(updater.start_pull)
            if self.path == "/api/updates/cancel":
                return self._send_json(HTTPStatus.OK, {"ok": updater.cancel()})
            if self.path == "/api/updates/note":
                with update_note_lock:
                    text, update_note["text"] = update_note["text"], None
                return self._send_json(HTTPStatus.OK, {"note": text})
            if self.path == "/api/settings/folder":
                return self._handle_settings_folder()
            if self.path == "/api/onboarding/browse/close":
                close_dialog()
                return self._send_json(HTTPStatus.OK, {"ok": True})
            if self.path == "/api/size-readout" and size_readout_on:
                return self._handle_size_readout()
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _handle_mpv_status(self):
            # The page asks for this first, so the first call marks the page
            # as loaded. launch.sh looks for this line (the start-up fix).
            if not page_loaded.is_set():
                page_loaded.set()
                print(f"page loaded {time.time() - started_at:.1f} s after launch", flush=True)
            # The command found (a full path, such as /usr/bin/mpv) stays in
            # the backend: no answer holds an absolute path (the Home actions work).
            found = detect_mpv()
            self._send_json(HTTPStatus.OK, {k: v for k, v in found.items() if k != "command"})

        def _handle_mpv_look_again(self):
            # The same answer as the status above, after reading mpv_command
            # again; the check itself looks afresh every time (the mpv missing screen).
            problem = read_mpv_setting_again()
            if problem:
                return self._send_json(HTTPStatus.OK, {"available": False, "problem": problem, "hint": mpv.SETTING_HINT})
            return self._handle_mpv_status()

        def _handle_library(self):
            def source(label, root):
                # A folder left empty (the folder choice screens) is not set, never the
                # server's own folder.
                if not root:
                    return {"label": label, "path": "", "status": "not_found", "reason": "No folder chosen", "groups": []}
                return scanner.scan_source(label, root)

            self._send_json(
                HTTPStatus.OK,
                {
                    "movies": source("Movies", settings["movies_path"]),
                    "tv": source("TV Shows", settings["tv_path"]),
                },
            )

        def _fixture_count(self):
            """Developer only (the Movies list work): ?fixture=2000 asks for 2,000
            invented films instead of the saved ones; anything else, none."""
            value = parse_qs(urlsplit(self.path).query).get("fixture", [""])[0]
            if value.isdigit() and 0 < int(value) <= movie_fixture.MAX_COUNT:
                return int(value)
            return None

        def _handle_parsed_library(self, fixture=None):
            with library_lock:
                if library["answer"] is None:
                    try:
                        library["answer"] = library_index.render(library["index"], roots)
                    except Exception as exc:
                        # The page gets one plain sentence and falls back to
                        # the plain list; only the kind of error is logged.
                        _log(f"saved library can't be shown ({type(exc).__name__})")
                        return self._send_json(
                            HTTPStatus.OK, {"ok": False, "error": parsed_library.ERROR_SENTENCE}
                        )
                answer = library["answer"]
            available = library_index.availability(roots)
            # folder_set is false for a kind skipped in onboarding (the folder choice screens).
            answer = {**answer, **{s: {**answer[s], "available": available[s], "folder_set": bool(roots[s])}
                                   for s in roots}}
            if fixture:
                answer = movie_fixture.with_invented_movies(answer, fixture)
            self._send_json(HTTPStatus.OK, answer)

        def _handle_scan(self):
            # No scans while mpv plays: the Nova needs the processor for
            # smooth video (the quick rescan and Remove work).
            self._send_json(*start_scan())

        def _handle_remove_missing(self):
            # The only way anything leaves the saved library (the quick rescan and Remove work).
            with library_lock:
                if scan_state["state"] == "scanning":
                    return self._send_json(HTTPStatus.CONFLICT, {"ok": False, "busy": True, "error": REMOVE_FAILED})
                if library["index"] is None:
                    return self._send_json(HTTPStatus.OK, {"ok": True, "removed": 0})
                try:
                    index, removed = library_index.remove_missing(library["index"])
                    library_index.save(index_path, index)
                except Exception as exc:
                    _log(f"removing missing items failed ({type(exc).__name__}); the saved library is unchanged")
                    return self._send_json(HTTPStatus.OK, {"ok": False, "error": REMOVE_FAILED})
                library["index"] = index
                library["answer"] = None
            _log(f"library: removed {removed} missing item{'' if removed == 1 else 's'}")
            prune_watching(index)
            self._send_json(HTTPStatus.OK, {"ok": True, "removed": removed})

        def _handle_continue(self):
            # Ids, words and numbers only, never a file location (the Continue watching work).
            if not resume_on:
                return self._send_json(HTTPStatus.OK, {"items": []})
            with library_lock:
                index = library["index"]
            available = library_index.availability(roots)
            with watching_lock:
                items = watching.items(index, roots, available)
            self._send_json(HTTPStatus.OK, {"items": items})

        def _handle_picture(self):
            key = urlsplit(self.path).path.rsplit("/", 1)[-1]
            with watching_lock:
                picture = watching.picture_file(key) if resume_on else None
            try:
                body = picture.read_bytes() if picture is not None else None
            except OSError:
                body = None
            if body is None:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_enamel(self):
            name = urlsplit(self.path).path.removeprefix(ENAMEL_URL)
            if name not in ENAMEL_FILES:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            try:
                body = (ui_dir.parent / "vendor" / "enamel" / name).read_bytes()
            except OSError:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ENAMEL_FILES[name])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_continue_remove(self):
            # X on a tile: no confirm; the resume position is kept (the Continue watching work).
            try:
                key = self._read_json_body().get("id")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            try:
                with watching_lock:
                    removed = watching.remove(key)
            except Exception as exc:
                _log(f"continue watching: couldn't remove a tile ({type(exc).__name__})")
                return self._send_json(HTTPStatus.OK, {"ok": False})
            self._send_json(HTTPStatus.OK, {"ok": removed})

        def _handle_scan_status(self):
            with library_lock:
                self._send_json(HTTPStatus.OK, dict(scan_state))

        def _handle_status(self):
            with play_lock:
                state = dict(play_state)
            # The mpv log's location and its last lines (which name the
            # file played) stay in the backend: no answer holds an absolute
            # path (the fresh start mode). The page shows only the error and the hint.
            if isinstance(state["last_result"], dict):
                state["last_result"] = {
                    k: v for k, v in state["last_result"].items() if k not in PRIVATE_RESULT_KEYS
                }
            self._send_json(HTTPStatus.OK, state)

        def _handle_find_folders(self):
            # One search at a time; each one only reads. The log gets counts
            # and kinds of place only, never a path or a name.
            with folder_search_lock:
                found = folder_finder.search()
                folder_search["last"] = found
                keep_found(found.suggestions)
            _log(found.log_line())
            # browse: a folder dialog is there to open (the Browse somewhere else work).
            self._send_json(HTTPStatus.OK, {**found.answer(), "browse": folder_dialog.find() is not None})

        def _handle_scan_result(self):
            # The result screen (the first scan screen): counts, and each folder's place
            # and own name, never a full path.
            with library_lock:
                index = library["index"]
                current = dict(roots)
            with folder_search_lock:
                last = folder_search["last"]
            self._send_json(HTTPStatus.OK, onboarding.result(index, current, last.places if last else None))

        def _read_choice(self, kinds):
            """The request's folder ids, each a string or null. None once it
            has answered that the request isn't one."""
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
                return None
            if not isinstance(body, dict) or not all(
                body.get(kind) is None or isinstance(body.get(kind), str) for kind in kinds
            ):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid choice"})
                return None
            return body

        def _handle_browse(self):
            # "Browse somewhere else" (the Browse somewhere else work): {"movies": id or null}, the
            # folder chosen on screen 1 if this is screen 2. Runs on this
            # request's own thread, with no time limit, so the server keeps
            # answering. The log gets the dialog's name and what happened,
            # never a path; the page gets ids, places and names.
            # From Settings (the Settings screen work): {"settings": "movies" | "tv"}, and the
            # folder is checked against the other kind's folder as it is.
            body = self._read_choice(["movies"])
            if body is None:
                return
            kind = body.get("settings")
            if kind is not None and kind not in settings_screen.KINDS:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid choice"})
            name = folder_dialog.find()
            if name is None:
                _log("onboarding: no folder dialog found")
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": folder_dialog.OPEN_FAILED})
            with dialog_lock:
                if closing.is_set() or dialog["process"] is not None:
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": folder_dialog.ALREADY_OPEN})
                try:
                    process = folder_dialog.start(name)
                except OSError as exc:
                    _log(f"onboarding: folder dialog ({name}) couldn't start ({type(exc).__name__})")
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": folder_dialog.OPEN_FAILED})
                dialog["process"] = process
            try:
                result, path = folder_dialog.wait(process)
            finally:
                with dialog_lock:
                    dialog["process"] = None
            _log(f"onboarding: folder dialog ({name}): {result}")
            if result == folder_dialog.CANCELLED:
                return self._send_json(HTTPStatus.OK, {"ok": True, "picked": False})
            if result == folder_dialog.NOT_A_FOLDER:
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": folder_dialog.NOT_A_FOLDER_MESSAGE})
            if result != folder_dialog.PICKED:
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": folder_dialog.OPEN_FAILED})
            with folder_search_lock:
                last = folder_search["last"]
            found = folder_finder.picked(path, last)
            with folder_search_lock:
                keep_found([found], picked=True)
                movies = folder_search["paths"].get(body.get("movies"))
            # The same checks and messages as a listed folder.
            if kind is None:
                message = found.problem or onboarding.problem(movies, found.path)
            else:
                with library_lock:
                    other = roots["tv" if kind == "movies" else "movies"]
                message = found.problem or settings_screen.problem(kind, found.path, other)
            self._send_json(HTTPStatus.OK, {
                "ok": True, "picked": True, "folder": folder_finder.folder_answer(found),
                "place_kind": found.place.kind, "message": message,
            })

        def _handle_choose_folders(self):
            # The TV Shows screen's choice (the folder choice screens): {"movies": id or
            # null, "tv": id or null}, ids from the folder search. Refused
            # with the sentence the page shows in the row; on a good pair
            # both folders go into settings.json and the app uses them at
            # once. Only "chosen" or "skipped" is logged, never a folder.
            body = self._read_choice(onboarding.KEYS)
            if body is None:
                return
            with folder_search_lock:
                paths = {kind: folder_search["paths"].get(body[kind]) if body.get(kind) else None
                         for kind in onboarding.KEYS}
                refused = [folder_search["problems"].get(body.get(kind)) for kind in onboarding.KEYS]
            if any(body.get(kind) and paths[kind] is None for kind in onboarding.KEYS):
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.GONE})
            message = next(filter(None, refused), None) or onboarding.problem(paths["movies"], paths["tv"])
            if message:
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": message})
            if settings_file is None:
                _log("onboarding: no settings file to save to")
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.SAVE_FAILED})
            try:
                onboarding.save_folders(settings_file, paths["movies"], paths["tv"])
            except onboarding.SaveError as exc:
                _log(f"onboarding: {exc}")
                return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.SAVE_FAILED})
            with library_lock:
                for kind, key in onboarding.KEYS.items():
                    settings[key] = paths[kind] or ""
                    roots[kind] = paths[kind] or ""
                library["answer"] = None
            with watching_lock:
                watching.set_media_roots([r for r in roots.values() if r])
            _log(onboarding.log_line(paths["movies"], paths["tv"]))
            self._send_json(HTTPStatus.OK, {"ok": True})

        def _handle_settings(self):
            # The Settings screen (the Settings screen work): each folder as its place path,
            # the version and the credits; never a full path.
            with folder_search_lock:
                last = folder_search["last"]
            with library_lock:
                current = dict(settings)
            self._send_json(HTTPStatus.OK, {
                "folders": settings_screen.folders(current, last.places if last else None),
                **settings_screen.about(ui_dir.parent),
                # Read from the device only: showing it never goes online (the never-online work).
                "updates": {
                    "last_checked": update_check.last_checked_text(
                        update_check.load_last_checked(data_dir), date.today()),
                    "development": update_check.is_development(ui_dir.parent),
                },
            })

        def _handle_update_check(self):
            # Check for updates (the never-online work): the one request, only when the
            # viewer chooses the row. One at a time; the rest of the app keeps
            # answering while it runs (each request has its own thread).
            if not update_lock.acquire(blocking=False):
                return self._send_json(HTTPStatus.CONFLICT, {"error": "already checking"})
            try:
                result = update_check.check(ui_dir.parent, data_dir,
                                            settings_screen.version(ui_dir.parent), date.today())
            finally:
                update_lock.release()
            _log(result.pop("log"))
            # What Update and restart needs stays here (the Update and restart work); the page is
            # told only whether it may offer it.
            result = updater.offered(result, result.pop("release", None))
            self._send_json(HTTPStatus.OK, result)

        def _handle_update_install(self):
            try:
                version = self._read_json_body().get("version")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            if not isinstance(version, str):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing version"})
            self._handle_update_start(lambda: updater.start_update(version))

        def _handle_update_start(self, start):
            # Under the play lock, so a film can't start in between (the Update and restart work).
            with play_lock:
                refused = start()
            if refused:
                return self._send_json(HTTPStatus.CONFLICT, {"ok": False, "text": refused})
            self._send_json(HTTPStatus.OK, {"ok": True, "boot": BOOT_ID, **updater.status()})

        def _handle_licence(self):
            # A credit's licence text, asked for by the credit's id.
            credit = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            found = settings_screen.licence_text(ui_dir.parent, credit)
            if found is None:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            self._send_json(HTTPStatus.OK, {"ok": True, **found})

        def _handle_settings_folder(self):
            # Settings (the Settings screen work): {"kind": "movies" | "tv", "id": a folder
            # id from the search, or null for "Stop using ..."}. The folder
            # already set changes nothing. A good choice is saved to
            # settings.json (the session's own in fresh start), the old
            # folder's items turn Missing, and one rescan starts. Only the
            # kind and "changed" or "stopped" is logged, never a folder.
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            if not isinstance(body, dict) or body.get("kind") not in settings_screen.KINDS \
                    or not (body.get("id") is None or isinstance(body.get("id"), str)):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid choice"})
            kind, chosen = body["kind"], body.get("id")
            path = None
            if chosen:
                with folder_search_lock:
                    path = folder_search["paths"].get(chosen)
                    refused = folder_search["problems"].get(chosen)
                if path is None:
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.GONE})
                if refused:
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": refused})
            other = "tv" if kind == "movies" else "movies"
            with library_lock:
                if settings_screen.same_folder(path, roots[kind]):
                    return self._send_json(HTTPStatus.OK, {"ok": True, "changed": False})
                message = settings_screen.problem(kind, path, roots[other])
                if message is None and scan_state["state"] == "scanning":
                    message = settings_screen.SCANNING
                if message:
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": message})
                if settings_file is None:
                    _log("settings: no settings file to save to")
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.SAVE_FAILED})
                try:
                    onboarding.save_folder(settings_file, kind, path)
                except onboarding.SaveError as exc:
                    _log(f"settings: {exc}")
                    return self._send_json(HTTPStatus.OK, {"ok": False, "message": onboarding.SAVE_FAILED})
                settings[onboarding.KEYS[kind]] = path or ""
                roots[kind] = path or ""
                moved = library_index.move_folder(library["index"], kind, path) if path else library["index"]
                if moved is not library["index"]:
                    library["index"] = moved
                    try:
                        library_index.save(index_path, moved)
                    except Exception as exc:
                        _log(f"settings: the saved library couldn't be updated ({type(exc).__name__}); the rescan saves it")
                library["answer"] = None
            with watching_lock:
                watching.set_media_roots([r for r in roots.values() if r])
            _log(settings_screen.log_line(kind, path))
            scan = start_scan()[1] if path else None
            self._send_json(HTTPStatus.OK, {"ok": True, "changed": True, "scan": scan})

        def _resolve_source_root(self, source: str):
            # A folder left empty (the folder choice screens) is not set: Path("") would be
            # the server's own folder.
            if source in onboarding.KEYS and settings[onboarding.KEYS[source]]:
                return Path(settings[onboarding.KEYS[source]])
            return None

        def _handle_play(self):
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})

            source = body.get("source")
            rel_path = body.get("path")
            if "continue" in body:
                # A Continue watching tile asks by its ID (the Continue watching work).
                with watching_lock:
                    target_file = watching.play_target(body["continue"]) if resume_on else None
                if target_file is None:
                    return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "file not found"})
                source, rel_path = target_file
            root = self._resolve_source_root(source)
            if root is None:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unknown source"})
            if source == "movies" and body.get("id"):
                # The Movies list asks by the film's ID (the Movies list work).
                with library_lock:
                    rel_path = library_index.movie_play_path(library["index"], roots["movies"], body["id"])
                if rel_path is None:
                    return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "file not found"})
            if not rel_path:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing path"})
            if parsed_library.folder_problem(str(root)):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Folder not available"})

            root_resolved = root.resolve()
            candidate = (root / rel_path).resolve()
            if not candidate.is_relative_to(root_resolved):
                return self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "path escapes configured folder"}
                )
            if not candidate.is_file():
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "file not found"})

            status = detect_mpv()
            if not status["available"]:
                # Missing mpv, or an mpv_command that can't work (the settings mistakes work).
                return self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "error": status.get("problem", "mpv is not available"),
                        "hint": status.get("hint", status.get("install_hint")),
                    },
                )

            with play_lock:
                if play_state["state"] == "playing":
                    return self._send_json(
                        HTTPStatus.CONFLICT, {"error": "already playing"}
                    )
                # No film starts while an update runs (the Update and restart work).
                if updater.busy():
                    return self._send_json(HTTPStatus.CONFLICT, {"error": "updating"})
                play_state["state"] = "playing"
                play_state["last_result"] = None

            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            log_path = logs_dir / f"mpv-{timestamp}.log"
            command = status["command"]
            mpv_args = settings["mpv_args"]
            resume = settings["resume"]
            keep_awake = settings["keep_awake"]
            resume_dir = resume_positions.folder_for_play(
                own_resume, watch_later_dir, data_dir, app_id, command, mpv_args, resume, _log)
            # Continue watching (the Continue watching work): only files of the saved library,
            # and only with resume on. mpv writes into a fresh folder in /tmp.
            target, capture_dir = None, None
            with library_lock:
                # Kettle's title for D-pad Up in mpv (the playback controls work).
                title = continue_watching.play_title(library["index"], roots, source, rel_path)
                if resume:
                    target = continue_watching.locate(library["index"], roots, source, rel_path)
            if target is not None:
                try:
                    capture_dir = Path(tempfile.mkdtemp(prefix="kettle-quit-", dir=mpv.SHARED_TMP))
                except OSError as exc:
                    _log(f"continue watching: no folder for mpv to save in ({type(exc).__name__})")
            # mpv's control socket, so closing the app can ask it to quit
            # (the server shutdown check). Under /tmp for the Flatpak mpv, like capture_dir.
            try:
                control_dir = Path(tempfile.mkdtemp(prefix="kettle-mpv-", dir=mpv.SHARED_TMP))
            except OSError as exc:
                _log(f"no folder for mpv's control socket ({type(exc).__name__})")
                control_dir = None
            control = control_dir / "mpv.sock" if control_dir is not None else None

            # Whatever happens to mpv, the state always goes back to idle, so
            # the page never stays on "Playing..." (the stuck Playing fix).
            def run_playback():
                try:
                    result = mpv.play(
                        command, candidate, log_path, mpv_args, resume, keep_awake, capture_dir, control,
                        title, resume_dir,
                    )
                except Exception as exc:
                    print(f"playback failed: {type(exc).__name__}", file=sys.stderr)
                    result = {
                        "ok": False,
                        "error": mpv.START_FAILED,
                        "hint": mpv.START_FAILED_HINT,
                    }
                if control_dir is not None:
                    shutil.rmtree(control_dir, ignore_errors=True)
                stamp = save_stop(target, rel_path, capture_dir) if capture_dir is not None else None
                with play_lock:
                    play_state["state"] = "idle"
                    play_state["last_result"] = result
                # Closing: no time to shrink; the full-size frame stays the picture.
                if stamp is not None and not closing.is_set():
                    threading.Thread(
                        target=shrink_picture, args=(command, target["key"], stamp, capture_dir), daemon=True
                    ).start()
                elif capture_dir is not None:
                    shutil.rmtree(capture_dir, ignore_errors=True)

            thread = threading.Thread(target=run_playback, daemon=True)
            with play_lock:
                playback["thread"], playback["socket"] = thread, control
            thread.start()
            # The page keeps the screen on for the film only when keep_awake
            # is on (the screen wake lock fix).
            self._send_json(HTTPStatus.OK, {"started": True, "keep_awake": keep_awake})

        def _handle_wake_lock(self):
            # One line in the launch log each time the page's screen wake
            # lock changes (the screen wake lock fix), to see on a device whether Firefox
            # granted it. Fixed words only, never anything the page made up.
            try:
                state = self._read_json_body().get("state")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            if state not in WAKE_LOCK_STATES:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unknown state"})
            _log(f"screen wake lock: {state}")
            self._send_json(HTTPStatus.OK, {"ok": True})

        def _handle_size_readout(self):
            # One line per launch (the sizing spike), written only from checked
            # numbers. Only reached with the setting on; otherwise not found.
            # A refusal is logged too, naming the field, never its value, so
            # an on setting with no readout line is never a silent failure.
            try:
                text = size_readout.line(self._read_json_body())
            except (json.JSONDecodeError, UnicodeDecodeError):
                _log("size readout refused: the page's answer wasn't readable")
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid readout"})
            except ValueError as exc:
                _log(f"size readout refused: {exc}")
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid readout"})
            with size_readout_lock:
                first = not size_readout_done["done"]
                size_readout_done["done"] = True
            if not first:
                return self._send_json(HTTPStatus.OK, {"ok": True, "logged": False})
            _log(text)
            self._send_json(HTTPStatus.OK, {"ok": True, "logged": True})

        def _handle_shutdown(self):
            httpd_ref["stopping"] = True
            self._send_json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=close_server, args=(httpd_ref,), daemon=True).start()

    return Handler


def close_server(httpd_ref: dict) -> None:
    """Stop the server, after a playing film has closed (the server shutdown check)."""
    httpd_ref["finish_playback"]()
    httpd_ref["server"].shutdown()


def request_restart(httpd_ref: dict, root: Path, note: str) -> None:
    """Update and restart (the Update and restart work): stop this server as for Quit; main()
    then restarts it in place from root, unless the app is being closed."""
    httpd_ref["restart"] = (Path(root), note)
    threading.Thread(target=close_server, args=(httpd_ref,), daemon=True).start()


def serve(root: Path, environ, port: int, httpd_ref: dict,
          fresh_parent: Path = launch_options.FRESH_PARENT) -> None:
    """Run the app's server from the app folder root until it is asked to
    stop. The data folder is chosen here, once (the fresh start mode); a fresh-start
    folder is deleted when the server stops, however it was asked to."""
    ui_dir = root / "ui"
    # A development copy keeps settings.json, data/ and logs/ in its own
    # folder; an installed copy in the home folder (the installer work).
    paths = app_paths.for_app(root, environ)
    logs_dir = paths.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    if paths.installed:
        # Onboarding creates settings.json here on first launch.
        paths.settings_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        settings = load_settings(root, paths)
    except SettingsError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        sys.exit(1)

    options = launch_options.choose(settings, environ, fresh_parent)
    # Every part of the app finds its data through this one setting, and
    # onboarding saves only to this one file.
    real_settings_file = paths.settings_file
    settings, settings_file = launch_options.for_session(settings, options, real_settings_file)
    if options.fresh_start:
        _log("fresh start: a new, empty data folder for this session, deleted when the app quits")
        _log("fresh start: both folders count as not set; those chosen last this session, settings.json isn't written")
    if options.pretend_no_mpv:
        _log("pretending mpv is not installed (launch option)")
    try:
        handler_cls = make_handler(ui_dir, logs_dir, settings, httpd_ref, port, options, settings_file,
                                   real_settings_file, paths.installed, app_paths.names(root)["APP_ID"])
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        httpd_ref["server"] = httpd
        print(f"Serving on http://127.0.0.1:{port}/", flush=True)
        httpd.serve_forever()
        httpd.server_close()
    finally:
        if options.fresh_start:
            gone = launch_options.remove_fresh(options.fresh_root, fresh_parent)
            _log("fresh start: folder deleted" if gone else "fresh start: the folder couldn't be deleted; the next fresh start cleans it up")


def main():
    # Before anything imports guessit, so the bundled copy is the one used.
    vendor_path.use_vendor()
    port = int(os.environ.get("KETTLE_VIDEO_PORT", DEFAULT_PORT))
    # After Update and restart (the Update and restart work): the message for the page, read
    # once, and never passed on to anything this server starts.
    httpd_ref = {"update_note": os.environ.pop(app_update.NOTE_ENV, None)}

    def _handle_signal(signum, frame):
        httpd_ref["stopping"] = True
        if "server" not in httpd_ref:
            # Still starting: stop here (a fresh-start folder made already
            # is deleted on the way out).
            raise SystemExit(0)
        threading.Thread(target=close_server, args=(httpd_ref,), daemon=True).start()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    serve(repo_root(), os.environ, port, httpd_ref)
    # Update and restart (the Update and restart work): the server has stopped cleanly (a
    # fresh-start folder deleted, the port closed); the same process now
    # becomes the new version's server, so launch.sh and Steam see the app
    # still running. Not when the app is being closed meanwhile.
    restart = httpd_ref.get("restart")
    if restart and not httpd_ref.get("stopping"):
        root, note = restart
        _log(f"restarting in place from the {'same' if root == repo_root() else 'new'} folder")
        try:
            app_update.restart_in_place(root, note)
        except OSError as exc:
            _log(f"couldn't restart in place ({type(exc).__name__}); the app closes")
            sys.exit(1)


if __name__ == "__main__":
    main()
