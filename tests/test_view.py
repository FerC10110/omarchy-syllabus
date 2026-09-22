import datetime
import os
import unittest
from unittest import mock

from support import TempHome
from syllabus import downloads, paths, store, view


def lesson(course_rel, name, title, group=""):
    rel = f"{course_rel}/{name}"
    return {"id": f"main:{rel}", "relpath": rel, "name": name, "group": group, "size": 10, "mtimeNs": 1,
            "title": title, "number": None}


class Build(TempHome):
    def setUp(self):
        super().setUp()
        self.config = store.load_config()
        self.config["roots"] = [{"id": "main", "path": self.tmp}]
        course_a = {"id": "main:A", "rootId": "main", "relpath": "A", "folderId": "main:A", "title": "A course",
                    "topic": "", "autoCover": "", "images": [],
                    "lessons": [lesson("A", "1.mp4", "One"), lesson("A", "2.mp4", "Two"),
                                lesson("A", "3.mp4", "Tiny"), lesson("A", "g/4.mp4", "Four", group="g")],
                    "docs": [{"relpath": "A/s.pdf", "name": "s.pdf", "size": 3, "ext": "pdf"}]}
        course_b = {"id": "main:S/B", "rootId": "main", "relpath": "S/B", "folderId": "main:S", "title": "B",
                    "topic": "S", "autoCover": "", "images": [], "docs": [],
                    "lessons": [lesson("S/B", "1.mp4", "Bee")]}
        self.cache = {"version": 1, "roots": {"main": {
            "path": self.tmp, "scannedAt": "2026-09-19T10:00:00+00:00", "courses": [course_a, course_b],
            "images": [], "folders": {"main:A": "course", "main:S": "collection"}}},
            "files": {"main:A/1.mp4": {"duration": 1000.0}, "main:A/2.mp4": {"duration": 2000.0},
                      "main:A/3.mp4": {"duration": 5.0}, "main:A/g/4.mp4": {"duration": 0.0, "error": "bad"},
                      "main:S/B/1.mp4": {"duration": 600.0}}}
        self.library = store.empty_library()
        self.state = store.empty_state()

    def build(self, moment=None):
        return view.build_view(self.config, self.library, self.state, self.cache, moment)

    def course(self, built, course_id):
        return next(c for c in built["courses"] if c["id"] == course_id)

    def test_courses_roots_and_folders(self):
        built = self.build()
        self.assertEqual([c["id"] for c in built["courses"]], ["main:S/B", "main:A"])
        self.assertEqual(built["topics"], ["S"])
        self.assertEqual(built["roots"], [{"id": "main", "path": self.tmp, "online": True,
                                           "scannedAt": "2026-09-19T10:00:00+00:00", "courseCount": 2}])
        self.assertEqual(built["folders"], {"main:A": {"layout": "auto", "detected": "course"},
                                            "main:S": {"layout": "auto", "detected": "collection"}})
        self.assertEqual(built["paths"]["state"], paths.state_path())
        self.assertEqual(built["paths"]["library"], paths.library_path())

    def test_suspect_and_broken_videos_are_hidden_and_not_counted(self):
        course = self.course(self.build(), "main:A")
        self.assertEqual({l["id"]: l["hidden"] for l in course["lessons"]},
                         {"main:A/1.mp4": False, "main:A/2.mp4": False, "main:A/3.mp4": True, "main:A/g/4.mp4": True})
        self.assertEqual((course["lessonCount"], course["duration"], course["docCount"]), (2, 3000.0, 1))

    def test_progress_totals(self):
        self.state["lessons"]["main:A/1.mp4"] = {"pos": 1000.0, "duration": 1000.0, "seen": True}
        self.state["lessons"]["main:A/2.mp4"] = {"pos": 500.0, "duration": 2000.0, "seen": False}
        course = self.course(self.build(), "main:A")
        self.assertEqual((course["seenCount"], course["watched"], course["remaining"], course["percent"]),
                         (1, 1500.0, 1500.0, 50.0))

    def test_overrides(self):
        self.library["courses"]["main:A"] = {
            "title": "Renamed", "topic": "RAG", "order": ["main:A/2.mp4"],
            "tasks": [{"id": "t", "text": "Do", "done": True, "doneAt": None}, "junk"],
            "links": [{"id": "l", "kind": "link", "title": "", "url": "https://x"}, {"id": "bad", "kind": "link"}]}
        self.library["lessons"]["main:A/3.mp4"] = {"hidden": False, "title": "Short", "bookmarks": [
            {"id": "b2", "at": 50, "text": "z"}, {"id": "b1", "at": 10, "text": "a"}, {"id": "b0", "at": "x"}]}
        course = self.course(self.build(), "main:A")
        self.assertEqual((course["title"], course["defaultTitle"], course["topic"]), ("Renamed", "A course", "RAG"))
        self.assertEqual([l["id"] for l in course["lessons"]],
                         ["main:A/2.mp4", "main:A/1.mp4", "main:A/3.mp4", "main:A/g/4.mp4"])
        tiny = course["lessons"][2]
        self.assertEqual((tiny["title"], tiny["defaultTitle"], tiny["hidden"], tiny["suspect"]),
                         ("Short", "Tiny", False, True))
        self.assertEqual([b["id"] for b in tiny["bookmarks"]], ["b1", "b2"])
        self.assertEqual((course["taskCount"], course["taskDone"], [l["id"] for l in course["links"]]), (1, 1, ["l"]))

    def test_an_empty_stored_topic_is_the_default(self):
        # Saved by an earlier version, which stored "" instead of removing the key.
        self.library["courses"]["main:S/B"] = {"topic": ""}
        self.assertEqual(self.course(self.build(), "main:S/B")["topic"], "S")

    def test_continue_and_today(self):
        moment = datetime.datetime(2026, 9, 19, 15, 0, tzinfo=datetime.timezone.utc)
        self.state["lessons"]["main:A/2.mp4"] = {"pos": 500.0, "duration": 2000.0, "seen": False,
                                                 "updatedAt": "2026-09-19T10:00:00+00:00"}
        self.state["last"] = {"lessonId": "main:A/2.mp4", "at": "x"}
        self.state["days"] = {store.local_day(moment): {"main:A": 1200}}
        built = self.build(moment)
        self.assertEqual(built["continue"], {"lessonId": "main:A/2.mp4", "courseId": "main:A", "title": "Two",
                                             "courseTitle": "A course", "pos": 500.0, "duration": 2000.0,
                                             "seen": False, "online": True})
        self.assertEqual((built["today"]["seconds"], built["today"]["streak"]), (1200, 1))

    def test_no_continue_without_history(self):
        self.assertIsNone(self.build()["continue"])

    def test_continue_follows_the_roadmap(self):
        self.library["roadmaps"] = [{"id": "r", "title": "AI", "stages": [
            {"id": "s", "title": "One", "courseIds": ["main:S/B", "main:A"]}]}]
        self.assertEqual(self.build()["continue"]["lessonId"], "main:S/B/1.mp4")
        # The first course is done: the roadmap moves on to the next one.
        self.state["lessons"]["main:S/B/1.mp4"] = {"pos": 600.0, "duration": 600.0, "seen": True,
                                                   "updatedAt": "2026-09-19T10:00:00+00:00"}
        self.state["last"] = {"lessonId": "main:S/B/1.mp4", "at": "x"}
        self.assertEqual(self.build()["continue"]["lessonId"], "main:A/1.mp4")

    def test_panel_size_and_pin(self):
        self.assertEqual(self.build()["window"], {"width": 1100, "height": 720, "pinned": False})
        self.state["window"] = {"width": 1400, "pinned": True}
        self.assertEqual(self.build()["window"], {"width": 1400, "height": 720, "pinned": True})

    def test_offline_root(self):
        self.config["roots"] = [{"id": "main", "path": os.path.join(self.tmp, "gone")}]
        built = self.build()
        self.assertFalse(built["roots"][0]["online"])
        self.assertEqual(len(built["courses"]), 2)
        self.assertFalse(any(c["online"] for c in built["courses"]))

    def test_roadmap_stats(self):
        self.state["lessons"]["main:S/B/1.mp4"] = {"pos": 300.0, "duration": 600.0}
        self.library["roadmaps"] = [{"id": "r", "title": "AI", "tasks": [], "links": [], "stages": [
            {"id": "s1", "title": "One", "courseIds": ["main:S/B", "main:gone"],
             "tasks": [{"id": "t", "text": "x", "done": False}]},
            {"id": "s2", "title": "Two", "courseIds": ["main:A", "main:S/B"], "tasks": []}]}]
        roadmap = self.build()["roadmaps"][0]
        first = roadmap["stages"][0]
        self.assertEqual((first["courseIds"], first["missing"], first["percent"], first["taskCount"]),
                         (["main:S/B"], 1, 50.0, 1))
        self.assertEqual((roadmap["courseCount"], roadmap["duration"], roadmap["watched"]), (2, 3600.0, 300.0))

    def test_cover(self):
        cover = os.path.join(self.tmp, "c.webp")
        with open(cover, "w") as f:
            f.write("x")
        self.library["courses"]["main:A"] = {"cover": cover}
        self.assertEqual(self.course(self.build(), "main:A")["cover"], cover)
        self.library["courses"]["main:A"] = {"cover": os.path.join(self.tmp, "missing.webp")}
        self.assertEqual(self.course(self.build(), "main:A")["cover"], "")

    def test_formatters(self):
        self.assertEqual(view.fmt_clock(5020.7), "1:23:40")
        self.assertEqual(view.fmt_clock(65), "1:05")
        self.assertEqual(view.fmt_study(4800), "1h20")
        self.assertEqual(view.fmt_study(1500), "25 min")


