# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike), throwaway probe, not used by the app.

Answers Question 1 of the webview spike on whichever device it runs on:
Python version, pip / venv / ensurepip, GTK + WebKit through the GTK
bindings, Qt bindings + Qt WebEngine, and the processor type. Each check is
run in a fresh Python process so one failure cannot hide another, and the
exact code of each check is printed next to its result.

Read-only: it installs nothing and writes nothing.

    python3 spikes/webview/probe.py
"""

import glob
import platform
import subprocess
import sys

CHECKS = [
    ("pip", "import pip; print(pip.__version__)"),
    ("venv", "import venv; print('ok')"),
    ("ensurepip", "import ensurepip; print(ensurepip.version())"),
    ("GTK bindings (gi)", "import gi; print(gi.__version__)"),
    ("GTK 3", "import gi; gi.require_version('Gtk', '3.0'); "
              "from gi.repository import Gtk; "
              "print(Gtk.get_major_version(), Gtk.get_minor_version(), "
              "Gtk.get_micro_version())"),
    ("GTK 4", "import gi; gi.require_version('Gtk', '4.0'); "
              "from gi.repository import Gtk; "
              "print(Gtk.get_major_version(), Gtk.get_minor_version(), "
              "Gtk.get_micro_version())"),
    ("WebKit2GTK 4.1 (GTK 3)", "import gi; gi.require_version('WebKit2', '4.1'); "
                               "from gi.repository import WebKit2; "
                               "print(WebKit2.get_major_version(), "
                               "WebKit2.get_minor_version())"),
    ("WebKit2GTK 4.0 (GTK 3)", "import gi; gi.require_version('WebKit2', '4.0'); "
                               "from gi.repository import WebKit2; "
                               "print(WebKit2.get_major_version(), "
                               "WebKit2.get_minor_version())"),
    ("WebKitGTK 6.0 (GTK 4)", "import gi; gi.require_version('WebKit', '6.0'); "
                              "from gi.repository import WebKit; "
                              "print(WebKit.get_major_version(), "
                              "WebKit.get_minor_version())"),
    ("PyQt6 + WebEngine", "from PyQt6.QtCore import QT_VERSION_STR; "
                          "from PyQt6 import QtWebEngineWidgets; "
                          "print(QT_VERSION_STR)"),
    ("PySide6 + WebEngine", "import PySide6; from PySide6 import QtWebEngineWidgets; "
                            "print(PySide6.__version__)"),
    ("PyQt5 + WebEngine", "from PyQt5.QtCore import QT_VERSION_STR; "
                          "from PyQt5 import QtWebEngineWidgets; "
                          "print(QT_VERSION_STR)"),
]

# System libraries that matter even without Python bindings: they tell
# whether a route "would need a system change" or only a binding.
LIBRARY_PATTERNS = [
    "/usr/lib*/libwebkit2gtk-*.so*",
    "/usr/lib*/libwebkitgtk-6*.so*",
    "/usr/lib*/*/libwebkit2gtk-*.so*",
    "/usr/lib*/libQt6WebEngineCore.so.*",
    "/usr/lib*/*/libQt6WebEngineCore.so.*",
    "/usr/lib*/libQt5WebEngineCore.so.*",
    "/usr/lib*/girepository-1.0/WebKit*.typelib",
    "/usr/lib*/*/girepository-1.0/WebKit*.typelib",
]


def run_check(code):
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return "yes", result.stdout.strip()
    last = (result.stderr.strip().splitlines() or ["(no message)"])[-1]
    return "no", last


def main():
    print(f"Device: {platform.node()}  processor: {platform.machine()}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    for name, code in CHECKS:
        found, detail = run_check(code)
        print(f"\n{name}: {found}  {detail}")
        print(f"  check: {sys.executable} -c \"{code}\"")
    print("\nSystem libraries (no Python needed):")
    hits = sorted({p for pattern in LIBRARY_PATTERNS for p in glob.glob(pattern)})
    for path in hits:
        print(f"  {path}")
    if not hits:
        print("  none of WebKitGTK or Qt WebEngine found")


if __name__ == "__main__":
    main()
