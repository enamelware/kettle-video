# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The system's own folder dialog, for "Browse somewhere else" (the Browse somewhere else work).
No HTTP awareness.

As the spike recommends (docs/spikes/folder-dialog.md, "What onboarding part 1
needs to call it"): kdialog, then zenity, then Python's own Tk dialog, whichever
is found first; never the desktop portal. Each is a program already on the
system, started as it is, as its own process. Tk needs a second Python because
it must run on a program's main thread.

There is no time limit while a dialog is open. Its error output goes nowhere,
because it could name a folder and the launch log must not. This module never
logs and never creates anything: "New folder" inside a dialog is the system's.
"""

import os
import shutil
import signal
import subprocess
import sys
from typing import Optional, Tuple

TITLE = "Choose a folder"
PROGRAMS = ("kdialog", "zenity")
PYTHON = sys.executable

PICKED, CANCELLED, NOT_A_FOLDER, FAILED = "picked", "cancelled", "not a folder", "failed"

# The sentences the page shows.
OPEN_FAILED = "Couldn't open the folder window. Choose a folder from the list instead."
ALREADY_OPEN = "The folder window is already open."
NOT_A_FOLDER_MESSAGE = "That isn't a folder, so pick a different one."

# Exit 2 if Tk can't open its window: Python's own exit for an error is 1, which
# would read as a cancel. Bytes, not print(): a folder's name need not be valid
# text.
TK_CHILD = (
    "import os, sys\n"
    "try:\n"
    "    import tkinter, tkinter.filedialog\n"
    "    root = tkinter.Tk()\n"
    "    root.withdraw()\n"
    "    path = tkinter.filedialog.askdirectory(parent=root, title=sys.argv[1], initialdir=sys.argv[2], mustexist=True)\n"
    "except Exception:\n"
    "    sys.exit(2)\n"
    "sys.stdout.buffer.write(os.fsencode(path or ''))\n"
)


def _tk_works() -> bool:
    """tkinter is missing on some systems, and Tk needs an X display."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        done = subprocess.run([PYTHON, "-c", "import tkinter"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def find() -> Optional[str]:
    """The first dialog this device has, or None: the row is then hidden."""
    for name in PROGRAMS:
        if shutil.which(name):
            return name
    return "tk" if _tk_works() else None


def command(name: str, start: str) -> list:
    """The command that opens this dialog in folder mode at the folder start."""
    if name == "kdialog":
        return ["kdialog", "--title", TITLE, "--getexistingdirectory", start]
    if name == "zenity":
        return ["zenity", "--file-selection", "--directory", f"--title={TITLE}", f"--filename={start}/"]
    return [PYTHON, "-c", TK_CHILD, TITLE, start]


def start(name: str) -> subprocess.Popen:
    """Opens the dialog at the home folder. Raises OSError if it can't start."""
    return subprocess.Popen(command(name, os.path.expanduser("~")), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def outcome(returncode: int, output: bytes) -> Tuple[str, Optional[str]]:
    """What the dialog's exit code and output mean: (PICKED, the path) or
    (one of the others, None). Exit 1 or empty output is a cancel; so is the
    stop signal, which is how Kettle itself closes a dialog. Any other signal is
    a dialog that crashed, so it failed, and the person is told. Only line
    endings are trimmed: a folder's name can really end in a space."""
    path = os.fsdecode(output).rstrip("\r\n")
    if returncode in (1, -signal.SIGTERM) or (returncode == 0 and not path.strip()):
        return CANCELLED, None
    if returncode != 0:
        return FAILED, None
    if not os.path.isdir(path):
        return NOT_A_FOLDER, None
    return PICKED, path


def wait(process: subprocess.Popen) -> Tuple[str, Optional[str]]:
    """Blocks, with no time limit, until the dialog closes."""
    output, _ = process.communicate()
    return outcome(process.returncode, output)


def close(process: subprocess.Popen) -> None:
    """Closes an open dialog, which then counts as cancelled."""
    process.terminate()
