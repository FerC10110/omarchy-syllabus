import os
import subprocess
import sys
import unittest
from unittest import mock

from support import TempHome, install_fake_ffprobe, make_tree
from syllabus import ops, paths, probe, scan, store
from syllabus.errors import SyllabusError
from test_readily import install_fake_readily, read_calls


class OpsCase(TempHome):
    def setUp(self):
        super().setUp()
        install_fake_ffprobe(self.tmp)
        self.root = os.path.join(self.tmp, "cursos")
        make_tree(self.root, {"A/1_a.mp4": 600, "A/2_b.mp4": 600.5, "A/3_tiny.mp4": 5, "A/4_c.mp4": 601,
                              "S/B/1_x.mp4": 900, "S/C/1_y.mp4": 900, "cover.webp": "img"})
        store.write_json(paths.config_path(), {"roots": [{"id": "main", "path": self.root}]})
        self.cache = scan.scan_all(store.load_config(), {}, store.empty_scan(), probe.probe_duration)
        self.cache.pop("probed")

    def apply(self, **payload):
        with store.transaction() as docs:
            return ops.apply(docs, payload, self.cache)

    def fails(self, code, **payload):
        with self.assertRaises(SyllabusError) as caught:
            self.apply(**payload)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def library(self):
        return store.load_library()


class Window(OpsCase):
    def test_window_set(self):
        self.apply(op="window.set", width=1300, height=800)
        self.assertEqual(store.load_state()["window"], {"width": 1300, "height": 800})
        self.apply(op="window.set", pinned=True)
        self.assertEqual(store.load_state()["window"], {"width": 1300, "height": 800, "pinned": True})

    def test_window_set_errors(self):
        self.fails(2, op="window.set")
        self.fails(2, op="window.set", width=100)
        self.fails(2, op="window.set", height="big")
        self.fails(2, op="window.set", pinned="yes")


class Courses(OpsCase):
    def test_course_set(self):
        self.apply(op="course.set", courseId="main:A", title="Alpha", topic="RAG", readilyTag="#Cursos/Alpha Beta")
        self.assertEqual(self.library()["courses"]["main:A"],
                         {"title": "Alpha", "topic": "RAG", "readilyTag": "cursos/alpha-beta"})
        self.apply(op="course.set", courseId="main:A", title="", readilyTag="")
        self.assertEqual(self.library()["courses"]["main:A"], {"topic": "RAG"})

    def test_empty_topic_brings_back_the_default(self):
        from syllabus import view
        self.apply(op="course.set", courseId="main:S/B", topic="RAG")
        self.apply(op="course.set", courseId="main:S/B", topic="  ")
        self.assertNotIn("topic", self.library()["courses"]["main:S/B"])
        built = view.build_view(store.load_config(), self.library(), store.load_state(), self.cache)
        self.assertEqual(next(c for c in built["courses"] if c["id"] == "main:S/B")["topic"], "S")

    def test_errors(self):
        self.fails(3, op="course.set", courseId="main:nope", title="x")
        self.fails(2, op="course.set", courseId="main:A", readilyTag="!!!")
        self.fails(2, op="nope")

    def test_cover_set(self):
        self.apply(op="cover.set", courseId="main:A", source=os.path.join(self.root, "cover.webp"))
        cover = self.library()["courses"]["main:A"]["cover"]
        self.assertTrue(cover.startswith(paths.covers_dir()))
        self.assertTrue(os.path.isfile(cover))
        self.apply(op="cover.set", courseId="main:A", source="")
        self.assertNotIn("cover", self.library()["courses"]["main:A"])
        self.fails(2, op="cover.set", courseId="main:A", source=os.path.join(self.root, "A", "1_a.mp4"))

    def test_folder_layout(self):
        self.assertEqual(self.apply(op="folder.layout", folderId="main:S", layout="course"), {"rescan": True})
        self.assertEqual(self.library()["folders"], {"main:S": {"layout": "course"}})
        self.apply(op="folder.layout", folderId="main:S", layout="auto")
        self.assertEqual(self.library()["folders"], {})
        self.fails(2, op="folder.layout", folderId="main:S", layout="weird")
        self.fails(3, op="folder.layout", folderId="main:nope", layout="course")


