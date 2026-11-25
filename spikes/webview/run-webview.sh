#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Kettle spike (the webview spike): opens the app in the Route C web view instead of
# Firefox. Point a non-Steam shortcut at this file. Deleting spikes/webview/
# removes it and everything it uses. Output goes to logs/webview-spike.log.
cd "$(dirname "$0")/../.." || exit 1
mkdir -p logs
exec spikes/webview/.venv-c/bin/python spikes/webview/window_pywebview.py >>logs/webview-spike.log 2>&1
