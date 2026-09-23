import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from support import (PLUGIN, TempHome, install_fake_ffprobe, install_fake_ytdlp, make_tree, ytdlp_answer,
                     ytdlp_calls)
from syllabus import cli, paths, store
from syllabus.errors import OFFLINE, UNKNOWN, SyllabusError
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


class WebPlayback(TempHome):
    def setUp(self):
        super().setUp()
        self.config = store.load_config()
        self.lesson = {"id": "web:7f3a21/youtube:aaa", "title": "One", "name": "One", "number": None, "group": "",
                       "relpath": "", "url": "https://www.youtube.com/watch?v=aaa", "site": "youtube",
                       "videoId": "aaa", "available": True, "source": "playlist", "duration": 600.0}
        self.cache = {"version": 1, "files": {}, "roots": {"web": {
            "courses": [{"id": "web:7f3a21", "rootId": "web", "relpath": "", "folderId": "", "title": "Curso",
                         "topic": "", "lessons": [self.lesson], "docs": [], "images": [], "autoCover": "",
                         "coverPath": "", "sourceUrl": "https://p", "sourceKind": "playlist"}],
            "images": [], "folders": {}, "sources": {}, "fetchedAt": ""}}}
        self.state = store.empty_state()

    def test_a_link_is_what_mpv_gets(self):
        target, course, kind = cli.media_path(self.config, self.cache, self.state, self.lesson["id"])
        self.assertEqual(target, "https://www.youtube.com/watch?v=aaa")
        self.assertEqual(course["id"], "web:7f3a21")
        self.assertEqual(kind, "link")

    def test_a_downloaded_file_wins_over_the_link(self):
        path = os.path.join(self.tmp, "one.mkv")
        open(path, "w").close()
        self.state["downloads"] = {self.lesson["id"]: {"path": path, "size": 1, "at": ""}}
        target, _course, kind = cli.media_path(self.config, self.cache, self.state, self.lesson["id"])
        self.assertEqual((target, kind), (path, "file"))

    def test_a_download_that_is_gone_falls_back_to_the_link(self):
        self.state["downloads"] = {self.lesson["id"]: {"path": os.path.join(self.tmp, "nope.mkv"), "size": 1,
                                                       "at": ""}}
        target, _course, kind = cli.media_path(self.config, self.cache, self.state, self.lesson["id"])
        self.assertEqual((target, kind), ("https://www.youtube.com/watch?v=aaa", "link"))

    def test_a_video_that_is_gone_cannot_be_played(self):
        self.lesson["available"] = False
        with self.assertRaises(SyllabusError) as caught:
            cli.media_path(self.config, self.cache, self.state, self.lesson["id"])
        self.assertIn("not available any more", str(caught.exception))

    def test_a_gone_video_that_was_downloaded_still_plays(self):
        # Downloading a course is precisely what should survive the uploader taking a
        # video down: a registered file that still exists must win over "available".
        self.lesson["available"] = False
        path = os.path.join(self.tmp, "one.mkv")
        open(path, "w").close()
        self.state["downloads"] = {self.lesson["id"]: {"path": path, "size": 1, "at": ""}}
        target, _course, kind = cli.media_path(self.config, self.cache, self.state, self.lesson["id"])
        self.assertEqual((target, kind), (path, "file"))

    def test_a_report_finds_its_lesson_by_link_or_by_downloaded_file(self):
        self.assertEqual(cli.lesson_for_path(self.config, "https://www.youtube.com/watch?v=aaa", self.cache,
                                             self.state), self.lesson["id"])
        path = os.path.join(self.tmp, "one.mkv")
        self.state["downloads"] = {self.lesson["id"]: {"path": path, "size": 1, "at": ""}}
        self.assertEqual(cli.lesson_for_path(self.config, path, self.cache, self.state), self.lesson["id"])
        self.assertIsNone(cli.lesson_for_path(self.config, "https://vimeo.com/999", self.cache, self.state))

    def test_a_downloaded_file_inside_a_root_resolves_to_its_web_lesson_not_the_root(self):
        # web.downloadFolder can sit inside a scanned root (the scan skips it on purpose);
        # state["downloads"] must be checked before the root prefixes, or the file resolves
        # to a phantom "main:Downloads/..." lesson that owns no progress and no study time.
        root = os.path.join(self.tmp, "cursos")
        os.makedirs(os.path.join(root, "Downloads"), exist_ok=True)
        self.config["roots"] = [{"id": "main", "path": root}]
        path = os.path.join(root, "Downloads", "one.mkv")
        open(path, "w").close()
        self.state["downloads"] = {self.lesson["id"]: {"path": path, "size": 1, "at": ""}}
        self.assertEqual(cli.lesson_for_path(self.config, path, self.cache, self.state), self.lesson["id"])


