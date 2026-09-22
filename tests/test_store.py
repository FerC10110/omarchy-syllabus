import datetime
import json
import os
import unittest

from support import TempHome, local_tz
from syllabus import paths, store
from syllabus.errors import GENERAL, SyllabusError


class Paths(TempHome):
    def test_xdg_locations(self):
        self.assertEqual(paths.config_path(), os.path.join(self.tmp, "config", "syllabus", "config.json"))
        self.assertEqual(paths.state_path(), os.path.join(self.tmp, "state", "syllabus", "state.json"))
        self.assertEqual(paths.scan_path(), os.path.join(self.tmp, "cache", "syllabus", "scan.json"))
        self.assertEqual(paths.socket_path(), os.path.join(self.tmp, "run", "syllabus", "mpv.sock"))

    def test_note_path_is_hashed_and_stable(self):
        a = paths.note_path("main:Shorts/LLM")
        self.assertEqual(a, paths.note_path("main:Shorts/LLM"))
        self.assertTrue(a.startswith(os.path.join(self.tmp, "config", "syllabus", "notes")))
        self.assertTrue(a.endswith(".md"))
        self.assertEqual(len(os.path.basename(a)), 16 + 3)

    def test_plugin_paths(self):
        self.assertTrue(paths.BIN_PATH.endswith(os.path.join("bin", "syllabus")))
        self.assertTrue(paths.LUA_PATH.endswith(os.path.join("mpv", "syllabus.lua")))


class Config(TempHome):
    def test_defaults_when_missing(self):
        config = store.load_config()
        self.assertEqual(config["roots"], [{"id": "main", "path": os.path.join(os.path.expanduser("~"), "Videos", "Courses")}])
        self.assertEqual(config["seenThreshold"], 0.9)
        self.assertEqual(config["readily"], {"enabled": True, "section": "Cursos"})

    def test_merge_keeps_valid_values_and_drops_wrong_types(self):
        store.write_json(paths.config_path(), {
            "roots": [{"id": "ext", "path": "/mnt/x/"}, {"id": "bad:id", "path": "/y"}, "junk"],
            "seenThreshold": "high",
            "resumeRewind": 10,
            "readily": {"enabled": False},
            "unknown": 1,
        })
        config = store.load_config()
        self.assertEqual(config["roots"], [{"id": "ext", "path": "/mnt/x"}])
        self.assertEqual(config["seenThreshold"], 0.9)
        self.assertEqual(config["resumeRewind"], 10)
        self.assertEqual(config["readily"], {"enabled": False, "section": "Cursos"})
        self.assertNotIn("unknown", config)

    def test_web_defaults(self):
        config = store.load_config()
        self.assertEqual(config["web"]["quality"], "1080p")
        self.assertEqual(config["web"]["refreshHours"], 24)
        self.assertEqual(config["web"]["subtitleLanguages"], ["es", "en"])
        self.assertIs(config["web"]["autoSubtitles"], True)
        self.assertEqual(config["web"]["audioLanguage"], "")
        self.assertEqual(config["web"]["downloadFolder"],
                         os.path.join(os.path.expanduser("~"), "Videos", "Syllabus"))

    def test_web_values_are_cleaned(self):
        store.write_json(paths.config_path(), {"web": {"quality": "4k", "refreshHours": 900,
                                                       "downloadFolder": "~/Bajados/",
                                                       "subtitleLanguages": ["es", "", 7, "pt-BR"],
                                                       "audioLanguage": "not a language"}})
        web = store.load_config()["web"]
        self.assertEqual(web["quality"], "1080p")
        self.assertEqual(web["refreshHours"], 168)
        self.assertEqual(web["downloadFolder"], os.path.join(os.path.expanduser("~"), "Bajados"))
        self.assertEqual(web["subtitleLanguages"], ["es", "pt-BR"])
        self.assertEqual(web["audioLanguage"], "")