class Lessons(OpsCase):
    def order(self):
        return self.library()["courses"]["main:A"]["order"]

    def test_lesson_set(self):
        self.apply(op="lesson.set", lessonId="main:A/1_a.mp4", title="Intro", hidden=True)
        self.assertEqual(self.library()["lessons"]["main:A/1_a.mp4"], {"title": "Intro", "hidden": True})
        self.apply(op="lesson.set", lessonId="main:A/1_a.mp4", title="")
        self.assertEqual(self.library()["lessons"]["main:A/1_a.mp4"], {"hidden": True})
        self.fails(2, op="lesson.set", lessonId="main:A/1_a.mp4", hidden="yes")
        self.fails(3, op="lesson.set", lessonId="main:A/zz.mp4", hidden=True)

    def test_move_skips_hidden_lessons(self):
        self.apply(op="lesson.move", courseId="main:A", lessonId="main:A/4_c.mp4", delta=-1)
        self.assertEqual(self.order(), ["main:A/1_a.mp4", "main:A/4_c.mp4", "main:A/2_b.mp4", "main:A/3_tiny.mp4"])
        self.apply(op="lesson.move", courseId="main:A", lessonId="main:A/1_a.mp4", delta=-1)
        self.assertEqual(self.order()[0], "main:A/1_a.mp4")
        self.apply(op="lesson.move", courseId="main:A", lessonId="main:A/1_a.mp4", delta=1)
        self.assertEqual(self.order()[:2], ["main:A/4_c.mp4", "main:A/1_a.mp4"])

    def test_seen_set(self):
        self.apply(op="seen.set", lessonId="main:A/1_a.mp4", seen=True)
        self.assertTrue(store.load_state()["lessons"]["main:A/1_a.mp4"]["seen"])
        self.apply(op="seen.set", lessonId="main:A/1_a.mp4", seen=False)
        entry = store.load_state()["lessons"]["main:A/1_a.mp4"]
        self.assertEqual((entry["seen"], entry["pos"]), (False, 0.0))

    def test_bookmarks(self):
        lesson = "main:A/1_a.mp4"
        mark = self.apply(op="bookmark.add", lessonId=lesson, at=83.5, text=" chunking ")["id"]
        marks = self.library()["lessons"][lesson]["bookmarks"]
        self.assertEqual((marks[0]["id"], marks[0]["at"], marks[0]["text"]), (mark, 83.5, "chunking"))
        self.apply(op="bookmark.set", lessonId=lesson, bookmarkId=mark, text="RAG", at=90)
        marks = self.library()["lessons"][lesson]["bookmarks"]
        self.assertEqual((marks[0]["at"], marks[0]["text"]), (90.0, "RAG"))
        self.apply(op="bookmark.remove", lessonId=lesson, bookmarkId=mark)
        self.assertEqual(self.library()["lessons"][lesson]["bookmarks"], [])
        self.fails(2, op="bookmark.add", lessonId=lesson, at=-1, text="x")
        self.fails(3, op="bookmark.remove", lessonId=lesson, bookmarkId="zz")