def web_lesson(course_id, video_id, title, source="playlist"):
    return {"id": f"{course_id}/youtube:{video_id}", "title": title, "name": title, "number": None, "group": "",
            "relpath": "", "url": f"https://www.youtube.com/watch?v={video_id}", "site": "youtube",
            "videoId": video_id, "available": True, "source": source, "duration": 600.0}


class Downloads(TempHome):
    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)
        self.folder = os.path.join(self.tmp, "Downloads")
        store.write_json(paths.config_path(), {"roots": [], "web": {"downloadFolder": self.folder}})
        self.course_id = "web:7f3a21"
        self.lessons = [web_lesson(self.course_id, "aaa", "Uno"), web_lesson(self.course_id, "bbb", "Dos")]
        cache = {"version": 1, "files": {}, "roots": {"web": {
            "courses": [{"id": self.course_id, "rootId": "web", "relpath": "", "folderId": "",
                         "title": "Curso web", "topic": "", "lessons": self.lessons, "docs": [], "images": [],
                         "autoCover": "", "coverPath": "", "sourceUrl": "https://p", "sourceKind": "playlist"}],
            "images": [], "folders": {}, "sources": {}, "fetchedAt": ""}}}
        store.save_scan(cache)
        library = store.empty_library()
        library["web"] = {self.course_id: {"sources": [{"kind": "playlist", "url": "https://p"}], "addedAt": ""}}
        store.save_library(library)
        for lesson in self.lessons:
            ytdlp_answer(self.answers, lesson["url"], {"__file__": "video", "__ext__": "mkv"})

    def ok(self, *argv, stdin=""):
        code, data, err = run_cli(*argv, stdin=stdin)
        self.assertEqual(code, 0, err)
        return data

    def test_download_run_downloads_and_registers_every_file(self):
        summary = self.ok("download", self.course_id, "--run")
        self.assertEqual((summary["total"], summary["done"], summary["failed"]), (2, 2, []))
        registry = store.load_state()["downloads"]
        self.assertEqual(sorted(registry), sorted(l["id"] for l in self.lessons))
        for record in registry.values():
            self.assertTrue(os.path.isfile(record["path"]))

    def test_stop_on_a_course_that_is_not_downloading_returns_false_instead_of_raising(self):
        self.assertEqual(self.ok("download", self.course_id, "--stop"),
                         {"courseId": self.course_id, "stopped": False})

    def test_downloads_delete_removes_the_files_and_reports_totals(self):
        self.ok("download", self.course_id, "--run")
        result = self.ok("downloads-delete", self.course_id)
        self.assertEqual(result["removed"], 2)
        self.assertGreater(result["freed"], 0)
        self.assertEqual(store.load_state()["downloads"], {})

    def test_downloads_delete_of_an_unknown_course_comes_back_as_data(self):
        code, data, err = run_cli("downloads-delete", "web:nope")
        self.assertEqual(code, 3)
        self.assertEqual(data, {"error": "Unknown course", "code": 3})

    def test_downloads_delete_stops_a_running_download_first(self):
        # A real, owned process stands in for the worker; _is_worker is stubbed because its
        # cmdline does not literally name this course. If the files were deleted while it kept
        # running, it would write straight into a folder downloads-delete just emptied.
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            store.write_json(paths.download_path(self.course_id),
                             {"courseId": self.course_id, "pid": worker.pid, "total": 1, "done": 0,
                              "current": "", "failed": []})
            with mock.patch.object(cli.downloads, "_is_worker", return_value=True):
                self.ok("downloads-delete", self.course_id)
            worker.wait(timeout=5)
            self.assertIsNotNone(worker.poll())
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=5)


