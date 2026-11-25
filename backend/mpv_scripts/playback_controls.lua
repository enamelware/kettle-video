-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Mario Carabotta

-- Kettle: the wording of the on-screen feedback while a film plays
-- (the playback controls work). Passed to mpv with --script by backend/mpv.py at every
-- launch, together with Kettle's key file (backend/mpv_input.conf), which
-- calls the actions below by name ("script-binding playback_controls/...").
-- No keys are bound here: the key file decides which key does what.
--
-- Only the wording needs a script: "Paused", the track names, "No subtitles
-- in this file" and "Only one audio track" depend on the file, which key
-- bindings alone can't check. Everything is shown with mpv's own on-screen
-- text and progress bar.

local SEEK_SHOW_MS = 2000   -- seeking: the bar with elapsed and total time
local PAUSED_SHOW_S = 3     -- pausing: "Paused" with the times
local WHERE_SHOW_MS = 3000  -- D-pad Up: title, times and the bar
local TRACK_SHOW_S = 3      -- subtitle and audio track names

-- The text mpv shows under its progress bar (osd-status-msg). D-pad Up
-- adds the title for a moment; anything else goes back to the times only.
-- The title is Kettle's own (passed with --force-media-title); a file
-- outside the saved library shows what mpv finds itself (the file's own
-- title, or its name).
local TIMES = "${time-pos} / ${duration}"
local TITLE_AND_TIMES = "${media-title}\n" .. TIMES

-- Language codes as mpv reports them (two or three letters) and their
-- English names. A code not listed here is shown as it is.
local LANGUAGES = {
    ar = "Arabic", ara = "Arabic",
    bg = "Bulgarian", bul = "Bulgarian",
    ca = "Catalan", cat = "Catalan",
    cs = "Czech", ces = "Czech", cze = "Czech",
    da = "Danish", dan = "Danish",
    de = "German", deu = "German", ger = "German",
    el = "Greek", ell = "Greek", gre = "Greek",
    en = "English", eng = "English",
    es = "Spanish", spa = "Spanish",
    et = "Estonian", est = "Estonian",
    fa = "Persian", fas = "Persian", per = "Persian",
    fi = "Finnish", fin = "Finnish",
    fr = "French", fra = "French", fre = "French",
    he = "Hebrew", heb = "Hebrew",
    hi = "Hindi", hin = "Hindi",
    hr = "Croatian", hrv = "Croatian",
    hu = "Hungarian", hun = "Hungarian",
    id = "Indonesian", ind = "Indonesian",
    is = "Icelandic", isl = "Icelandic", ice = "Icelandic",
    it = "Italian", ita = "Italian",
    ja = "Japanese", jpn = "Japanese",
    ko = "Korean", kor = "Korean",
    lt = "Lithuanian", lit = "Lithuanian",
    lv = "Latvian", lav = "Latvian",
    ms = "Malay", msa = "Malay", may = "Malay",
    nl = "Dutch", nld = "Dutch", dut = "Dutch",
    no = "Norwegian", nor = "Norwegian", nb = "Norwegian", nob = "Norwegian",
    pl = "Polish", pol = "Polish",
    pt = "Portuguese", por = "Portuguese",
    ro = "Romanian", ron = "Romanian", rum = "Romanian",
    ru = "Russian", rus = "Russian",
    sk = "Slovak", slk = "Slovak", slo = "Slovak",
    sl = "Slovenian", slv = "Slovenian",
    sr = "Serbian", srp = "Serbian",
    sv = "Swedish", swe = "Swedish",
    th = "Thai", tha = "Thai",
    tr = "Turkish", tur = "Turkish",
    uk = "Ukrainian", ukr = "Ukrainian",
    vi = "Vietnamese", vie = "Vietnamese",
    zh = "Chinese", zho = "Chinese", chi = "Chinese",
}

-- Each message also goes to mpv's log, so the automated check can read
-- what was shown. Track names come from inside the video file, never from
-- a file or folder name.
local function show(text, seconds)
    mp.osd_message(text, seconds)
    mp.msg.info("shown: " .. text:gsub("\n", " | "))
end

local function status_text(text, duration_ms)
    mp.set_property("osd-status-msg", text)
    mp.set_property_number("osd-duration", duration_ms)
end

-- The language's name, else the track's title, else "Track 2".
local function track_name(track)
    local lang = track.lang
    if lang and lang ~= "" and lang ~= "und" then
        return LANGUAGES[lang:lower()] or lang
    end
    if track.title and track.title ~= "" then
        return track.title
    end
    return "Track " .. tostring(track.id)
end

local function tracks_of(kind)
    local found = {}
    for _, track in ipairs(mp.get_property_native("track-list") or {}) do
        if track.type == kind then
            found[#found + 1] = track
        end
    end
    return found
end

-- The track after the selected one; nil after the last one (Off).
local function next_track(tracks)
    for i, track in ipairs(tracks) do
        if track.selected then
            return tracks[i + 1]
        end
    end
    return tracks[1]
end

local function play_pause()
    local paused = not mp.get_property_bool("pause")
    mp.set_property_bool("pause", paused)
    if paused then
        show("Paused\n" .. mp.get_property_osd("time-pos", "") .. " / "
            .. mp.get_property_osd("duration", ""), PAUSED_SHOW_S)
    else
        mp.osd_message("", 0)
    end
end

local function seek(seconds)
    status_text(TIMES, SEEK_SHOW_MS)
    mp.command("osd-msg-bar seek " .. seconds .. " relative")
end

local function show_where()
    status_text(TITLE_AND_TIMES, WHERE_SHOW_MS)
    mp.command("osd-msg-bar show-progress")
end

local function next_subtitle()
    local tracks = tracks_of("sub")
    if #tracks == 0 then
        show("No subtitles in this file", TRACK_SHOW_S)
        return
    end
    local track = next_track(tracks)
    if track then
        mp.set_property_number("sid", track.id)
        show("Subtitles: " .. track_name(track), TRACK_SHOW_S)
    else
        mp.set_property("sid", "no")
        show("Subtitles: Off", TRACK_SHOW_S)
    end
end

local function next_audio()
    local tracks = tracks_of("audio")
    if #tracks == 0 then
        show("No audio in this file", TRACK_SHOW_S)
        return
    end
    if #tracks == 1 then
        show("Only one audio track", TRACK_SHOW_S)
        return
    end
    -- Audio never goes Off: after the last track comes the first again.
    local track = next_track(tracks) or tracks[1]
    mp.set_property_number("aid", track.id)
    show("Audio: " .. track_name(track), TRACK_SHOW_S)
end

status_text(TIMES, SEEK_SHOW_MS)

local repeat_ok = { repeatable = true }
mp.add_key_binding(nil, "play-pause", play_pause)
mp.add_key_binding(nil, "back-10s", function() seek(-10) end, repeat_ok)
mp.add_key_binding(nil, "forward-10s", function() seek(10) end, repeat_ok)
mp.add_key_binding(nil, "back-1min", function() seek(-60) end, repeat_ok)
mp.add_key_binding(nil, "forward-1min", function() seek(60) end, repeat_ok)
mp.add_key_binding(nil, "next-subtitle", next_subtitle)
mp.add_key_binding(nil, "next-audio", next_audio)
mp.add_key_binding(nil, "show-where", show_where)