class Roadmaps(OpsCase):
    def roadmap(self):
        return self.library()["roadmaps"][0]

    def test_lifecycle(self):
        r = self.apply(op="roadmap.add", title="AI")["id"]
        s1 = self.apply(op="stage.add", roadmapId=r, title="Basics")["id"]
        s2 = self.apply(op="stage.add", roadmapId=r, title="Agents")["id"]
        for course in ("main:A", "main:S/B", "main:A"):
            self.apply(op="stage.addCourse", roadmapId=r, stageId=s1, courseId=course)
        self.apply(op="stage.moveCourse", roadmapId=r, stageId=s1, courseId="main:S/B", delta=-1)
        self.apply(op="stage.move", roadmapId=r, stageId=s2, delta=-1)
        self.apply(op="stage.set", roadmapId=r, stageId=s1, title="Foundations")
        self.assertEqual([s["title"] for s in self.roadmap()["stages"]], ["Agents", "Foundations"])
        self.assertEqual(self.roadmap()["stages"][1]["courseIds"], ["main:S/B", "main:A"])
        self.apply(op="stage.removeCourse", roadmapId=r, stageId=s1, courseId="main:A")
        self.apply(op="stage.remove", roadmapId=r, stageId=s2)
        self.apply(op="roadmap.set", roadmapId=r, title="AI Engineering")
        self.assertEqual((self.roadmap()["title"], [s["id"] for s in self.roadmap()["stages"]]), ("AI Engineering", [s1]))
        self.assertEqual(self.roadmap()["stages"][0]["courseIds"], ["main:S/B"])
        self.fails(3, op="stage.addCourse", roadmapId=r, stageId=s1, courseId="main:nope")
        self.fails(3, op="stage.removeCourse", roadmapId=r, stageId=s1, courseId="main:A")
        self.fails(2, op="stage.move", roadmapId=r, stageId=s1, delta=2)
        self.fails(2, op="roadmap.add", title="  ")
        self.apply(op="roadmap.remove", roadmapId=r)
        self.assertEqual(self.library()["roadmaps"], [])
        self.fails(3, op="roadmap.remove", roadmapId=r)

    def test_roadmap_order(self):
        a = self.apply(op="roadmap.add", title="A")["id"]
        b = self.apply(op="roadmap.add", title="B")["id"]
        self.apply(op="roadmap.move", roadmapId=b, delta=-1)
        self.assertEqual([r["id"] for r in self.library()["roadmaps"]], [b, a])


class Tasks(OpsCase):
    def tasks_of(self, owner):
        library = self.library()
        if owner["kind"] == "course":
            return library["courses"]["main:A"]["tasks"]
        if owner["kind"] == "roadmap":
            return library["roadmaps"][0]["tasks"]
        return library["roadmaps"][0]["stages"][0]["tasks"]

    def test_tasks_on_every_owner(self):
        r = self.apply(op="roadmap.add", title="AI")["id"]
        s = self.apply(op="stage.add", roadmapId=r, title="One")["id"]
        owners = [{"kind": "course", "id": "main:A"}, {"kind": "roadmap", "id": r},
                  {"kind": "stage", "roadmapId": r, "id": s}]
        for owner in owners:
            with self.subTest(owner=owner["kind"]):
                t1 = self.apply(op="task.add", owner=owner, text="Read")["id"]
                t2 = self.apply(op="task.add", owner=owner, text="Code")["id"]
                self.apply(op="task.set", owner=owner, taskId=t1, done=True)
                self.apply(op="task.move", owner=owner, taskId=t2, delta=-1)
                self.apply(op="task.set", owner=owner, taskId=t2, text="Build")
                tasks = self.tasks_of(owner)
                self.assertEqual([(t["text"], t["done"]) for t in tasks], [("Build", False), ("Read", True)])
                self.assertTrue(tasks[1]["doneAt"])
                self.apply(op="task.set", owner=owner, taskId=t1, done=False)
                self.assertIsNone(self.tasks_of(owner)[1]["doneAt"])
                self.apply(op="task.remove", owner=owner, taskId=t1)
                self.assertEqual(len(self.tasks_of(owner)), 1)

    def test_errors(self):
        self.fails(2, op="task.add", owner={"kind": "course", "id": "main:A"}, text="  ")
        self.fails(2, op="task.add", owner={"kind": "planet", "id": "x"}, text="a")
        self.fails(3, op="task.set", owner={"kind": "course", "id": "main:A"}, taskId="zz", done=True)


