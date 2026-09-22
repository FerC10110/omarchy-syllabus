-- Syllabus's mpv companion. Loaded by `syllabus play` with
--   --script-opt=syllabus-bin=<path to bin/syllabus> --script-opt=syllabus-report=<seconds>
-- It reports where each video was left and how long it was watched, shows the
-- video's bookmarks as chapters, and saves a new bookmark with the "b" key.
local mp = require("mp")
local utils = require("mp.utils")
local input = require("mp.input")

local bin = mp.get_opt("syllabus-bin")
if not bin or bin == "" then
  return
end
local every = tonumber(mp.get_opt("syllabus-report") or "") or 30

-- Reports are numbered so the CLI can drop one that arrives after a newer one.
-- Starting from the clock keeps them above what an earlier mpv already sent.
local seq = math.floor(os.time() * 1000)

local current = nil       -- { path, pos, duration } of the loaded video
local played = 0          -- seconds watched since the last report
local playing_since = nil -- mp.get_time() when playback last started
local loaded = false      -- whether the current file has successfully loaded

-- Fire and forget: detached, and not tied to the playback lifetime, so a
-- report sent while mpv is quitting still runs.
local function run(args)
  mp.command_native({ name = "subprocess", args = args, detach = true, playback_only = false })
end

local function count_time()
  if playing_since then
    local now = mp.get_time()
    played = played + (now - playing_since)
    playing_since = now
  end
end

local function set_playing(on)
  if on and not playing_since then
    playing_since = mp.get_time()
  elseif not on and playing_since then
    count_time()
    playing_since = nil
  end
end

-- keep_last: this video is ending because another one replaced it (or it
-- failed), so the report must not make it the last video again.
local function report(eof, keep_last)
  if not current then
    return
  end
  count_time()
  seq = seq + 1
  local args = {
    bin, "report",
    "--path=" .. current.path,
    "--pos=" .. string.format("%.3f", current.pos),
    "--duration=" .. string.format("%.3f", current.duration),
    "--played=" .. string.format("%.1f", played),
    "--seq=" .. string.format("%.0f", seq),
  }
  if eof then
    table.insert(args, "--eof")
  end
  if keep_last then
    table.insert(args, "--keep-last")
  end
  played = 0
  run(args)
end

local function add_chapters(marks)
  local chapters = mp.get_property_native("chapter-list") or {}
  for _, mark in ipairs(marks) do
    table.insert(chapters, { title = mark.text ~= "" and mark.text or "Bookmark", time = mark.at })
  end
  table.sort(chapters, function(a, b) return a.time < b.time end)
  mp.set_property_native("chapter-list", chapters)
end

local function load_bookmarks(path)
  mp.command_native_async({
    name = "subprocess",
    args = { bin, "bookmarks", "--path=" .. path },
    capture_stdout = true,
    playback_only = false,
  }, function(ok, result)
    if not ok or not result or result.status ~= 0 or not current or current.path ~= path then
      return
    end
    local data = utils.parse_json(result.stdout or "")
    if data and type(data.bookmarks) == "table" and #data.bookmarks > 0 then
      add_chapters(data.bookmarks)
    end
  end)
end

mp.register_event("start-file", function()
  loaded = false
end)

local function bookmark()
  if not current then
    return
  end
  local path = current.path
  local at = mp.get_property_number("time-pos") or current.pos
  input.get({
    prompt = "Bookmark at " .. mp.format_time(at) .. ": ",
    submit = function(text)
      input.terminate()
      mp.command_native_async({
        name = "subprocess",
        args = { bin, "bookmark-here", "--path=" .. path, "--at=" .. string.format("%.3f", at), "--text=" .. text },
        capture_stdout = true,
        playback_only = false,
      }, function(ok, result)
        if ok and result and result.status == 0 then
          if current and current.path == path then
            add_chapters({ { at = at, text = text } })
          end
          mp.osd_message("Bookmark saved")
        else
          mp.osd_message("Could not save the bookmark")
        end
      end)
    end,
  })
end

mp.register_event("file-loaded", function()
  loaded = true
  current = {
    path = mp.get_property("path"),
    pos = mp.get_property_number("time-pos") or 0,
    duration = mp.get_property_number("duration") or 0,
  }
  played = 0
  playing_since = nil
  set_playing(mp.get_property_native("core-idle") == false)
  load_bookmarks(current.path)
end)

mp.observe_property("time-pos", "number", function(_, value)
  if current and value then
    current.pos = value
  end
end)

mp.observe_property("duration", "number", function(_, value)
  if current and value then
    current.duration = value
  end
end)

-- Paused, buffering or seeking time does not count as studied.
mp.observe_property("core-idle", "bool", function(_, idle)
  set_playing(current ~= nil and idle == false)
end)

-- With keep-open=yes mpv pauses at the end instead of ending the file.
mp.observe_property("eof-reached", "bool", function(_, reached)
  if reached then
    report(true)
  end
end)

-- After `loadfile replace` the old video ends with reason "stop" once `syllabus
-- play` has already made the new one the last video.
mp.register_event("end-file", function(event)
  if event.reason == "error" and not loaded then
    -- No internet, a link that died, or a disk that is not there: the cause reads the same.
    local what = mp.get_property("media-title") or mp.get_property("path") or "that video"
    run({ "notify-send", "-a", "Syllabus", "Syllabus",
          "Couldn't play " .. what .. ": no internet, or the video is no longer available" })
  end
  report(event.reason == "eof", event.reason ~= "eof" and event.reason ~= "quit")
  current = nil
  playing_since = nil
end)

mp.register_event("shutdown", function()
  report(false)
end)

mp.add_periodic_timer(every, function()
  if playing_since then
    report(false)
  end
end)

mp.add_key_binding("b", "syllabus-bookmark", bookmark)
