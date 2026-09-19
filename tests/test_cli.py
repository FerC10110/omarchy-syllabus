import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from support import PLUGIN, TempHome, install_fake_ffprobe, make_tree
from syllabus import cli, paths, store
from test_readily import install_fake_readily

BIN = os.path.join(PLUGIN, "bin", "syllabus")


def run_cli(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None), err.getvalue()


class CliCase(TempHome):
    def setUp(self):
        super().setUp()
        install_fake_ffprobe(self.tmp)
        self.root = os.path.join(self.tmp, "cursos")
        make_tree(self.root, {"A/1_a.mp4": 600, "A/2_b.mp4": 1200, "A/slides.pdf": "pdf", "A/cover.png": "img",
                              "S/B/1_x.mp4": 900, "S/C/1_y.mp4": 900, "S/C/2_y.mp4": "broken", "A.webp": "img"})
        store.write_json(paths.config_path(), {"roots": [{"id": "main", "path": self.root}]})

    def ok(self, *argv, stdin=""):
        code, data, err = run_cli(*argv, stdin=stdin)
        self.assertEqual(code, 0, err)
        return data

    def fails(self, code, *argv, stdin=""):
        got, data, err = run_cli(*argv, stdin=stdin)
        self.assertEqual(got, code, err)
        self.assertEqual(data["code"], code)
        self.assertTrue(err.startswith("syllabus: "), err)
        return data

    def lesson_path(self, rel):
        return os.path.join(self.root, rel)


class Read(CliCase):
    def test_view_creates_the_watched_files(self):
        built = self.ok("view")
        self.assertTrue(os.path.exists(paths.state_path()))
        self.assertTrue(os.path.exists(paths.library_path()))
        self.assertEqual(built["courses"], [])

    def test_scan(self):
        summary = self.ok("scan")
        self.assertEqual((summary["courses"], summary["lessons"], summary["probed"], summary["moved"]), (3, 5, 5, 0))
        self.assertEqual(summary["hours"], round(3600 / 3600, 1))
        self.assertEqual([e["id"] for e in summary["errors"]], ["main:S/C/2_y.mp4"])
        self.assertEqual(self.ok("scan")["probed"], 0)
        self.assertEqual(self.ok("scan", "--force")["probed"], 5)
        built = self.ok("view")
        self.assertEqual(len(built["courses"]), 3)
        course = next(c for c in built["courses"] if c["id"] == "main:A")
        self.assertTrue(course["cover"].startswith(paths.covers_dir()))

    def test_scan_follows_a_moved_video(self):
        self.ok("scan")
        with store.transaction() as docs:
            docs.state["lessons"]["main:A/1_a.mp4"] = {"pos": 100.0, "duration": 600.0, "seq": 1}
        os.rename(self.lesson_path("A/1_a.mp4"), self.lesson_path("A/01_a.mp4"))
        self.assertEqual(self.ok("scan")["moved"], 1)
        self.assertEqual(store.load_state()["lessons"]["main:A/01_a.mp4"]["pos"], 100.0)

    def test_summary(self):
        self.ok("scan")
        self.assertIn("Nothing in progress", self.ok("summary")["text"])
        self.ok("report", f"--path={self.lesson_path('A/2_b.mp4')}", "--pos=120", "--duration=1200",
                "--played=700", "--seq=1")
        summary = self.ok("summary")
        self.assertEqual(summary["text"], "Continue: A · b · 2:00 / 20:00\nToday 12 min · Streak 1 day")
        self.assertEqual(summary["continue"]["lessonId"], "main:A/2_b.mp4")

    def test_files_covers_and_notes(self):
        self.ok("scan")
        files = self.ok("files", "main:A")
        self.assertEqual([f["name"] for f in files["files"]], ["slides.pdf"])
        self.assertEqual(files["files"][0]["path"], self.lesson_path("A/slides.pdf"))
        images = self.ok("covers", "main:A")["images"]
        self.assertEqual([(i["name"], i["where"]) for i in images], [("cover.png", "course"), ("A.webp", "root")])
        self.assertEqual(self.ok("note-get", "main:A")["text"], "")
        self.ok("apply", stdin=json.dumps({"op": "note.set", "courseId": "main:A", "text": "hi"}) + "\n")
        self.assertEqual(self.ok("note-get", "main:A")["text"], "hi\n")
        self.fails(3, "files", "main:nope")

    def test_readily_items(self):
        self.ok("scan")
        install_fake_readily(self.tmp)
        items = self.ok("readily-items", "course", "main:A")
        self.assertEqual((items["tag"], len(items["items"])), ("cursos/a", 2))
        self.ok("apply", stdin=json.dumps({"op": "config.set", "key": "readily.enabled", "value": False}))
        self.assertEqual(self.ok("readily-items", "course", "main:A"),
                         {"tag": "", "items": [], "warning": "Readily integration is off"})

    def test_config_and_usage(self):
        self.assertEqual(self.ok("config")["roots"], [{"id": "main", "path": self.root}])
        self.fails(2, "nope")
        self.fails(2, "play")


