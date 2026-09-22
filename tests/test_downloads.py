import json
import os
import signal
import subprocess
import unittest
from unittest import mock

from support import TempHome, install_fake_ytdlp, ytdlp_answer, ytdlp_calls
from syllabus import downloads, paths, store


def web_lesson(course_id, video_id, title, source="playlist"):
    return {"id": f"{course_id}/youtube:{video_id}", "title": title, "name": title, "number": None, "group": "",
            "relpath": "", "url": f"https://www.youtube.com/watch?v={video_id}", "site": "youtube",
            "videoId": video_id, "available": True, "source": source, "duration": 600.0}


class Downloads(TempHome):
    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)
        self.folder = os.path.join(self.tmp, "Bajados")
        store.write_json(paths.config_path(), {"roots": [], "web": {"downloadFolder": self.folder,
                                                                    "quality": "720p",
                                                                    "subtitleLanguages": ["es", "en"],
                                                                    "autoSubtitles": True}})
        self.course_id = "web:7f3a21"
        self.lessons = [web_lesson(self.course_id, "aaa", "Uno: la/barra"),
                        web_lesson(self.course_id, "bbb", "Dos")]
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

    def test_names_are_safe_and_numbered(self):
        self.assertEqual(downloads.file_stem(1, self.lessons[0]), "01 - Uno: la barra [youtube-aaa]")
        self.assertEqual(downloads.safe_name("a" * 200), "a" * 120)
        self.assertEqual(downloads.safe_name("  con\nsalto  "), "con salto")
        self.assertEqual(downloads.safe_name(""), "untitled")

    def test_a_hostile_title_or_id_cannot_walk_out_of_the_folder(self):
        lesson = web_lesson("web:7f3a21", "aaa", "../../../../etc/passwd")
        lesson["site"], lesson["videoId"] = "we/b", "../../../../../../tmp/escape-poc"
        stem = downloads.file_stem(1, lesson)
        self.assertNotIn("/", stem)
        self.assertNotIn("..", stem)
        template = os.path.join(self.folder, stem + ".%(ext)s")
        self.assertTrue(os.path.normpath(template).startswith(self.folder + os.sep))

    def test_the_arguments_carry_the_format_and_the_subtitles(self):
        config = store.load_config()
        args = downloads.ytdlp_args(config, "https://u", "/out/%(ext)s")
        self.assertEqual(args[args.index("-f") + 1], "bv*[height<=720]+ba/b[height<=720]")
        self.assertIn("--write-subs", args)
        self.assertIn("--write-auto-subs", args)
        self.assertEqual(args[args.index("--sub-langs") + 1], "es,en")
        self.assertIn("--embed-subs", args)
        self.assertEqual(args[args.index("--merge-output-format") + 1], "mkv")

    def test_without_subtitle_languages_nothing_about_subtitles_is_asked(self):
        config = store.load_config()
        config["web"]["subtitleLanguages"] = []
        args = downloads.ytdlp_args(config, "https://u", "/out/%(ext)s")
        for flag in ("--write-subs", "--write-auto-subs", "--sub-langs", "--embed-subs", "--merge-output-format"):
            self.assertNotIn(flag, args)

    def test_a_download_registers_every_file_and_skips_what_is_there(self):
        summary = downloads.run(self.course_id)
        self.assertEqual((summary["total"], summary["done"], summary["failed"]), (2, 2, []))
        registry = store.load_state()["downloads"]
        self.assertEqual(sorted(registry), sorted(l["id"] for l in self.lessons))
        first = registry[self.lessons[0]["id"]]
        self.assertTrue(os.path.isfile(first["path"]))
        self.assertEqual(first["size"], len("video"))
        self.assertTrue(first["path"].startswith(os.path.join(self.folder, "Curso web") + os.sep))
        calls = len(ytdlp_calls(self.answers))
        again = downloads.run(self.course_id)
        self.assertEqual(again["total"], 0)
        self.assertEqual(len(ytdlp_calls(self.answers)), calls)

    def test_a_failed_video_does_not_stop_the_rest(self):
        ytdlp_answer(self.answers, self.lessons[0]["url"], {"__error__": "ERROR: video unavailable"})
        summary = downloads.run(self.course_id)
        self.assertEqual((summary["done"], len(summary["failed"])), (1, 1))
        self.assertEqual(list(store.load_state()["downloads"]), [self.lessons[1]["id"]])

    def test_delete_only_removes_registered_files_inside_the_folder(self):
        downloads.run(self.course_id)
        outside = os.path.join(self.tmp, "ajeno.mkv")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("no tocar")
        state = store.load_state()
        state["downloads"]["web:7f3a21/youtube:ccc"] = {"path": outside, "size": 8, "at": ""}
        kept = state["downloads"][self.lessons[1]["id"]]["path"]
        result = downloads.delete_files(store.load_config(), state,
                                        [self.lessons[0]["id"], "web:7f3a21/youtube:ccc"])
        self.assertEqual(result["removed"], 1)
        self.assertTrue(os.path.isfile(outside))
        self.assertTrue(os.path.isfile(kept))
        self.assertEqual(list(state["downloads"]), [self.lessons[1]["id"]])

    def test_progress_is_written_while_it_runs_and_cleaned_at_the_end(self):
        seen = []

        def spy(args, **rest):
            with open(paths.download_path(self.course_id), encoding="utf-8") as f:
                seen.append(json.load(f))
            return subprocess.run(args, **rest)

        downloads.run(self.course_id, spawn=spy)
        self.assertEqual([p["done"] for p in seen], [0, 1])
        self.assertEqual(seen[0]["total"], 2)
        self.assertEqual(seen[0]["courseId"], self.course_id)
        self.assertFalse(os.path.exists(paths.download_path(self.course_id)))

    def test_stop_refuses_to_signal_a_pid_that_is_not_our_worker(self):
        # This test's own pid is real and alive, but its cmdline never names this course:
        # stop() must not treat a recycled/unrelated pid as the download worker.
        store.write_json(paths.download_path(self.course_id),
                         {"courseId": self.course_id, "pid": os.getpid(), "total": 1, "done": 0,
                          "current": "", "failed": []})
        with mock.patch("os.kill") as killer:
            self.assertFalse(downloads.stop(self.course_id))
        killer.assert_not_called()

    def test_a_progress_file_of_a_worker_that_is_gone_is_forgotten(self):
        # SIGTERM never lets the worker clean up after itself, so the file it leaves
        # behind would otherwise keep the course "downloading" until the next login.
        path = paths.download_path(self.course_id)
        store.write_json(path, {"courseId": self.course_id, "pid": os.getpid(), "total": 2,
                                "done": 1, "current": "", "failed": []})
        self.assertIsNone(downloads.progress(self.course_id))
        self.assertFalse(os.path.exists(path))

    def test_a_progress_file_that_cannot_be_read_is_forgotten_too(self):
        path = paths.download_path(self.course_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(downloads.progress(self.course_id))
        self.assertFalse(os.path.exists(path))

    def test_stopping_a_download_clears_what_it_was_doing(self):
        path = paths.download_path(self.course_id)
        store.write_json(path, {"courseId": self.course_id, "pid": os.getpid(), "total": 2,
                                "done": 1, "current": "", "failed": []})
        with mock.patch.object(downloads, "_is_worker", return_value=True), mock.patch("os.kill") as killer:
            self.assertTrue(downloads.stop(self.course_id))
        killer.assert_called_once()
        self.assertFalse(os.path.exists(path))

    def test_stop_signals_the_whole_group_when_the_worker_is_its_own_session_leader(self):
        # cmd_download starts the worker with start_new_session=True: yt-dlp is a child inside
        # the worker's own process group, so only signalling that group stops the download
        # itself and not just the worker's bookkeeping.
        path = paths.download_path(self.course_id)
        worker_pid = 424242
        store.write_json(path, {"courseId": self.course_id, "pid": worker_pid, "total": 2,
                                "done": 1, "current": "", "failed": []})
        our_group = os.getpgid(0)

        def fake_getpgid(pid):
            if pid == 0:
                return our_group
            if pid == worker_pid:
                return worker_pid  # its own session: group leader is itself
            raise AssertionError(f"unexpected getpgid({pid})")

        with mock.patch.object(downloads, "_is_worker", return_value=True), \
                mock.patch("os.getpgid", side_effect=fake_getpgid), \
                mock.patch("os.killpg") as killpg, mock.patch("os.kill") as kill:
            self.assertTrue(downloads.stop(self.course_id))
        killpg.assert_called_once_with(worker_pid, signal.SIGTERM)
        kill.assert_not_called()
        self.assertFalse(os.path.exists(path))

    def test_stop_never_signals_the_test_processs_own_group(self):
        # A worker that is NOT its own session leader (the common case for a pid that
        # merely shares our group) must be signalled directly, never through killpg,
        # so stop() can never reach the group this test process itself lives in.
        path = paths.download_path(self.course_id)
        store.write_json(path, {"courseId": self.course_id, "pid": os.getpid(), "total": 2,
                                "done": 1, "current": "", "failed": []})
        with mock.patch.object(downloads, "_is_worker", return_value=True), \
                mock.patch("os.killpg") as killpg, mock.patch("os.kill") as kill:
            self.assertTrue(downloads.stop(self.course_id))
        killpg.assert_not_called()
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_register_writes_nothing_once_the_course_is_gone(self):
        # The worker keeps running after removal (it only notices at the next SIGTERM),
        # so a finished video must not re-create registry entries no one can reach any more.
        library = store.load_library()
        library["web"].pop(self.course_id, None)
        store.save_library(library)
        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, "ghost.mkv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        downloads._register(self.lessons[0]["id"], path)
        self.assertEqual(store.load_state().get("downloads", {}), {})


if __name__ == "__main__":
    unittest.main()