class WebCommands(TempHome):
    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)
        store.write_json(paths.config_path(), {"roots": []})
        self.playlist_url = "https://www.youtube.com/playlist?list=PLfake"
        ytdlp_answer(self.answers, self.playlist_url, {
            "_type": "playlist", "title": "Curso web", "id": "PLfake",
            "entries": [{"id": "aaa", "ie_key": "Youtube", "title": "Uno", "duration": 600},
                        {"id": "bbb", "ie_key": "Youtube", "title": "Dos", "duration": 900}]})

    def run_cli(self, argv):
        """The command's JSON on success; a command that fails raises SyllabusError, the way
        every other caller of ops/web/scan in this suite asserts on errors."""
        code, data, err = run_cli(*argv)
        if code != 0:
            raise SyllabusError((data or {}).get("error", err), code)
        return data

    def test_web_add_creates_the_course_and_scans_it_once(self):
        out = self.run_cli(["web-add", self.playlist_url, "--title", "Mi curso", "--topic", "IA"])
        course_id = out["courseId"]
        self.assertTrue(course_id.startswith("web:"))
        self.assertEqual(out["videos"], 2)
        library = store.load_library()
        self.assertEqual(library["web"][course_id]["sources"],
                         [{"kind": "playlist", "url": self.playlist_url}])
        self.assertEqual(library["courses"][course_id]["title"], "Mi curso")
        self.assertEqual(library["courses"][course_id]["topic"], "IA")
        cache = store.load_scan()
        self.assertEqual(len(cache["roots"]["web"]["courses"][0]["lessons"]), 2)
        # La playlist se lee una sola vez: el escaneo reusa la respuesta de web-add.
        self.assertEqual([c[-1] for c in ytdlp_calls(self.answers)].count(self.playlist_url), 1)

    def test_a_loose_video_can_join_an_existing_course(self):
        course_id = self.run_cli(["web-add", self.playlist_url])["courseId"]
        video = "https://vimeo.com/111"
        ytdlp_answer(self.answers, video, {"id": "111", "ie_key": "Vimeo", "title": "Extra", "duration": 120})
        self.run_cli(["web-add", video, "--course", course_id, "--password", "pass"])
        sources = store.load_library()["web"][course_id]["sources"]
        self.assertEqual(sources[1], {"kind": "video", "url": video, "password": "pass"})
        lessons = store.load_scan()["roots"]["web"]["courses"][0]["lessons"]
        self.assertEqual(lessons[-1]["title"], "Extra")
        self.assertEqual(lessons[-1]["source"], "video")

    def test_a_link_that_cannot_be_read_changes_nothing(self):
        # Errors-as-data is a binding invariant of this CLI: asserted here on the raw
        # (code, data, err) triple, the way CliCase.fails() does, not through self.run_cli's
        # convenience re-raise — so a SyllabusError escaping cli.main() uncaught would show up
        # as a test failure (a bare traceback), not a false pass.
        dead = "https://www.youtube.com/playlist?list=PLdead"
        ytdlp_answer(self.answers, dead, {"__error__": "ERROR: [youtube] PLdead: Unable to download webpage"})
        code, data, err = run_cli("web-add", dead)
        self.assertEqual(code, OFFLINE)
        self.assertEqual(data, {"error": "[youtube] PLdead: Unable to download webpage", "code": OFFLINE})
        self.assertTrue(err.startswith("syllabus: "), err)
        self.assertEqual(store.load_library()["web"], {})

    def test_web_refresh_reads_the_course_again(self):
        course_id = self.run_cli(["web-add", self.playlist_url])["courseId"]
        before = len(ytdlp_calls(self.answers))
        self.run_cli(["web-refresh", course_id])
        self.assertGreater(len(ytdlp_calls(self.answers)), before)
        # Same as above: the unknown-course failure is asserted as data, not via assertRaises.
        code, data, err = run_cli("web-refresh", "web:nope")
        self.assertEqual(code, UNKNOWN)
        self.assertEqual(data, {"error": "Unknown web course", "code": UNKNOWN})
        self.assertTrue(err.startswith("syllabus: "), err)

    def test_a_failed_add_never_prints_the_password(self):
        dead = "https://vimeo.com/000"
        password = "abre,sésamo"
        ytdlp_answer(self.answers, dead, {"__error__": "ERROR: [vimeo] 000: Unable to download webpage"})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("")), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = cli.main(["web-add", dead, "--password", password])
        self.assertNotEqual(code, 0)
        self.assertNotIn(password, out.getvalue())
        self.assertNotIn(password, err.getvalue())


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
