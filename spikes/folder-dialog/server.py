# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the folder dialog spike): a small server, started the way launch.sh
starts the app's (python3 -u, from the project folder, in the background),
that opens a folder dialog when asked and keeps answering meanwhile.

    GET  /                    the test page (page.html)
    GET  /api/ping            {"ok": true}: shows the server still answers
    GET  /api/checks          Question 1 on this device
    POST /api/open/NAME       opens dialog NAME; answers when it closes
         ?close_after=S       (automatic check) stop it after S seconds
    POST /api/note            the page's focus record for the last dialog
    POST /api/quit            stops the server (the launcher then closes Firefox)

Each record goes to stdout, with no folder names (dialogs.describe), so
the launcher's log can be pasted into the issue. Not part of the app.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dialogs  # noqa: E402

PAGE = os.path.join(HERE, "page.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # records only, below

    def _answer(self, status, payload, kind="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            with open(PAGE, "rb") as f:
                self._answer(200, f.read(), "text/html; charset=utf-8")
        elif path == "/api/ping":
            self._answer(200, {"ok": True})
        elif path == "/api/checks":
            self._answer(200, dialogs.checks())
        else:
            self._answer(404, {"ok": False})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else b""
        if url.path.startswith("/api/open/"):
            name = url.path.rsplit("/", 1)[1]
            close_after = parse_qs(url.query).get("close_after", [None])[0]
            print(f"open {name}", flush=True)
            record = dialogs.open_dialog(name, float(close_after) if close_after else None)
            print("record " + json.dumps(record), flush=True)
            self._answer(200, record)
        elif url.path == "/api/note":
            note = json.loads(data or b"{}")
            # Only the page's own fields: no free text reaches the log.
            keep = {k: note[k] for k in ("dialog", "lostFocus", "focusBack", "secondsToFocus") if k in note}
            print("focus " + json.dumps(keep), flush=True)
            self._answer(200, {"ok": True})
        elif url.path == "/api/quit":
            self._answer(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._answer(404, {"ok": False})


def main():
    port = int(os.environ.get("KETTLE_SPIKE_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"folder dialog spike listening on port {port}", flush=True)
    server.serve_forever()
    print("folder dialog spike stopped", flush=True)


if __name__ == "__main__":
    main()
