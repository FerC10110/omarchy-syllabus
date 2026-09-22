import os
import unittest

from support import TempHome, install_fake_ffprobe, install_fake_ytdlp, make_tree, ytdlp_answer, ytdlp_calls
from syllabus import covers, paths, probe, scan, store, web


def config_for(root):
    config = store.load_config()
    config["roots"] = [{"id": "main", "path": root}]
    return config


class ScanAll(TempHome):
    def setUp(self):
        super().setUp()
        install_fake_ffprobe(self.tmp)
        self.root = os.path.join(self.tmp, "cursos")
        make_tree(self.root, {"A/1_a.mp4": 600, "A/2_b.mp4": 1200.5, "A/3_broken.mkv": "garbage", "B/1_x.mp4": 30})
        self.config = config_for(self.root)

    def scan(self, old=None, fn=probe.probe_duration, force=False, config=None):
        return scan.scan_all(config or self.config, {}, old or store.empty_scan(), fn, force=force)

    def test_durations_and_errors(self):
        cache = self.scan()
        files = cache["files"]
        self.assertEqual(files["main:A/1_a.mp4"]["duration"], 600.0)
        self.assertEqual(files["main:A/2_b.mp4"]["duration"], 1200.5)
        self.assertEqual(files["main:A/3_broken.mkv"]["duration"], 0.0)
        self.assertIn("Invalid data", files["main:A/3_broken.mkv"]["error"])
        self.assertEqual(cache["probed"], 4)
        self.assertEqual([c["id"] for c in cache["roots"]["main"]["courses"]], ["main:A", "main:B"])
        self.assertEqual(cache["roots"]["main"]["path"], self.root)
        self.assertTrue(cache["roots"]["main"]["scannedAt"].endswith("+00:00"))

    def test_cache_is_reused_until_the_file_changes(self):
        first = self.scan()
        calls = []

        def counting(path):
            calls.append(path)
            return probe.probe_duration(path)

        second = self.scan(first, counting)
        self.assertEqual((calls, second["probed"]), ([], 0))
        make_tree(self.root, {"A/1_a.mp4": 6000})
        third = self.scan(second, counting)
        self.assertEqual([os.path.basename(p) for p in calls], ["1_a.mp4"])
        self.assertEqual(third["files"]["main:A/1_a.mp4"]["duration"], 6000.0)

    def test_force_probes_everything(self):
        self.assertEqual(self.scan(self.scan(), force=True)["probed"], 4)

    def test_offline_root_keeps_the_cached_tree(self):
        first = self.scan()
        second = self.scan(first, config=config_for(os.path.join(self.tmp, "not-mounted")))
        self.assertEqual(second["roots"]["main"], first["roots"]["main"])
        self.assertEqual(second["files"], first["files"])
        self.assertEqual(second["probed"], 0)

    def test_an_ffprobe_that_cannot_run_is_an_error_per_file(self):
        blocked = os.path.join(self.tmp, "ffprobe-not-executable")
        with open(blocked, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.environ["SYLLABUS_FFPROBE"] = blocked
        with self.assertRaises(probe.ProbeError):
            probe.probe_duration(os.path.join(self.root, "A", "1_a.mp4"))
        cache = self.scan()
        self.assertEqual(cache["probed"], 4)
        self.assertTrue(all(record["error"] for record in cache["files"].values()))

    def test_ffprobe_output_that_is_not_utf8(self):
        noisy = os.path.join(self.tmp, "ffprobe-latin1")
        with open(noisy, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nprintf 'caf\\351: Invalid data\\n' >&2\nexit 1\n")
        os.chmod(noisy, 0o755)
        os.environ["SYLLABUS_FFPROBE"] = noisy
        with self.assertRaises(probe.ProbeError) as caught:
            probe.probe_duration(os.path.join(self.root, "A", "1_a.mp4"))
        self.assertIn("Invalid data", str(caught.exception))


class Moves(TempHome):
    def setUp(self):
        super().setUp()
        install_fake_ffprobe(self.tmp)
        self.root = os.path.join(self.tmp, "cursos")
        self.config = config_for(self.root)

    def rename(self, old, new):
        os.makedirs(os.path.dirname(os.path.join(self.root, new)), exist_ok=True)
        os.rename(os.path.join(self.root, old), os.path.join(self.root, new))

    def test_moved_and_renamed_files_keep_their_data(self):
        make_tree(self.root, {"A/1_a.mp4": 600, "A/2_b.mp4": 1200})
        old = scan.scan_all(self.config, {}, store.empty_scan(), probe.probe_duration)
        self.rename("A/1_a.mp4", "A/old/1_a.mp4")
        self.rename("A/2_b.mp4", "A/02 - b.mp4")
        new = scan.scan_all(self.config, {}, old, probe.probe_duration)
        moves = scan.find_moves(old, new, ["main"])
        self.assertEqual(moves, {"main:A/1_a.mp4": "main:A/old/1_a.mp4", "main:A/2_b.mp4": "main:A/02 - b.mp4"})

        library = store.empty_library()
        library["lessons"]["main:A/1_a.mp4"] = {"title": "Intro"}
        library["courses"]["main:A"] = {"order": ["main:A/2_b.mp4", "main:A/1_a.mp4"]}
        state = store.empty_state()
        state["lessons"]["main:A/2_b.mp4"] = {"pos": 30}
        state["last"] = {"lessonId": "main:A/2_b.mp4", "at": "x"}
        self.assertEqual(scan.apply_moves(library, state, moves), 2)
        self.assertEqual(library["lessons"], {"main:A/old/1_a.mp4": {"title": "Intro"}})
        self.assertEqual(library["courses"]["main:A"]["order"], ["main:A/02 - b.mp4", "main:A/old/1_a.mp4"])
        self.assertEqual(state["lessons"], {"main:A/02 - b.mp4": {"pos": 30}})
        self.assertEqual(state["last"]["lessonId"], "main:A/02 - b.mp4")

    def test_ambiguous_sizes_are_not_guessed(self):
        make_tree(self.root, {"A/1_a.mp4": 600, "A/2_b.mp4": 600})
        old = scan.scan_all(self.config, {}, store.empty_scan(), probe.probe_duration)
        self.rename("A/1_a.mp4", "A/x.mp4")
        self.rename("A/2_b.mp4", "A/y.mp4")
        new = scan.scan_all(self.config, {}, old, probe.probe_duration)
        self.assertEqual(scan.find_moves(old, new, ["main"]), {})

    def test_offline_roots_never_move(self):
        make_tree(self.root, {"A/1_a.mp4": 600})
        old = scan.scan_all(self.config, {}, store.empty_scan(), probe.probe_duration)
        self.assertEqual(scan.find_moves(old, store.empty_scan(), []), {})


class Covers(TempHome):
    def test_cache_cover_copies_once(self):
        source = os.path.join(self.tmp, "cover.webp")
        with open(source, "w") as f:
            f.write("img")
        target = covers.cache_cover(source)
        self.assertEqual(target, covers.cached_path(source))
        self.assertTrue(target.startswith(paths.covers_dir()))
        self.assertTrue(target.endswith(".webp"))
        with open(target) as f:
            self.assertEqual(f.read(), "img")
        self.assertEqual(covers.cache_cover(source), target)
        self.assertEqual([n for n in os.listdir(paths.covers_dir()) if n.startswith(".tmp-")], [])

    def test_cache_cover_cleans_up_the_temp_file_after_a_failed_copy(self):
        source = os.path.join(self.tmp, "missing.png")
        with self.assertRaises(OSError):
            covers.cache_cover(source)
        self.assertEqual(os.listdir(paths.covers_dir()), [])


class WebRoot(TempHome):
    def setUp(self):
        super().setUp()
        install_fake_ffprobe(self.tmp)
        self.answers = install_fake_ytdlp(self.tmp)
        self.root = os.path.join(self.tmp, "cursos")
        make_tree(self.root, {"A/1_a.mp4": 600})
        store.write_json(paths.config_path(), {"roots": [{"id": "main", "path": self.root}],
                                               "web": {"downloadFolder": os.path.join(self.root, "Bajados")}})
        self.config = store.load_config()

    def fake_tree(self, courses=("web:7f3a21",)):
        def build(defs, old_tree, due, **rest):
            self.built = (dict(defs), set(due))
            return {"courses": [{"id": cid, "rootId": "web", "relpath": "", "folderId": "", "title": "Curso web",
                                 "topic": "", "docs": [], "images": [], "autoCover": "", "coverPath": "",
                                 "sourceUrl": "https://example/p", "sourceKind": "playlist",
                                 "lessons": [{"id": cid + "/youtube:aaa", "title": "1", "name": "1", "number": None,
                                              "group": "", "relpath": "", "url": "https://www.youtube.com/watch?v=aaa",
                                              "site": "youtube", "videoId": "aaa", "available": True,
                                              "source": "playlist", "duration": 300.0}]} for cid in courses],
                    "images": [], "folders": {}, "sources": {cid: {"fetchedAt": store.now_iso(), "error": ""}
                                                             for cid in courses},
                    "fetchedAt": store.now_iso(), "error": ""}
        return build

    def scan(self, defs, old=None, force=False, web_ids=None):
        return scan.scan_all(self.config, {}, old or store.empty_scan(), probe.probe_duration, force,
                             web_defs=defs, web_ids=web_ids, build_web=self.fake_tree())

    def test_the_web_root_joins_the_disk_roots_and_its_durations_go_to_files(self):
        cache = self.scan({"web:7f3a21": {"sources": [], "addedAt": ""}})
        self.assertEqual(sorted(cache["roots"]), ["main", "web"])
        self.assertEqual(cache["files"]["web:7f3a21/youtube:aaa"], {"duration": 300.0})
        self.assertEqual(self.built[1], {"web:7f3a21"})

    def test_without_web_courses_nothing_web_is_scanned(self):
        cache = self.scan({})
        self.assertEqual(list(cache["roots"]), ["main"])
        self.assertEqual(ytdlp_calls(self.answers), [])

    def test_the_download_folder_is_not_scanned_as_a_course(self):
        make_tree(self.root, {"Bajados/Curso web/01 - uno [youtube-aaa].mkv": 300})
        cache = self.scan({})
        titles = [c["title"] for c in cache["roots"]["main"]["courses"]]
        self.assertNotIn("Bajados", titles)
        self.assertEqual(titles, ["A"])

    def test_a_download_folder_nested_under_a_course_root_is_not_scanned_either(self):
        make_tree(self.root, {"Mercados/cursoTrading/1_uno.mp4": 300,
                              "Mercados/Bajados/Curso web/01 - uno [youtube-aaa].mkv": 300})
        store.write_json(paths.config_path(),
                         {"roots": [{"id": "main", "path": self.root}],
                          "web": {"downloadFolder": os.path.join(self.root, "Mercados", "Bajados")}})
        self.config = store.load_config()
        cache = self.scan({})
        courses = cache["roots"]["main"]["courses"]
        self.assertNotIn("Bajados", [c["title"] for c in courses])
        paths_seen = [l["relpath"] for c in courses for l in c["lessons"]]
        self.assertTrue(all("Bajados" not in p for p in paths_seen), paths_seen)

    def test_only_the_courses_that_are_due_are_read_again(self):
        old = self.scan({"web:7f3a21": {"sources": [], "addedAt": ""}})
        fresh = dict(old["roots"]["web"]["sources"]["web:7f3a21"], fetchedAt=store.now_iso())
        old["roots"]["web"]["sources"]["web:7f3a21"] = fresh
        self.scan({"web:7f3a21": {"sources": [], "addedAt": ""}}, old=old)
        self.assertEqual(self.built[1], set())
        self.scan({"web:7f3a21": {"sources": [], "addedAt": ""}}, old=old, web_ids={"web:7f3a21"})
        self.assertEqual(self.built[1], {"web:7f3a21"})
        self.scan({"web:7f3a21": {"sources": [], "addedAt": ""}}, old=old, force=True)
        self.assertEqual(self.built[1], {"web:7f3a21"})

    def test_a_broken_web_step_does_not_lose_the_disk_scan(self):
        def explode(defs, old_tree, due, **rest):
            raise RuntimeError("yt-dlp exploded")

        cache = scan.scan_all(self.config, {}, store.empty_scan(), probe.probe_duration,
                              web_defs={"web:7f3a21": {"sources": [], "addedAt": ""}}, build_web=explode)
        self.assertEqual([c["title"] for c in cache["roots"]["main"]["courses"]], ["A"])
        self.assertIn("yt-dlp exploded", cache["roots"]["web"]["error"])

    def test_a_read_older_than_the_setting_is_due(self):
        old_tree = {"sources": {"a": {"fetchedAt": "2020-01-01T00:00:00+00:00"},
                                "b": {"fetchedAt": store.now_iso()},
                                "c": {"fetchedAt": "not a date"}}}
        due = scan.web_due(old_tree, {"a": {}, "b": {}, "c": {}, "d": {}}, 24)
        self.assertEqual(due, {"a", "c", "d"})


if __name__ == "__main__":
    unittest.main()
