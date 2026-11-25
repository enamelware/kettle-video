-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Mario Carabotta

-- Kettle spike (the mpv quit spike), throwaway prototype, not loaded by the app.
--
-- When the viewer presses B (the q key), save:
--   <out_dir>/<id>.json      which file, position, duration, time of quit
--   <out_dir>/<id>.full.jpg  the frame on screen, video only (no subtitles,
--                            no on-screen text), at the video's own size
-- and then quit exactly as mpv's own q does, so --save-position-on-quit
-- still saves the resume position.
--
-- A film that plays to the end writes a record with finished = true (mpv
-- itself saves nothing then). Any other way of closing (window closed, a
-- stop signal that reaches mpv) writes a record with how = "other" and no
-- picture, from the last position seen.
--
-- out_dir and id come from the runner (run.py) through
-- --script-opts=kettle_quit-out_dir=...,kettle_quit-id=...
-- The 640 px picture is made by the runner after mpv has closed, so the
-- resize never slows down quitting.

local options = require "mp.options"
local utils = require "mp.utils"

local opts = { out_dir = "", id = "" }
options.read_options(opts, "kettle_quit")

local recorded = false
-- Remembered while playing: at end of file or shutdown, mpv may already
-- have unloaded the file and these properties are gone.
local last = {}

for _, name in ipairs({ "time-pos", "duration", "path" }) do
    mp.observe_property(name, "native", function(_, value)
        if value ~= nil then
            last[name] = value
        end
    end)
end

local function out_path(suffix)
    return utils.join_path(opts.out_dir, opts.id .. suffix)
end

local function write_record(record)
    if opts.out_dir == "" or opts.id == "" then
        mp.msg.warn("kettle_quit: no out_dir or id given, nothing saved")
        return
    end
    -- Write to a temporary name first so a reader never sees half a file.
    local tmp = out_path(".json.part")
    local file, err = io.open(tmp, "w")
    if not file then
        mp.msg.error("kettle_quit: cannot write record: " .. tostring(err))
        return
    end
    file:write(utils.format_json(record))
    file:close()
    local ok, rename_err = os.rename(tmp, out_path(".json"))
    if not ok then
        mp.msg.error("kettle_quit: cannot save record: " .. tostring(rename_err))
    end
end

local function base_record(how)
    return {
        file = mp.get_property("path") or last["path"],
        duration = mp.get_property_number("duration") or last["duration"],
        quit_at = os.time(),
        how = how,
    }
end

local function quit_with_capture()
    local started = mp.get_time()
    local record = base_record("b")
    record.paused = mp.get_property_bool("pause")
    -- Pause first, so the frame on screen, the position saved here and
    -- the resume position mpv saves on quit are all the same moment.
    mp.set_property_bool("pause", true)
    record.position = mp.get_property_number("time-pos") or last["time-pos"]
    record.finished = false

    -- "video" = the decoded frame only: no subtitles, no on-screen text.
    local _, err = mp.command_native({
        name = "screenshot-to-file",
        filename = out_path(".full.jpg"),
        flags = "video",
    })
    record.frame_saved = (err == nil and utils.file_info(out_path(".full.jpg")) ~= nil)
    if not record.frame_saved then
        mp.msg.warn("kettle_quit: frame not saved: " .. tostring(err))
    end
    record.capture_ms = math.floor((mp.get_time() - started) * 1000 + 0.5)

    write_record(record)
    recorded = true
    mp.msg.info(string.format("kettle_quit: saved at %.3f s in %d ms",
        record.position or -1, record.capture_ms))
    -- The same command as mpv's own q binding.
    mp.command("quit")
end

-- Forced since the playback controls work: run.py starts mpv the way Kettle does, with
-- Kettle's key file, whose plain q binding would otherwise win.
mp.add_forced_key_binding("q", "kettle-quit", quit_with_capture)

mp.register_event("end-file", function(event)
    if recorded or event.reason ~= "eof" then
        return
    end
    local record = base_record("end")
    record.position = record.duration or last["time-pos"]
    record.finished = true
    record.frame_saved = false
    write_record(record)
    recorded = true
end)

mp.register_event("shutdown", function()
    if recorded then
        return
    end
    local record = base_record("other")
    record.position = last["time-pos"]
    record.finished = false
    record.frame_saved = false
    write_record(record)
    recorded = true
end)