class Apply(CliCase):
    def test_apply_returns_the_new_view(self):
        self.ok("scan")
        data = self.ok("apply", stdin=json.dumps({"op": "roadmap.add", "title": "AI"}) + "\n")
        self.assertEqual(data["view"]["roadmaps"][0]["title"], "AI")
        self.assertEqual(data["result"], {"id": data["view"]["roadmaps"][0]["id"]})

    def test_folder_layout_rescans(self):
        self.ok("scan")
        data = self.ok("apply", stdin=json.dumps({"op": "folder.layout", "folderId": "main:S", "layout": "course"}))
        self.assertIn("main:S", [c["id"] for c in data["view"]["courses"]])
        self.assertEqual(data["result"]["scan"]["courses"], 2)

    def test_bad_input(self):
        self.fails(2, "apply", stdin="not json\n")
        self.fails(2, "apply", stdin="[1]\n")
        self.fails(3, "apply", stdin=json.dumps({"op": "course.set", "courseId": "main:nope", "title": "x"}))

    def test_note_changed_outside_is_marked(self):
        self.ok("scan")
        self.ok("apply", stdin=json.dumps({"op": "note.set", "courseId": "main:A", "text": "hi"}))
        with open(paths.note_path("main:A"), "w", encoding="utf-8") as f:
            f.write("hi from the editor\n")
        data = self.fails(2, "apply", stdin=json.dumps({"op": "note.set", "courseId": "main:A", "text": "hi!",
                                                        "base": "hi"}))
        self.assertEqual(data["reason"], "noteChanged")
        self.assertTrue(data["error"].startswith("The note changed outside the window"))
        self.assertEqual(self.ok("note-get", "main:A")["text"], "hi from the editor\n")
        # Other errors carry no reason.
        self.assertNotIn("reason", self.fails(3, "note-get", "main:nope"))


class Play(CliCase):
    def setUp(self):
        super().setUp()
        self.ok("scan")
        patcher = mock.patch("syllabus.player.play", return_value="started")
        self.play = patcher.start()
        self.addCleanup(patcher.stop)

    def test_play_resumes_a_little_before(self):
        with store.transaction() as docs:
            docs.state["lessons"]["main:A/2_b.mp4"] = {"pos": 100.0, "duration": 1200.0}
        data = self.ok("play", "main:A/2_b.mp4")
        self.assertEqual((data["start"], data["mode"], data["courseId"]), (95.0, "started", "main:A"))
        _, path, start = self.play.call_args.args
        self.assertEqual((path, start), (self.lesson_path("A/2_b.mp4"), 95.0))
        self.assertEqual(store.load_state()["last"]["lessonId"], "main:A/2_b.mp4")
        self.assertEqual(self.ok("play", "main:A/2_b.mp4", "--at", "12")["start"], 12.0)

    def test_play_errors(self):
        self.fails(3, "play", "main:A/zz.mp4")
        os.unlink(self.lesson_path("A/1_a.mp4"))
        self.fails(4, "play", "main:A/1_a.mp4")
        store.write_json(paths.config_path(), {"roots": [{"id": "main", "path": os.path.join(self.tmp, "gone")}]})
        self.assertIn("not mounted", self.fails(4, "play", "main:A/2_b.mp4")["error"])

    def test_resume(self):
        self.assertEqual(self.fails(3, "resume")["error"], "Nothing left to watch")
        with mock.patch("syllabus.cli.notify") as notify:
            self.fails(3, "resume", "--notify")
        notify.assert_called_once_with("Nothing left to watch")
        self.assertEqual(self.ok("resume", "main:A")["lessonId"], "main:A/1_a.mp4")
        self.ok("report", f"--path={self.lesson_path('A/1_a.mp4')}", "--pos=600", "--duration=600",
                "--played=10", "--seq=1", "--eof")
        self.assertEqual(self.ok("resume")["lessonId"], "main:A/2_b.mp4")
        self.fails(3, "resume", "main:nope")

    def test_resume_notifies_on_unexpected_errors(self):
        with mock.patch("syllabus.cli.resume", side_effect=KeyError("boom")), \
                mock.patch("syllabus.cli.notify") as notify:
            data = self.fails(1, "resume", "--notify")
        self.assertEqual(data["error"], "KeyError: 'boom'")
        notify.assert_called_once_with("Syllabus: unexpected error: KeyError: 'boom'")


