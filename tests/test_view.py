import datetime
import os
import unittest

from support import TempHome
from syllabus import paths, store, view


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


if __name__ == "__main__":
    unittest.main()