def web_lesson(course_id, video_id, title, duration, available=True, source="playlist"):
    return {"id": f"{course_id}/youtube:{video_id}", "title": title, "name": title, "number": None, "group": "",
            "relpath": "", "url": f"https://www.youtube.com/watch?v={video_id}", "site": "youtube",
            "videoId": video_id, "available": available, "source": source, "duration": duration}


class WebCourses(TempHome):
    def setUp(self):
        super().setUp()
        self.config = store.load_config()
        self.config["roots"] = []
        lessons = [web_lesson("web:7f3a21", "aaa", "One", 600.0),
                   web_lesson("web:7f3a21", "bbb", "Two", 1200.0),
                   web_lesson("web:7f3a21", "ccc", "Gone", 300.0, available=False)]
        self.cache = {"version": 1, "roots": {"web": {
            "courses": [{"id": "web:7f3a21", "rootId": "web", "relpath": "", "folderId": "",
                         "title": "Deep Learning", "topic": "", "lessons": lessons, "docs": [], "images": [],
                         "autoCover": "", "coverPath": "", "sourceUrl": "https://www.youtube.com/playlist?list=PL",
                         "sourceKind": "playlist"}],
            "images": [], "folders": {}, "fetchedAt": "2026-09-22T10:00:00+00:00",
            "sources": {"web:7f3a21": {"fetchedAt": "2026-09-22T10:00:00+00:00", "error": ""}}}},
            "files": {"web:7f3a21/youtube:aaa": {"duration": 600.0},
                      "web:7f3a21/youtube:bbb": {"duration": 1200.0},
                      "web:7f3a21/youtube:ccc": {"duration": 300.0}}}
        self.library = store.empty_library()
        self.library["web"] = {"web:7f3a21": {"sources": [{"kind": "playlist",
                                                           "url": "https://www.youtube.com/playlist?list=PL"}],
                                              "addedAt": "2026-09-19T12:00:00+00:00"}}
        self.state = store.empty_state()

    def build(self):
        return view.build_view(self.config, self.library, self.state, self.cache)

    def test_the_web_root_is_always_online(self):
        root = next(r for r in self.build()["roots"] if r["id"] == "web")
        self.assertTrue(root["online"])
        self.assertEqual(root["error"], "")
        self.assertEqual(root["path"], "")
        self.assertEqual(root["scannedAt"], "2026-09-22T10:00:00+00:00")
        self.assertEqual(root["courseCount"], 1)

    def test_a_web_step_that_failed_on_the_first_scan_still_shows_its_error(self):
        self.cache["roots"]["web"] = {"courses": [], "images": [], "folders": {}, "sources": {},
                                      "fetchedAt": "", "error": "Could not read the web courses: boom"}
        root = next(r for r in self.build()["roots"] if r["id"] == "web")
        self.assertEqual(root["error"], "Could not read the web courses: boom")
        self.assertEqual(root["courseCount"], 0)
        self.assertTrue(root["online"])

    def test_the_course_says_where_it_came_from(self):
        course = self.build()["courses"][0]
        self.assertEqual(course["web"]["kind"], "playlist")
        self.assertEqual(course["web"]["url"], "https://www.youtube.com/playlist?list=PL")
        self.assertEqual(course["web"]["videoCount"], 3)
        self.assertEqual(course["web"]["goneCount"], 1)
        self.assertEqual(course["web"]["downloadedCount"], 0)
        self.assertEqual(course["web"]["sources"], [{"kind": "playlist",
                                                     "url": "https://www.youtube.com/playlist?list=PL"}])
        self.assertTrue(course["online"])

    def test_a_video_that_is_gone_stays_visible_but_out_of_the_totals(self):
        course = self.build()["courses"][0]
        self.assertEqual([l["title"] for l in course["lessons"]], ["One", "Two", "Gone"])
        self.assertFalse(course["lessons"][2]["available"])
        self.assertEqual(course["lessonCount"], 2)
        self.assertEqual(course["duration"], 1800.0)

    def test_a_gone_video_is_never_what_continue_plays(self):
        self.state["lessons"] = {"web:7f3a21/youtube:aaa": {"pos": 600.0, "seen": True, "duration": 600.0},
                                 "web:7f3a21/youtube:bbb": {"pos": 1200.0, "seen": True, "duration": 1200.0}}
        self.state["last"] = {"lessonId": "web:7f3a21/youtube:bbb"}
        self.assertIsNone(self.build()["continue"])
        self.assertNotEqual((self.build()["continue"] or {}).get("lessonId"), "web:7f3a21/youtube:ccc")

    def test_a_downloaded_video_says_so_and_adds_its_size(self):
        self.state["downloads"] = {"web:7f3a21/youtube:aaa": {"path": "/tmp/one.mkv", "size": 1024,
                                                              "at": "2026-09-22T10:00:00+00:00"}}
        course = self.build()["courses"][0]
        self.assertTrue(course["lessons"][0]["downloaded"])
        self.assertFalse(course["lessons"][1]["downloaded"])
        self.assertEqual(course["web"]["downloadedCount"], 1)
        self.assertEqual(course["web"]["downloadedBytes"], 1024)

    def test_pending_count_ignores_a_gone_lesson_even_when_it_was_downloaded(self):
        # "ccc" is gone but was downloaded before it went; "aaa" and "bbb" are still
        # available and not downloaded. downloadedCount counts every saved file, gone or
        # not, but pendingCount must only count what Download can still fetch.
        self.state["downloads"] = {"web:7f3a21/youtube:ccc": {"path": "/tmp/gone.mkv", "size": 10, "at": ""}}
        course = self.build()["courses"][0]
        self.assertEqual(course["web"]["downloadedCount"], 1)
        self.assertEqual(course["web"]["pendingCount"], 2)

    def test_pending_count_is_zero_once_every_available_video_is_downloaded(self):
        self.state["downloads"] = {
            "web:7f3a21/youtube:aaa": {"path": "/tmp/a.mkv", "size": 1, "at": ""},
            "web:7f3a21/youtube:bbb": {"path": "/tmp/b.mkv", "size": 1, "at": ""},
        }
        course = self.build()["courses"][0]
        self.assertEqual(course["web"]["pendingCount"], 0)

    def test_a_junk_download_size_counts_as_zero_instead_of_raising(self):
        self.state["downloads"] = {"web:7f3a21/youtube:aaa": {"path": "/tmp/one.mkv", "size": "oops",
                                                              "at": "2026-09-22T10:00:00+00:00"}}
        self.assertEqual(self.build()["courses"][0]["web"]["downloadedBytes"], 0)

    def test_a_running_download_shows_its_progress(self):
        course = self.build()["courses"][0]
        self.assertFalse(course["web"]["downloading"])
        store.write_json(paths.download_path("web:7f3a21"),
                         {"courseId": "web:7f3a21", "pid": 1, "total": 3, "done": 1, "current": "01 - One"})
        # The pid is made up, so the worker check has to be the one thing stubbed here.
        with mock.patch.object(downloads, "_is_worker", return_value=True):
            course = self.build()["courses"][0]
        self.assertTrue(course["web"]["downloading"])
        self.assertEqual((course["web"]["downloadDone"], course["web"]["downloadTotal"]), (1, 3))

    def test_a_download_whose_worker_is_gone_is_not_shown_as_running(self):
        store.write_json(paths.download_path("web:7f3a21"),
                         {"courseId": "web:7f3a21", "pid": os.getpid(), "total": 3, "done": 1, "current": "One"})
        course = self.build()["courses"][0]
        self.assertFalse(course["web"]["downloading"])
        self.assertFalse(os.path.exists(paths.download_path("web:7f3a21")))

    def test_a_disk_course_has_no_web_block(self):
        self.cache["roots"]["main"] = {"path": self.tmp, "scannedAt": "", "courses": [
            {"id": "main:A", "rootId": "main", "relpath": "A", "folderId": "main:A", "title": "A", "topic": "",
             "autoCover": "", "images": [], "docs": [], "lessons": []}], "images": [], "folders": {}}
        self.config["roots"] = [{"id": "main", "path": self.tmp}]
        disk = next(c for c in self.build()["courses"] if c["id"] == "main:A")
        self.assertIsNone(disk["web"])


if __name__ == "__main__":
    unittest.main()
