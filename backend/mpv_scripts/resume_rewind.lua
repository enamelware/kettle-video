-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Mario Carabotta

-- Kettle: when mpv resumes a file from its saved position, start a few
-- seconds earlier so the viewer can pick up the thread. Passed to mpv with
-- --script by backend/mpv.py when resume is on (docs/decisions.md, "Resume").

local REWIND_SECONDS = 5

-- A start position given on the command line (or in mpv.conf) is the user's
-- choice, not a resume, so it is left alone.
local configured_start = mp.get_property("options/start")

-- mpv has already applied the saved position as this file's start when
-- on_load runs, so moving it here avoids a visible jump.
mp.add_hook("on_load", 50, function()
    local start = mp.get_property("file-local-options/start")
    if start == configured_start then
        return
    end
    -- Saved positions are plain seconds; leave anything else (percent,
    -- chapter, relative) untouched.
    local seconds = tonumber(start)
    if not seconds then
        return
    end
    local rewound = math.max(seconds - REWIND_SECONDS, 0)
    mp.set_property("file-local-options/start", string.format("%.3f", rewound))
    mp.msg.info(string.format("resume: %.1f s -> %.1f s", seconds, rewound))
end)
