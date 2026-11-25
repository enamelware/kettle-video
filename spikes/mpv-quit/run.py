# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the mpv quit spike), throwaway prototype, not used by the app.

Plays one file the way Kettle does today (backend.mpv.build_command, so the
resume save and the 5-second rewind are unchanged) plus quit_capture.lua.
After mpv closes it turns the full-size frame into a 640 px wide JPEG and
moves the record and the picture into the app's own data folder
(<data_dir>/spikes/mpv-quit/). Nothing is ever written next to the media.

The Flatpak mpv can read the whole device but cannot write to the app's
folder; it can write to /tmp (shared with the host). So mpv writes into a
fresh folder under /tmp and this runner moves the results.

    python3 spikes/mpv-quit/run.py FILE [--mpv auto|system|flatpak]
        [--watch-later-dir DIR] [--ipc SOCKET] [-- extra mpv args]
"""

import argparse
import hashlib
import json
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import mpv as kettle_mpv  # noqa: E402
from backend.settings import load_settings  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "quit_capture.lua"
PICTURE_WIDTH = 640
JPEG_QUALITY = 85
# Shared with the Flatpak mpv (its permissions include /tmp).
SHARED_TMP = Path("/tmp")


def fingerprint(file_path: Path) -> str:
    """Names the record and picture: the same file always gets the same name."""
    raw = str(file_path).encode("utf-8", "surrogateescape")
    return hashlib.sha1(raw).hexdigest()


def mpv_command(choice: str) -> list:
    if choice == "flatpak":
        return ["flatpak", "run", kettle_mpv.FLATPAK_APP_ID]
    if choice == "system":
        found = shutil.which("mpv")
        if not found:
            raise SystemExit("no system mpv on this device")
        return [found]
    found = kettle_mpv.detect("auto")
    if not found.get("available"):
        raise SystemExit("mpv not found")
    return found["command"]


def build(command: list, file_path: Path, work_dir: Path, file_id: str,
          extra_args: list) -> list:
    """Kettle's own command, with the capture script added before the file."""
    args = kettle_mpv.build_command(command, file_path, extra_args, resume=True)
    added = [
        f"--script={SCRIPT}",
        f"--script-opts=kettle_quit-out_dir={work_dir},kettle_quit-id={file_id}",
    ]
    return args[:-1] + added + args[-1:]


def shrink(command: list, full: Path, work_dir: Path):
    """Use mpv itself to scale the full-size frame to 640 px wide (Python's
    standard library can't read or write JPEG). Runs after quitting.
    Converting to RGB before scaling matters: scaling the JPEG's own colour
    format directly came out washed out (blacks lifted, about 10/255).
    Returns (picture path, None) or (None, a short reason it failed)."""
    try:
        done = subprocess.run(
            [*command, "--no-config", "--really-quiet", "--frames=1",
             f"--vf=lavfi=[format=rgb24,scale={PICTURE_WIDTH}:-2,setsar=1]", "--vo=image",
             "--vo-image-format=jpg", f"--vo-image-jpeg-quality={JPEG_QUALITY}",
             f"--vo-image-outdir={work_dir}", str(full)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            errors="replace", check=False,
        )
    except OSError as exc:
        return None, f"could not run mpv to shrink the picture: {type(exc).__name__}"
    picture = work_dir / "00000001.jpg"
    if picture.exists():
        return picture, None
    detail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no message"]
    return None, f"mpv made no 640 px picture (status {done.returncode}): {detail[0]}"


def _children_cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run(file_path: Path, command: list, out_dir: Path, extra_args: list = (),
        keep_full: bool = False) -> dict:
    file_path = Path(file_path)
    file_id = fingerprint(file_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="kettle-quit-", dir=SHARED_TMP))
    summary = {"id": file_id}
    try:
        args = build(command, file_path, work_dir, file_id, list(extra_args))
        started = time.monotonic()
        result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.STDOUT)
        summary["mpv_ended"] = time.monotonic()
        summary["mpv_exit"] = result.returncode
        summary["mpv_seconds"] = round(summary["mpv_ended"] - started, 3)

        record_src = work_dir / f"{file_id}.json"
        record = json.loads(record_src.read_text()) if record_src.exists() else None
        full = work_dir / f"{file_id}.full.jpg"
        if full.exists():
            summary["full_bytes"] = full.stat().st_size
            started = time.monotonic()
            cpu_before = _children_cpu()
            small, problem = shrink(command, full, work_dir)
            summary["shrink_seconds"] = round(time.monotonic() - started, 3)
            summary["shrink_cpu_seconds"] = round(_children_cpu() - cpu_before, 3)
            if small:
                picture = out_dir / f"{file_id}.jpg"
                shutil.move(small, picture)
                summary["picture"] = str(picture)
                summary["picture_bytes"] = picture.stat().st_size
            else:
                # Say so plainly, and keep the full-size frame so nothing is lost.
                summary["picture_error"] = problem
                print(f"mpv-quit: {problem}", file=sys.stderr)
                keep_full = True
            if record is not None:
                record["picture_saved"] = small is not None
            if keep_full:
                shutil.move(full, out_dir / f"{file_id}.full.jpg")
        if record is not None:
            (out_dir / f"{file_id}.json").write_text(json.dumps(record))
            summary["record"] = record
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return summary


def default_out_dir() -> Path:
    return Path(load_settings()["data_dir"]) / "spikes" / "mpv-quit"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--mpv", choices=["auto", "system", "flatpak"], default="auto")
    parser.add_argument("--watch-later-dir", help="keep test resume saves apart")
    parser.add_argument("--ipc", help="mpv --input-ipc-server path, for scripted runs")
    parser.add_argument("extra", nargs="*", help="extra mpv arguments, after --")
    ns = parser.parse_args(argv)
    extra = list(ns.extra)
    if ns.watch_later_dir:
        extra.append(f"--watch-later-dir={ns.watch_later_dir}")
    if ns.ipc:
        extra.append(f"--input-ipc-server={ns.ipc}")
    summary = run(ns.file, mpv_command(ns.mpv), default_out_dir(), extra)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
