import json
import os
import shutil
import stat
import subprocess
import time
import unittest

from support import PLUGIN, TempHome

LUA = os.path.join(PLUGIN, "mpv", "syllabus.lua")

FAKE_BIN = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_BIN_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "bookmarks":
    print(json.dumps({"lessonId": "x", "bookmarks": [{"id": "b", "at": 1.5, "text": "intro"}]}))
'''

REPLACE_THEN_QUIT = r'''
local mp = require("mp")
local loads = 0
mp.register_event("file-loaded", function()
  loads = loads + 1
  if loads == 1 then
    mp.add_timeout(0.5, function() mp.commandv("loadfile", mp.get_opt("helper-second"), "replace") end)
  else
    mp.add_timeout(0.5, function() mp.command("quit") end)
  end
end)
'''


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg"), "needs mpv and ffmpeg")
class Companion(TempHome):
    def test_reports_until_the_end(self):
        video = os.path.join(self.tmp, "a b.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=64x64:rate=10",
                        "-pix_fmt", "yuv420p", video], check=True)
        fake = os.path.join(self.tmp, "fake-bin")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_BIN)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        log = os.path.join(self.tmp, "calls.log")
        env = dict(os.environ, FAKE_BIN_LOG=log)
        subprocess.run(["mpv", "--no-config", "--vo=null", "--ao=null", "--msg-level=all=error",
                        f"--script={LUA}", f"--script-opt=syllabus-bin={fake}", "--script-opt=syllabus-report=1",
                        video], env=env, timeout=30, check=True)
        calls = []
        for _ in range(50):  # detached reports can land a moment after mpv exits
            if os.path.exists(log):
                with open(log, encoding="utf-8") as f:
                    calls = [json.loads(line) for line in f]
            if any("--eof" in c for c in calls):
                break
            time.sleep(0.1)
        self.assertIn(["bookmarks", f"--path={video}"], calls)
        # Detached processes may write the log out of order: sort by their seq.
        reports = sorted((c for c in calls if c[0] == "report"), key=lambda c: int(c[5].split("=")[1]))
        self.assertGreaterEqual(len(reports), 2)
        self.assertTrue(all(c[1] == f"--path={video}" for c in reports))
        seqs = [int(c[5].split("=")[1]) for c in reports]
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertIn("--eof", reports[-1])
        played = sum(float(c[4].split("=")[1]) for c in reports)
        self.assertAlmostEqual(played, 3.0, delta=0.6)

    def test_a_replaced_video_does_not_take_back_last(self):
        first = os.path.join(self.tmp, "first.mp4")
        second = os.path.join(self.tmp, "second.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=64x64:rate=10",
                        "-pix_fmt", "yuv420p", first], check=True)
        shutil.copyfile(first, second)
        fake = os.path.join(self.tmp, "fake-bin")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_BIN)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        # Does what `syllabus play` does to a running mpv (loadfile replace), then quits.
        helper = os.path.join(self.tmp, "helper.lua")
        with open(helper, "w", encoding="utf-8") as f:
            f.write(REPLACE_THEN_QUIT)
        log = os.path.join(self.tmp, "calls.log")
        env = dict(os.environ, FAKE_BIN_LOG=log)
        subprocess.run(["mpv", "--no-config", "--vo=null", "--ao=null", "--msg-level=all=error", "--pause",
                        f"--script={LUA}", f"--script={helper}", f"--script-opt=helper-second={second}",
                        f"--script-opt=syllabus-bin={fake}", first], env=env, timeout=30, check=True)
        reports = []
        for _ in range(50):  # detached reports can land a moment after mpv exits
            if os.path.exists(log):
                with open(log, encoding="utf-8") as f:
                    reports = [c for c in (json.loads(line) for line in f) if c[0] == "report"]
            if len(reports) >= 2:
                break
            time.sleep(0.1)
        by_path = {c[1]: c for c in reports}
        self.assertEqual(sorted(by_path), [f"--path={first}", f"--path={second}"])
        self.assertIn("--keep-last", by_path[f"--path={first}"])      # end-file "stop": it was replaced
        self.assertNotIn("--keep-last", by_path[f"--path={second}"])  # end-file "quit": still the last one


if __name__ == "__main__":
    unittest.main()