class Report(CliCase):
    def setUp(self):
        super().setUp()
        self.ok("scan")

    def report(self, rel, *extra, seq=1, pos=590):
        return self.ok("report", f"--path={self.lesson_path(rel)}", f"--pos={pos}", "--duration=600",
                       "--played=30", f"--seq={seq}", *extra)

    def test_report(self):
        self.assertEqual(self.report("A/1_a.mp4"), {"lessonId": "main:A/1_a.mp4", "applied": True})
        state = store.load_state()
        self.assertTrue(state["lessons"]["main:A/1_a.mp4"]["seen"])
        self.assertEqual(state["days"][store.local_day()], {"main:A": 30})
        self.assertEqual(self.report("A/1_a.mp4", seq=1, pos=10)["applied"], False)

    def test_keep_last(self):
        # mpv replaced A/1 with A/2 (`play` set last to A/2), then A/1's end-file report arrives.
        self.report("A/2_b.mp4", pos=10)
        self.assertTrue(self.report("A/1_a.mp4", "--keep-last", seq=2, pos=200)["applied"])
        state = store.load_state()
        self.assertEqual(state["last"]["lessonId"], "main:A/2_b.mp4")
        self.assertEqual(state["lessons"]["main:A/1_a.mp4"]["pos"], 200.0)
        self.assertEqual(state["days"][store.local_day()], {"main:A": 60})

    def test_outside_the_roots(self):
        self.assertEqual(self.ok("report", "--path=/elsewhere/x.mp4", "--pos=1", "--duration=2", "--played=1",
                                 "--seq=1"), {"ignored": True})

    def test_bookmarks(self):
        path = self.lesson_path("A/1_a.mp4")
        mark = self.ok("bookmark-here", f"--path={path}", "--at=83.5", "--text=-chunking")["bookmark"]
        self.assertEqual((mark["at"], mark["text"]), (83.5, "-chunking"))
        marks = self.ok("bookmarks", f"--path={path}")
        self.assertEqual((marks["lessonId"], [m["text"] for m in marks["bookmarks"]]), ("main:A/1_a.mp4", ["-chunking"]))
        self.assertEqual(self.ok("bookmarks", "--path=/elsewhere/x.mp4"), {"lessonId": None, "bookmarks": []})
        self.fails(3, "bookmark-here", "--path=/elsewhere/x.mp4", "--at=1", "--text=x")
        self.fails(2, "bookmark-here", f"--path={path}", "--text=x")

    def test_bookmark_here_asks_mpv(self):
        self.fails(5, "bookmark-here", "--text=x")
        with mock.patch("syllabus.player.current", return_value=(self.lesson_path("A/2_b.mp4"), 42.0)):
            mark = self.ok("bookmark-here", "--text=here")["bookmark"]
        self.assertEqual(mark["at"], 42.0)


class Launcher(TempHome):
    def test_bin_runs_and_leaves_no_bytecode(self):
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        result = subprocess.run([sys.executable, BIN, "config"], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("roots", json.loads(result.stdout))
        caches = [d for d, _, _ in os.walk(PLUGIN) if os.path.basename(d) == "__pycache__"]
        self.assertEqual(caches, [])


if __name__ == "__main__":
    unittest.main()