class Files(TempHome):
    def test_write_and_read_json(self):
        path = os.path.join(self.tmp, "x", "data.json")
        store.write_json(path, {"a": "ñ"})
        self.assertEqual(store.read_json(path, {}), {"a": "ñ"})
        self.assertEqual(os.listdir(os.path.dirname(path)), ["data.json"])

    def test_read_json_missing_and_broken(self):
        path = os.path.join(self.tmp, "missing.json")
        self.assertEqual(store.read_json(path, {"empty": True}), {"empty": True})
        with open(path, "w") as f:
            f.write("{nope")
        with self.assertRaises(SyllabusError):
            store.read_json(path, {})

    def test_read_json_rejects_non_object(self):
        path = os.path.join(self.tmp, "list.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        with self.assertRaises(SyllabusError) as ctx:
            store.read_json(path, {})
        self.assertEqual(ctx.exception.code, GENERAL)
        self.assertIn("not an object", str(ctx.exception))

    def test_ensure_files_creates_state_and_library(self):
        store.ensure_files()
        self.assertEqual(store.load_state(), store.empty_state())
        self.assertEqual(store.load_library(), store.empty_library())

    def test_load_state_drops_garbage(self):
        store.write_json(paths.state_path(), {"lessons": {"a": {"pos": 1}, "b": 3}, "last": "x", "days": []})
        state = store.load_state()
        self.assertEqual(state["lessons"], {"a": {"pos": 1}})
        self.assertIsNone(state["last"])
        self.assertEqual(state["days"], {})

    def test_load_state_keeps_only_a_valid_panel_size_and_pin(self):
        store.write_json(paths.state_path(), {"window": {"width": 1300, "height": "tall", "pinned": True, "x": 1}})
        self.assertEqual(store.load_state()["window"], {"width": 1300, "pinned": True})
        store.write_json(paths.state_path(), {"window": [1, 2]})
        self.assertEqual(store.load_state()["window"], {})


class Scan(TempHome):
    def test_load_scan_missing_returns_empty_shape(self):
        self.assertEqual(store.load_scan(), store.empty_scan())

    def test_save_and_load_round_trip(self):
        cache = store.empty_scan()
        cache["roots"]["main"] = {"scannedAt": "2026-09-19T00:00:00+00:00"}
        cache["files"]["main:a.mp4"] = {"duration": 120}
        store.save_scan(cache)
        self.assertEqual(store.load_scan(), cache)

    def test_load_scan_drops_garbage(self):
        store.write_json(paths.scan_path(), {
            "roots": {"main": {"scannedAt": "x"}, "bad": 3},
            "files": "nope",
        })
        cache = store.load_scan()
        self.assertEqual(cache["roots"], {"main": {"scannedAt": "x"}})
        self.assertEqual(cache["files"], {})


class Transaction(TempHome):
    def test_only_changed_documents_are_written(self):
        with store.transaction() as docs:
            docs.state["lessons"]["x"] = {"pos": 3}
        self.assertTrue(os.path.exists(paths.state_path()))
        self.assertFalse(os.path.exists(paths.library_path()))
        self.assertFalse(os.path.exists(paths.config_path()))

    def test_exception_discards_changes(self):
        with self.assertRaises(RuntimeError):
            with store.transaction() as docs:
                docs.library["roadmaps"].append({"id": "r"})
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(paths.library_path()))


class Dates(TempHome):
    def test_now_iso_is_utc(self):
        self.assertTrue(store.now_iso().endswith("+00:00"))

    def test_local_day_uses_local_time(self):
        moment = datetime.datetime(2026, 9, 19, 2, 0, tzinfo=datetime.timezone.utc)
        with local_tz("America/Argentina/Buenos_Aires"):
            self.assertEqual(store.local_day(moment), "2026-09-18")
        with local_tz("UTC"):
            self.assertEqual(store.local_day(moment), "2026-09-19")


class WebDocuments(TempHome):
    def test_library_and_state_start_with_the_web_tables(self):
        self.assertEqual(store.load_library()["web"], {})
        self.assertEqual(store.load_state()["downloads"], {})

    def test_web_definitions_and_downloads_survive_a_reload(self):
        store.write_json(paths.library_path(), {"web": {"web:7f3a21": {"sources": [], "addedAt": "x"}, "bad": 7}})
        store.write_json(paths.state_path(), {"downloads": {"web:7f3a21/youtube:a": {"path": "/tmp/a.mkv"},
                                                            "web:7f3a21/youtube:b": "junk"}})
        self.assertEqual(list(store.load_library()["web"]), ["web:7f3a21"])
        self.assertEqual(list(store.load_state()["downloads"]), ["web:7f3a21/youtube:a"])


if __name__ == "__main__":
    unittest.main()
