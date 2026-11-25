-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Mario Carabotta

-- Kettle: Continue watching (the Continue watching work), built from option 1 of the spike
-- in docs/spikes/mpv-quit.md. Passed to mpv with --script by backend/mpv.py
-- when the film belongs to the saved library and resume is on.
--
-- When the viewer presses B (the q key, or Esc), save into out_dir:
--   record.json  position, duration, finished = false, frame_saved
--   frame.jpg    the frame on screen, video only (no subtitles, no
--                on-screen text), at the video's own size
-- and then quit exactly as mpv's own q does, so --save-position-on-quit
-- still saves the resume position.
--
-- A film that plays to the end writes finished = true (mpv itself saves
-- nothing then). Any other way of closing (window closed, the app asking
-- mpv to quit as it closes, a stop signal that reaches mpv, as Steam's
-- "Exit game" sends) writes the position and the frame too: they are taken
-- just before mpv lets go of the film (the server shutdown check). Only a forced kill
-- saves nothing.
--
-- out_dir comes from the app through
-- --script-opts-append=kettle_quit-out_dir=<a fresh folder under /tmp>:
-- the Flatpak mpv can't write into the app's folder, only to /tmp. The app
-- moves the files and makes the small picture after mpv has closed.
--
-- Messages name no file or folder: the log never holds picture names.

local options = require "mp.options"
local utils = require "mp.utils"

local opts = { out_dir = "" }
options.read_options(opts, "kettle_quit")

local recorded = false
-- Remembered while playing: at end of file or shutdown, mpv may already
-- have unloaded the file and these properties are gone.
local last = {}

for _, name in ipairs({ "time-pos", "duration" }) do
    mp.observe_property(name, "native", function(_, value)
        if value ~= nil then
            last[name] = value
        end
    end)
end

local function out_path(name)
    return utils.join_path(opts.out_dir, name)
end

local function write_record(record)
    recorded = true
    if opts.out_dir == "" then
        mp.msg.warn("kettle_quit: no out_dir given, nothing saved")
        return
    end
    -- Write to a temporary name first so the app never reads half a file.
    local file = io.open(out_path("record.json.part"), "w")
    if not file then
        mp.msg.error("kettle_quit: cannot write the record")
        return
    end
    file:write(utils.format_json(record))
    file:close()
    if not os.rename(out_path("record.json.part"), out_path("record.json")) then
        mp.msg.error("kettle_quit: cannot save the record")
    end
end

-- The position, length and frame on screen, as a record not yet written.
local function capture()
    local record = {
        position = mp.get_property_number("time-pos") or last["time-pos"],
        duration = mp.get_property_number("duration") or last["duration"],
        finished = false,
    }
    -- "video" = the decoded frame only: no subtitles, no on-screen text.
    local _, err = mp.command_native({
        name = "screenshot-to-file",
        filename = out_path("frame.jpg"),
        flags = "video",
    })
    record.frame_saved = (err == nil and utils.file_info(out_path("frame.jpg")) ~= nil)
    if not record.frame_saved then
        mp.msg.warn("kettle_quit: frame not saved")
    end
    return record
end

-- Taken while closing in any other way than B, written at shutdown.
local closing = nil

local function quit_with_capture()
    -- Pause first, so the frame on screen, the position saved here and
    -- the resume position mpv saves on quit are all the same moment.
    mp.set_property_bool("pause", true)
    local record = capture()
    write_record(record)
    mp.msg.info(string.format("kettle_quit: saved at %.1f s", record.position or -1))
    -- The same command as mpv's own q binding.
    mp.command("quit")
end

-- Forced: Kettle switches mpv's other keys off (the playback controls work), which would
-- switch a plain binding off too. q is B on the controller, Esc the
-- keyboard's stop key; Kettle's key file binds both to a plain quit for
-- when this script isn't passed.
mp.add_forced_key_binding("q", "kettle-quit", quit_with_capture)
mp.add_forced_key_binding("ESC", "kettle-quit-esc", quit_with_capture)

mp.register_event("end-file", function(event)
    if recorded or event.reason ~= "eof" then
        return
    end
    local duration = last["duration"]
    write_record({
        position = duration or last["time-pos"],
        duration = duration,
        finished = true,
        frame_saved = false,
    })
end)

-- Runs just before mpv unloads the film, however it is closing, while the
-- frame is still there (the server shutdown check). Not at the end of the film: that is
-- "finished", with no picture.
mp.add_hook("on_unload", 50, function()
    if recorded or opts.out_dir == "" or mp.get_property_bool("eof-reached") then
        return
    end
    closing = capture()
end)

mp.register_event("shutdown", function()
    if recorded then
        return
    end
    write_record(closing or {
        position = last["time-pos"],
        duration = last["duration"],
        finished = false,
        frame_saved = false,
    })
end)
