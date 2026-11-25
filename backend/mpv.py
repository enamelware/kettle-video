# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""mpv detection + launch. Pure logic, no HTTP awareness."""

import json
import shlex
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from backend import keep_awake as awake

FLATPAK_APP_ID = "io.mpv.Mpv"
INSTALL_HINT = (
    "Install mpv from the Bazaar app store, or run: "
    f"flatpak install flathub {FLATPAK_APP_ID}"
)


# Shown with any mpv_command problem (the settings mistakes work).
SETTING_HINT = 'Fix it in settings.json, or set it to "auto" to let the app find mpv.'


def _flatpak_has_mpv() -> bool:
    try:
        result = subprocess.run(
            ["flatpak", "info", FLATPAK_APP_ID],
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _can_run(program: str) -> bool:
    """On the PATH, or a full path to a file we may run (which() checks
    both). A name with a character no file name can hold is never found."""
    try:
        return shutil.which(program) is not None
    except ValueError:
        return False


def _setting_problem(what: str) -> dict:
    """mpv_command is set but can't work: one plain sentence naming it."""
    return {
        "available": False,
        "problem": f"settings.json's 'mpv_command' {what}.",
        "hint": SETTING_HINT,
    }


def detect(mpv_command_setting) -> dict:
    # Left out, null, empty or "auto": the app looks for mpv itself.
    setting = "auto" if mpv_command_setting is None else mpv_command_setting
    if not isinstance(setting, str):
        return _setting_problem('must be text in quotes, like "auto" or "mpv"')
    if setting.strip() not in ("", "auto"):
        try:
            command = shlex.split(setting)
        except ValueError:
            return _setting_problem("has a quote that isn't closed")
        if not command or not _can_run(command[0]):
            return _setting_problem("names a program that can't be found")
        return {"available": True, "command": command, "via": "configured"}

    system_mpv = shutil.which("mpv")
    if system_mpv:
        return {"available": True, "command": [system_mpv], "via": "system"}

    if _flatpak_has_mpv():
        return {
            "available": True,
            "command": ["flatpak", "run", FLATPAK_APP_ID],
            "via": "flatpak",
        }

    return {"available": False, "install_hint": INSTALL_HINT}


START_FAILED = "Playback couldn't start: mpv could not be run."
START_FAILED_HINT = "Check that the configured mpv_command is correct and can be run."

LOG_TAIL_MAX_CHARS = 4000

# Starts a resumed file a few seconds before the saved position.
RESUME_REWIND_SCRIPT = Path(__file__).resolve().parent / "mpv_scripts" / "resume_rewind.lua"
# Saves the position, length and frame when B quits (Continue watching, the Continue watching work).
QUIT_CAPTURE_SCRIPT = Path(__file__).resolve().parent / "mpv_scripts" / "quit_capture.lua"
# Playback controls (the playback controls work): the wording of the on-screen feedback.
PLAYBACK_CONTROLS_SCRIPT = Path(__file__).resolve().parent / "mpv_scripts" / "playback_controls.lua"
# Kettle's key file: the only keys mpv answers to while a film plays.
KEY_FILE = Path(__file__).resolve().parent / "mpv_input.conf"

# Given at every launch, so nothing is ever written into the user's mpv
# settings folder (docs/spec.md, "Playback controls"). mpv's built-in bar is
# off, every default key is off and Kettle's key file replaces the user's
# input.conf. On-screen text: the system font, white with a dark outline,
# size 40 (mpv scales it to the screen: about 44 px high on the Deck).
PLAYBACK_OPTIONS = [
    "--osc=no",
    "--input-default-bindings=no",
    f"--input-conf={KEY_FILE}",
    "--osd-level=1",
    "--osd-font=sans-serif",
    "--osd-font-size=40",
    "--osd-color=#FFFFFF",
    "--osd-border-color=#000000",
    "--osd-border-size=2.5",
]

# The Flatpak mpv can write only here, not into the app's folder
# (docs/spikes/mpv-quit.md); the app moves what it writes afterwards.
SHARED_TMP = Path("/tmp")


# mpv prints its messages and play() copies them into the log. We don't use
# mpv's --log-file: the Flatpak mpv can read the home folder but not write
# to it (docs/decisions.md, "mpv logs"). "vd=v" adds the few lines saying
# which decoder was used and whether hardware decoding worked; they appear
# once, when the video opens. --quiet hides the progress line.
LOG_OPTIONS = ["--quiet", "--msg-level=all=info,vd=v", "--msg-module", "--msg-color=no"]

# A safety limit: normal logs are a few kilobytes.
LOG_MAX_CHARS = 1_000_000

# mpv's progress line, in case it ever prints one despite --quiet.
_STATUS_PREFIXES = ("AV:", "A:", "V:", "(Paused)", "(Buffering)")


# mpv names every picture it saves ("cplayer: Screenshot: '<file>'"), and
# picture names never go into the log (Continue watching, the Continue watching work).
_SCREENSHOT_MESSAGE = "Screenshot: '"


def _log_line(raw: str):
    """The line to keep from one line of mpv output, or None to skip it."""
    # A carriage return redraws a line in place: keep only its last version.
    line = raw.rstrip("\n").split("\r")[-1]
    if not line.strip() or line.lstrip().startswith(_STATUS_PREFIXES):
        return None
    if line.lstrip().startswith(_SCREENSHOT_MESSAGE) or f": {_SCREENSHOT_MESSAGE}" in line:
        return None
    return line


class _PlaybackLog:
    """The per-film log. Lines can come from mpv's output and from the Step 0
    lock diagnostics at the same time, so writes are serialised. A file that
    can't be written is skipped quietly: playback never depends on the log."""

    def __init__(self, log_path: Path, header: list):
        self._lock = threading.Lock()
        self._written = 0
        try:
            self._file = open(log_path, "w", encoding="utf-8")
            self._file.write("\n".join(header) + "\n\n")
            self._file.flush()
        except OSError:
            self._file = None

    def write(self, line: str) -> None:
        with self._lock:
            if self._file is None:
                return
            self._written += len(line) + 1
            try:
                if self._written > LOG_MAX_CHARS:
                    self._file.write("kettle-video: log size limit reached, later messages not saved\n")
                    self._file.close()
                    self._file = None
                    return
                self._file.write(line + "\n")
                self._file.flush()
            except OSError:
                self._file = None

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


def _copy_output_to_log(stream, log: _PlaybackLog) -> None:
    """Copy mpv's messages into the log as they arrive, so a crash mid-film
    still leaves everything up to that point. The stream is always read to
    the end, so mpv never waits on us."""
    for raw in stream:
        line = _log_line(raw)
        if line is not None:
            log.write(line)


def _read_log_tail(log_path: Path, max_chars: int = LOG_TAIL_MAX_CHARS) -> str:
    try:
        data = log_path.read_text(errors="replace")
    except OSError:
        return ""
    return data[-max_chars:]


def _option_name(arg: str) -> str:
    """'--no-resume-playback' and '--resume-playback=yes' -> 'resume-playback'."""
    name = arg.lstrip("-").split("=", 1)[0]
    return name[3:] if name.startswith("no-") else name


def build_command(
    command: list, file_path: Path, extra_args: list = (), resume: bool = True,
    capture_dir: Optional[Path] = None, control_socket: Optional[Path] = None,
    title: Optional[str] = None, watch_later_dir: Optional[Path] = None,
) -> list:
    """The full mpv argument list. Pure: no I/O, so it can be unit tested.

    Resume uses mpv's own saved positions (docs/decisions.md, "Resume"),
    with a small script that starts a few seconds before the saved spot.
    With a capture_dir (and resume on), the Continue watching script saves
    the position and frame there when B quits (the Continue watching work).
    With a control_socket, mpv listens there, so the app can ask it to quit
    when the app closes (the server shutdown check).
    The playback controls (the playback controls work) are always given: Kettle's key file,
    its wording script, mpv's bar off, and the on-screen text style. With a
    title (Kettle's, from the saved library), D-pad Up shows it instead of
    the file name.
    With a watch_later_dir (fresh start, the fresh start mode), mpv reads and saves its
    resume positions there instead of in its own folder. It comes after
    mpv_args, so it wins over theirs: fresh start never touches the real
    positions.
    An option the user already set in mpv_args is never added a second time:
    their value wins.
    """
    extra_args = list(extra_args)
    user_options = {_option_name(a) for a in extra_args if a.startswith("--")}
    capture = []
    # mpv's own "stop the screensaver" stays on, whatever mpv.conf says
    # (the keep-awake work): it works alongside the keep_awake lock.
    if resume:
        defaults = ["--fullscreen", "--save-position-on-quit", "--stop-screensaver=yes"]
        scripts = [f"--script={PLAYBACK_CONTROLS_SCRIPT}", f"--script={RESUME_REWIND_SCRIPT}"]
        if capture_dir is not None:
            scripts.append(f"--script={QUIT_CAPTURE_SCRIPT}")
            # After mpv_args: a --script-opts there replaces the whole list,
            # and -append then adds ours back without touching theirs.
            capture = [f"--script-opts-append=kettle_quit-out_dir={capture_dir}"]
    else:
        defaults = [
            "--fullscreen", "--no-resume-playback", "--no-save-position-on-quit",
            "--stop-screensaver=yes",
        ]
        scripts = [f"--script={PLAYBACK_CONTROLS_SCRIPT}"]
    if watch_later_dir is not None:
        capture.append(f"--watch-later-dir={watch_later_dir}")
    # The playback controls (the playback controls work), with or without resume.
    defaults += PLAYBACK_OPTIONS
    if control_socket is not None:
        defaults.append(f"--input-ipc-server={control_socket}")
    if title:
        defaults.append(f"--force-media-title={title}")
    return [
        *command,
        *(a for a in defaults if _option_name(a) not in user_options),
        *scripts,
        *LOG_OPTIONS,
        *extra_args,
        *capture,
        str(file_path),
    ]


def play(
    command: list,
    file_path: Path,
    log_path: Path,
    extra_args: list = (),
    resume: bool = True,
    keep_awake: bool = False,
    capture_dir: Optional[Path] = None,
    control_socket: Optional[Path] = None,
    title: Optional[str] = None,
    watch_later_dir: Optional[Path] = None,
) -> dict:
    """Run mpv until it exits. The server passes the keep_awake setting
    (on by default in settings.json); it is off here so a direct call never
    takes a system lock by surprise. capture_dir, control_socket, title,
    watch_later_dir: see build_command."""
    extra_args = list(extra_args)
    args = build_command(
        command, file_path, extra_args, resume, capture_dir, control_socket, title, watch_later_dir,
    )
    lock_tool = awake.find_lock_tool() if keep_awake else None
    args, warning = awake.wrap_command(args, keep_awake, lock_tool)

    # Under the lock tool a missing mpv no longer fails to start: the tool
    # starts and then reports it. Check first, so the screen still gets the
    # plain "could not be run" sentence (the stuck Playing fix).
    if lock_tool and not _can_run(command[0]):
        print("could not run mpv: not found", file=sys.stderr)
        return {"ok": False, "error": START_FAILED, "hint": START_FAILED_HINT}

    if warning:
        print(warning, file=sys.stderr)
    header = [f"kettle-video: mpv_args = {extra_args!r}"]
    if not keep_awake:
        header.append("kettle-video: keep_awake = off")
    elif warning:
        header.append(f"kettle-video: {warning}")
    else:
        header.append(f"kettle-video: keep_awake = on ({awake.LOCK_TOOL}, {awake.WHAT})")

    try:
        result = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Not found, not allowed to run, not a program, a bad character in
        # the command: all mean mpv never started (the stuck Playing fix). The screen
        # gets a plain sentence; the log names the kind of problem, never
        # a path.
        print(f"could not run mpv: {type(exc).__name__}", file=sys.stderr)
        return {
            "ok": False,
            "error": START_FAILED,
            "hint": START_FAILED_HINT,
        }

    log = _PlaybackLog(log_path, header)
    stop_diagnostics = awake.start_lock_diagnostics(log.write)  # Step 0, temporary
    try:
        with result:
            _copy_output_to_log(result.stdout, log)
    finally:
        stop_diagnostics.set()  # Step 0, temporary
        log.close()

    if result.returncode == 0:
        return {"ok": True, "log": str(log_path)}

    # One hint for system and Flatpak mpv alike: the mpv Flatpak can already
    # read the whole device, SD card included (the docs catch-up, docs/decisions.md).
    return {
        "ok": False,
        "error": f"mpv exited with status {result.returncode}",
        "log": str(log_path),
        "log_tail": _read_log_tail(log_path),
        "hint": "Check that the file isn't corrupted or in an unsupported format.",
    }


def ask_to_quit(control_socket: Path, timeout: float = 0.5) -> bool:
    """Ask a playing mpv to quit normally, as B does: it saves its resume
    position, and the Continue watching script its frame (the server shutdown check). Used
    when the app closes while a film plays. True if mpv took the request."""
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            sock.connect(str(control_socket))
            sock.sendall(json.dumps({"command": ["quit"]}).encode() + b"\n")
    except OSError:
        return False
    return True


# The Continue watching picture (the Continue watching work): about 480 px wide.
PICTURE_WIDTH = 480
PICTURE_QUALITY = 85


def shrink_frame(command: list, frame: Path, out_dir: Path) -> Optional[Path]:
    """Use mpv itself to make the small picture from a saved frame (Python's
    standard library can't read or write JPEG). Runs after mpv has closed,
    so it never slows down quitting. out_dir must be writable by mpv (under
    SHARED_TMP for the Flatpak). Converting to RGB before scaling is needed:
    without it the picture came out washed out (docs/spikes/mpv-quit.md).
    The picture, or None if mpv made none."""
    try:
        subprocess.run(
            [*command, "--no-config", "--really-quiet", "--frames=1",
             f"--vf=lavfi=[format=rgb24,scale={PICTURE_WIDTH}:-2,setsar=1]", "--vo=image",
             "--vo-image-format=jpg", f"--vo-image-jpeg-quality={PICTURE_QUALITY}",
             f"--vo-image-outdir={out_dir}", str(frame)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    picture = out_dir / "00000001.jpg"
    return picture if picture.is_file() else None