class Links(OpsCase):
    OWNER = {"kind": "course", "id": "main:A"}

    def links(self):
        return self.library()["courses"]["main:A"]["links"]

    def test_kind_is_detected_and_editable(self):
        a = self.apply(op="link.add", owner=self.OWNER, title="Repo", content=" https://github.com/x \n")["id"]
        b = self.apply(op="link.add", owner=self.OWNER, content="pip install x\nsecond line\n")["id"]
        first, second = self.links()
        self.assertEqual((first["kind"], first["url"], first["title"]), ("link", "https://github.com/x", "Repo"))
        self.assertEqual((second["kind"], second["text"], second["title"]), ("snippet", "pip install x\nsecond line", ""))
        self.apply(op="link.set", owner=self.OWNER, linkId=b, title="Install", content="https://pypi.org/x")
        second = self.links()[1]
        self.assertEqual((second["kind"], second["url"], second["title"]), ("link", "https://pypi.org/x", "Install"))
        self.assertNotIn("text", second)
        self.apply(op="link.move", owner=self.OWNER, linkId=b, delta=-1)
        self.assertEqual([l["id"] for l in self.links()], [b, a])
        self.apply(op="link.remove", owner=self.OWNER, linkId=a)
        self.assertEqual([l["id"] for l in self.links()], [b])

    def test_errors(self):
        r = self.apply(op="roadmap.add", title="AI")["id"]
        s = self.apply(op="stage.add", roadmapId=r, title="One")["id"]
        self.fails(2, op="link.add", owner={"kind": "stage", "roadmapId": r, "id": s}, content="x")
        self.fails(2, op="link.add", owner=self.OWNER, content="   ")
        self.fails(2, op="link.add", owner=self.OWNER, content="x", kind="video")

    def test_truncated_import(self):
        self.apply(op="link.add", owner=self.OWNER, title="Long", content="x" * 10, truncated=True)
        self.assertTrue(self.links()[0]["truncated"])

    def test_truncated_stays_until_the_content_changes(self):
        link = self.apply(op="link.add", owner=self.OWNER, title="Long", content="x" * 10 + "\n", truncated=True)["id"]
        # The window always sends the content back, even when only the title was edited.
        self.apply(op="link.set", owner=self.OWNER, linkId=link, title="Longer", content="x" * 10)
        self.assertEqual((self.links()[0]["title"], self.links()[0].get("truncated")), ("Longer", True))
        self.apply(op="link.set", owner=self.OWNER, linkId=link, title="Longer", content="x" * 10 + " more")
        self.assertNotIn("truncated", self.links()[0])

    def test_save_to_readily(self):
        log = install_fake_readily(self.tmp)
        link = self.apply(op="link.add", owner=self.OWNER, title="Repo", content="https://github.com/x")["id"]
        self.apply(op="readily.save", owner=self.OWNER, linkId=link)
        course = self.library()["courses"]["main:A"]
        self.assertEqual(course["readilyTag"], "cursos/a")
        self.assertTrue(course["links"][0]["readilySavedAt"])
        self.assertEqual(read_calls(log), [{"argv": ["save", "Cursos", "--stdin", "--create", "--title=Repo",
                                                     "--tag=cursos/a"], "stdin": "https://github.com/x"}])

    def test_readily_off(self):
        install_fake_readily(self.tmp)
        link = self.apply(op="link.add", owner=self.OWNER, content="https://github.com/x")["id"]
        self.apply(op="config.set", key="readily.enabled", value=False)
        self.fails(6, op="readily.save", owner=self.OWNER, linkId=link)

    def test_readily_copy(self):
        log = install_fake_readily(self.tmp)
        self.apply(op="readily.copy", section="Cursos", index=0, hash="abc")
        self.assertEqual(read_calls(log)[0]["argv"], ["copy", "Cursos", "0", "abc"])

    def test_owner_tag(self):
        from syllabus import view
        r = self.apply(op="roadmap.add", title="AI Engineering")["id"]
        built = view.build_view(store.load_config(), self.library(), store.load_state(), self.cache)
        self.assertEqual(ops.owner_tag(built, {"kind": "course", "id": "main:A"}), "cursos/a")
        self.assertEqual(ops.owner_tag(built, {"kind": "roadmap", "id": r}), "cursos/roadmap-ai-engineering")


class Notes(OpsCase):
    def test_note_set_and_clear(self):
        self.apply(op="note.set", courseId="main:A", text="# Notes")
        with open(paths.note_path("main:A"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Notes\n")
        self.apply(op="note.set", courseId="main:A", text="  ")
        self.assertFalse(os.path.exists(paths.note_path("main:A")))
        self.apply(op="note.set", courseId="main:A", text="")

    def note(self):
        with open(paths.note_path("main:A"), encoding="utf-8") as f:
            return f.read()

    def edit_outside(self, text):
        with open(paths.note_path("main:A"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_note_set_with_a_matching_base(self):
        self.apply(op="note.set", courseId="main:A", text="# Notes")
        # The window's base is the text it sent; the file got a final newline.
        self.apply(op="note.set", courseId="main:A", text="# Notes\nmore", base="# Notes")
        self.assertEqual(self.note(), "# Notes\nmore\n")
        self.edit_outside("# Edited")
        self.apply(op="note.set", courseId="main:A", text="# Edited\nagain", base="# Edited")
        self.assertEqual(self.note(), "# Edited\nagain\n")
        self.apply(op="note.set", courseId="main:A", text="", base="# Edited\nagain")
        self.assertFalse(os.path.exists(paths.note_path("main:A")))

    def test_note_set_refuses_a_stale_base(self):
        self.apply(op="note.set", courseId="main:A", text="# Notes")
        self.edit_outside("# Notes\nwritten in the editor\n")
        error = self.fails(2, op="note.set", courseId="main:A", text="# Notes!", base="# Notes")
        self.assertTrue(str(error).startswith("The note changed outside the window"), str(error))
        self.assertEqual(error.reason, "noteChanged")
        self.assertEqual(self.note(), "# Notes\nwritten in the editor\n")
        # Deleted outside: the base no longer matches either.
        os.unlink(paths.note_path("main:A"))
        self.fails(2, op="note.set", courseId="main:A", text="# Notes!", base="# Notes")
        self.assertFalse(os.path.exists(paths.note_path("main:A")))

    def test_new_note_with_an_empty_base(self):
        self.apply(op="note.set", courseId="main:A", text="first", base="")
        self.assertEqual(self.note(), "first\n")
        # A note created elsewhere meanwhile is not overwritten by a window that saw none.
        self.fails(2, op="note.set", courseId="main:A", text="mine", base="")
        self.assertEqual(self.note(), "first\n")

    def test_base_must_be_text(self):
        self.fails(2, op="note.set", courseId="main:A", text="x", base=3)


class Config(OpsCase):
    def test_config_set(self):
        self.apply(op="config.set", key="readily.section", value="Estudio")
        self.apply(op="config.set", key="seenThreshold", value=0.95)
        self.apply(op="config.set", key="player.args", value=["--fs"])
        config = store.load_config()
        self.assertEqual((config["readily"]["section"], config["seenThreshold"], config["player"]["args"]),
                         ("Estudio", 0.95, ["--fs"]))
        self.fails(2, op="config.set", key="seenThreshold", value=2)
        self.fails(2, op="config.set", key="readily.section", value="_bad")
        self.fails(2, op="config.set", key="player.args", value="--fs")
        self.fails(2, op="config.set", key="roots", value=[])


class WebConfig(OpsCase):
    def test_every_web_setting_can_be_changed(self):
        self.apply(op="config.set", key="web.quality", value="720p")
        self.apply(op="config.set", key="web.refreshHours", value=6)
        self.apply(op="config.set", key="web.subtitleLanguages", value=["pt", "en"])
        self.apply(op="config.set", key="web.autoSubtitles", value=False)
        self.apply(op="config.set", key="web.audioLanguage", value="es")
        self.apply(op="config.set", key="web.downloadFolder", value=os.path.join(self.tmp, "bajados"))
        web = store.load_config()["web"]
        self.assertEqual(web["quality"], "720p")
        self.assertEqual(web["refreshHours"], 6)
        self.assertEqual(web["subtitleLanguages"], ["pt", "en"])
        self.assertIs(web["autoSubtitles"], False)
        self.assertEqual(web["audioLanguage"], "es")
        self.assertEqual(web["downloadFolder"], os.path.join(self.tmp, "bajados"))

    def test_an_empty_audio_language_means_the_original(self):
        self.apply(op="config.set", key="web.audioLanguage", value="es")
        self.apply(op="config.set", key="web.audioLanguage", value="")
        self.assertEqual(store.load_config()["web"]["audioLanguage"], "")

    def test_bad_web_values_are_refused(self):
        from syllabus.errors import USAGE
        self.fails(USAGE, op="config.set", key="web.quality", value="4k")
        self.fails(USAGE, op="config.set", key="web.subtitleLanguages", value=["español"])
        self.fails(USAGE, op="config.set", key="web.audioLanguage", value="castellano")
        self.fails(USAGE, op="config.set", key="web.refreshHours", value=0)
        self.fails(USAGE, op="config.set", key="web.downloadFolder", value="bajados")


class WebOps(OpsCase):
    def setUp(self):
        super().setUp()
        self.course_id = "web:7f3a21"
        self.other_id = "web:999999"
        self.downloads_dir = os.path.join(self.tmp, "bajados")
        os.makedirs(self.downloads_dir)
        store.write_json(paths.config_path(), {"roots": [{"id": "main", "path": self.root}],
                                                "web": {"downloadFolder": self.downloads_dir}})
        lesson = {"id": self.course_id + "/youtube:aaa", "title": "Uno", "name": "Uno", "number": None,
                  "group": "", "relpath": "", "url": "https://www.youtube.com/watch?v=aaa", "site": "youtube",
                  "videoId": "aaa", "available": True, "source": "playlist", "duration": 600.0}
        loose = dict(lesson, id=self.course_id + "/vimeo:111", url="https://vimeo.com/111", site="vimeo",
                     videoId="111", source="video", title="Extra", name="Extra")
        self.cache["roots"]["web"] = {"courses": [{"id": self.course_id, "rootId": "web", "relpath": "",
                                                   "folderId": "", "title": "Curso", "topic": "",
                                                   "lessons": [lesson, loose], "docs": [], "images": [],
                                                   "autoCover": "", "coverPath": "", "sourceUrl": "https://p",
                                                   "sourceKind": "playlist"}],
                                      "images": [], "folders": {}, "sources": {}, "fetchedAt": ""}
        library = store.load_library()
        library["web"] = {self.course_id: {"sources": [{"kind": "playlist", "url": "https://p"},
                                                       {"kind": "video", "url": "https://vimeo.com/111"}],
                                           "addedAt": ""},
                          self.other_id: {"sources": [{"kind": "playlist", "url": "https://q"}], "addedAt": ""}}
        library["courses"][self.course_id] = {"title": "Curso", "tasks": [{"id": "t", "text": "x", "done": False}]}
        library["roadmaps"] = [{"id": "r", "title": "R", "stages": [{"id": "s", "title": "S",
                                                                     "courseIds": [self.course_id, "main:A"]}]}]
        store.save_library(library)

        def download(name, content):
            path = os.path.join(self.downloads_dir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return path

        # A downloaded file (and progress) for each of this course's two lessons, plus one
        # for an unrelated web course sitting in the same download folder, so removal can be
        # checked for both "everything of this course is gone" and "nothing else was touched".
        self.playlist_file = download("uno.mkv", "video")
        self.loose_file = download("extra.mkv", "extra video")
        self.other_file = download("otro.mkv", "other course video")
        self.other_lesson_id = self.other_id + "/youtube:zzz"
        with store.transaction() as docs:
            docs.state["downloads"] = {
                lesson["id"]: {"path": self.playlist_file, "size": os.path.getsize(self.playlist_file), "at": ""},
                loose["id"]: {"path": self.loose_file, "size": os.path.getsize(self.loose_file), "at": ""},
                self.other_lesson_id: {"path": self.other_file, "size": os.path.getsize(self.other_file), "at": ""},
            }
            docs.state["lessons"][lesson["id"]] = {"pos": 42.0, "duration": 600.0, "seen": False}
            docs.state["lessons"][loose["id"]] = {"pos": 10.0, "duration": 120.0, "seen": False}
            docs.state["last"] = {"lessonId": lesson["id"], "at": ""}

    def test_removing_a_web_course_takes_everything_with_it(self):
        result = self.apply(op="web.remove", courseId=self.course_id)
        self.assertTrue(result["rescan"])
        self.assertEqual(result["removed"], 2)
        self.assertFalse(os.path.exists(self.playlist_file))
        self.assertFalse(os.path.exists(self.loose_file))
        self.assertTrue(os.path.exists(self.other_file))
        state = store.load_state()
        self.assertEqual(set(state["downloads"]), {self.other_lesson_id})
        self.assertEqual(state["lessons"], {})
        self.assertIsNone(state["last"])
        library = self.library()
        self.assertNotIn(self.course_id, library["web"])
        self.assertNotIn(self.course_id, library["courses"])
        self.assertEqual(library["roadmaps"][0]["stages"][0]["courseIds"], ["main:A"])

    def test_removing_a_loose_video_only_drops_that_source(self):
        result = self.apply(op="web.removeVideo", courseId=self.course_id,
                            lessonId=self.course_id + "/vimeo:111")
        self.assertEqual(result["webIds"], [self.course_id])
        self.assertEqual(self.library()["web"][self.course_id]["sources"],
                         [{"kind": "playlist", "url": "https://p"}])
        self.assertFalse(os.path.exists(self.loose_file))
        self.assertTrue(os.path.exists(self.playlist_file))
        self.assertTrue(os.path.exists(self.other_file))
        state = store.load_state()
        self.assertNotIn(self.course_id + "/vimeo:111", state["downloads"])
        self.assertIn(self.course_id + "/youtube:aaa", state["downloads"])
        self.assertNotIn(self.course_id + "/vimeo:111", state["lessons"])
        self.assertIn(self.course_id + "/youtube:aaa", state["lessons"])

    def test_a_video_from_the_playlist_cannot_be_removed_one_by_one(self):
        from syllabus.errors import USAGE
        self.fails(USAGE, op="web.removeVideo", courseId=self.course_id,
                   lessonId=self.course_id + "/youtube:aaa")

    def test_removing_a_web_course_stops_a_running_download_first(self):
        # The worker is a real process we spawned and own; _is_worker is stubbed only
        # because its cmdline does not literally name this course. If web.remove did not
        # stop it before deleting, the worker would be left running with no registry left
        # to record what it finishes.
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            store.write_json(paths.download_path(self.course_id),
                             {"courseId": self.course_id, "pid": worker.pid, "total": 1, "done": 0,
                              "current": "", "failed": []})
            with mock.patch.object(ops.downloads, "_is_worker", return_value=True):
                self.apply(op="web.remove", courseId=self.course_id)
            worker.wait(timeout=5)
            self.assertIsNotNone(worker.poll())
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
