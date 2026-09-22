import os
import unittest

from support import PLUGIN, TempHome, install_fake_ytdlp, ytdlp_answer, ytdlp_calls
from syllabus import covers, paths, web

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfake"
PLAYLIST = {
    "_type": "playlist", "title": "Deep Learning desde cero", "id": "PLfake",
    "thumbnails": [{"url": "https://i.example.com/small.jpg"}, {"url": "https://i.example.com/big.jpg"}],
    "entries": [
        {"id": "aaaaaaaaaaa", "ie_key": "Youtube", "title": "1. Qué es una red", "duration": 610},
        {"id": "bbbbbbbbbbb", "ie_key": "Youtube", "title": "2. Backpropagation"},
        {"id": "ccccccccccc", "ie_key": "Youtube", "title": "[Private video]"},
        {"title": "no id, ignored"},
    ],
}


class Reading(TempHome):
    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)

    def test_a_playlist_becomes_entries(self):
        ytdlp_answer(self.answers, PLAYLIST_URL, PLAYLIST)
        answer = web.fetch_playlist(PLAYLIST_URL)
        self.assertEqual(answer["error"], "")
        self.assertEqual(answer["kind"], "playlist")
        self.assertEqual(answer["title"], "Deep Learning desde cero")
        self.assertEqual(answer["thumbnail"], "https://i.example.com/big.jpg")
        self.assertEqual([e["videoId"] for e in answer["entries"]],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
        first = answer["entries"][0]
        self.assertEqual(first["site"], "youtube")
        self.assertEqual(first["url"], "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertEqual(first["duration"], 610.0)
        self.assertTrue(first["available"])
        self.assertEqual(answer["entries"][1]["duration"], 0.0)
        self.assertFalse(answer["entries"][2]["available"])
        self.assertIn("--flat-playlist", ytdlp_calls(self.answers)[0])

    def test_a_single_link_comes_back_as_one_video(self):
        url = "https://vimeo.com/123456789"
        ytdlp_answer(self.answers, url, {"id": "123456789", "ie_key": "Vimeo", "title": "Clase 1",
                                         "duration": 300, "thumbnail": "https://i.example.com/v.jpg"})
        answer = web.fetch_playlist(url)
        self.assertEqual(answer["kind"], "video")
        self.assertEqual(answer["entries"][0]["url"], "https://vimeo.com/123456789")
        self.assertEqual(answer["entries"][0]["site"], "vimeo")

    def test_a_password_is_passed_on(self):
        url = "https://vimeo.com/999"
        ytdlp_answer(self.answers, url, {"id": "999", "ie_key": "Vimeo", "title": "Privada", "duration": 60})
        web.fetch_video(url, password="abre-sésamo")
        call = ytdlp_calls(self.answers)[0]
        self.assertIn("--video-password", call)
        self.assertEqual(call[call.index("--video-password") + 1], "abre-sésamo")

    def test_a_network_failure_is_data_not_an_exception(self):
        url = "https://www.youtube.com/playlist?list=PLdown"
        ytdlp_answer(self.answers, url, {"__error__": "ERROR: [youtube] PLdown: Unable to download webpage"})
        answer = web.fetch_playlist(url)
        self.assertEqual(answer["entries"], [])
        self.assertEqual(answer["error"], "[youtube] PLdown: Unable to download webpage")

    def test_missing_durations_are_filled_one_by_one(self):
        ytdlp_answer(self.answers, PLAYLIST_URL, PLAYLIST)
        ytdlp_answer(self.answers, "https://www.youtube.com/watch?v=bbbbbbbbbbb",
                     {"id": "bbbbbbbbbbb", "ie_key": "Youtube", "title": "2. Backpropagation", "duration": 905.5})
        entries = web.fetch_playlist(PLAYLIST_URL)["entries"]
        web.fetch_durations(entries)
        self.assertEqual(entries[1]["duration"], 905.5)
        self.assertEqual(entries[0]["duration"], 610.0)        # ya la tenía: no se vuelve a pedir
        self.assertEqual(entries[2]["duration"], 0.0)          # no disponible: no se pregunta
        asked = [c[-1] for c in ytdlp_calls(self.answers)]
        self.assertEqual(asked.count("https://www.youtube.com/watch?v=aaaaaaaaaaa"), 0)


class Names(unittest.TestCase):
    def test_urls_are_normalized_by_site(self):
        self.assertEqual(web.normalize_url("youtube", "dQw4w9WgXcQ"),
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(web.normalize_url("vimeo", "123456789"), "https://vimeo.com/123456789")
        self.assertEqual(web.normalize_url("odd", "x", "https://odd.example/x"), "https://odd.example/x")

    def test_ids(self):
        self.assertEqual(web.lesson_id("web:7f3a21", "youtube", "dQw4w9WgXcQ"),
                         "web:7f3a21/youtube:dQw4w9WgXcQ")
        fresh = web.new_course_id({"web:000000"})
        self.assertTrue(fresh.startswith("web:") and len(fresh) == 10)
        self.assertNotEqual(fresh, "web:000000")


def defs(*sources, added="2026-09-19T12:00:00+00:00"):
    return {"sources": list(sources), "addedAt": added}


class Tree(TempHome):
    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)
        ytdlp_answer(self.answers, PLAYLIST_URL, PLAYLIST)
        for video_id, duration in (("bbbbbbbbbbb", 905.5),):
            ytdlp_answer(self.answers, f"https://www.youtube.com/watch?v={video_id}",
                         {"id": video_id, "ie_key": "Youtube", "title": "2. Backpropagation", "duration": duration})
        self.covers = []

    def cover(self, url):
        self.covers.append(url)
        return "/cache/thumb.jpg"

    def build(self, definitions, old=None, due=None):
        due = set(definitions) if due is None else due
        return web.build_tree(definitions, old or {}, due, cover=self.cover)

    def test_a_playlist_becomes_a_course(self):
        tree = self.build({"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})})
        course = tree["courses"][0]
        self.assertEqual(course["id"], "web:7f3a21")
        self.assertEqual(course["rootId"], "web")
        self.assertEqual(course["title"], "Deep Learning desde cero")
        self.assertEqual(course["sourceKind"], "playlist")
        self.assertEqual(course["sourceUrl"], PLAYLIST_URL)
        self.assertEqual(course["coverPath"], "/cache/thumb.jpg")
        self.assertEqual(self.covers, ["https://i.example.com/big.jpg"])
        self.assertEqual([l["id"] for l in course["lessons"]],
                         ["web:7f3a21/youtube:aaaaaaaaaaa", "web:7f3a21/youtube:bbbbbbbbbbb",
                          "web:7f3a21/youtube:ccccccccccc"])
        self.assertEqual(course["lessons"][1]["duration"], 905.5)
        self.assertEqual(course["lessons"][1]["name"], course["lessons"][1]["title"])
        self.assertFalse(course["lessons"][2]["available"])
        self.assertEqual({l["source"] for l in course["lessons"]}, {"playlist"})
        self.assertEqual(tree["sources"]["web:7f3a21"]["error"], "")
        self.assertNotEqual(tree["sources"]["web:7f3a21"]["fetchedAt"], "")

    def test_loose_videos_come_after_the_playlist_in_the_order_they_were_added(self):
        first, second = "https://vimeo.com/111", "https://vimeo.com/222"
        ytdlp_answer(self.answers, first, {"id": "111", "ie_key": "Vimeo", "title": "Extra 1", "duration": 60})
        ytdlp_answer(self.answers, second, {"id": "222", "ie_key": "Vimeo", "title": "Extra 2", "duration": 90})
        tree = self.build({"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL},
                                              {"kind": "video", "url": first},
                                              {"kind": "video", "url": second})})
        lessons = tree["courses"][0]["lessons"]
        self.assertEqual([l["title"] for l in lessons[-2:]], ["Extra 1", "Extra 2"])
        self.assertEqual({l["source"] for l in lessons[-2:]}, {"video"})

    def test_a_video_that_went_away_stays_at_the_end_marked_gone_and_comes_back_in_place(self):
        definitions = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})}
        old = self.build(definitions)
        shorter = dict(PLAYLIST, entries=[PLAYLIST["entries"][1]])          # solo queda el segundo
        ytdlp_answer(self.answers, PLAYLIST_URL, shorter)
        tree = self.build(definitions, old=old)
        lessons = tree["courses"][0]["lessons"]
        self.assertEqual([l["videoId"] for l in lessons], ["bbbbbbbbbbb", "aaaaaaaaaaa", "ccccccccccc"])
        self.assertEqual([l["available"] for l in lessons], [True, False, False])
        ytdlp_answer(self.answers, PLAYLIST_URL, PLAYLIST)
        back = self.build(definitions, old=tree)
        self.assertEqual([l["videoId"] for l in back["courses"][0]["lessons"]],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
        self.assertTrue(back["courses"][0]["lessons"][0]["available"])

    def test_a_failed_read_keeps_the_old_course_and_writes_the_error(self):
        definitions = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})}
        old = self.build(definitions)
        ytdlp_answer(self.answers, PLAYLIST_URL, {"__error__": "ERROR: [youtube] Unable to download webpage"})
        tree = self.build(definitions, old=old)
        self.assertEqual(tree["courses"][0]["lessons"], old["courses"][0]["lessons"])
        self.assertEqual(tree["sources"]["web:7f3a21"]["error"], "[youtube] Unable to download webpage")

    def test_a_course_that_is_not_due_is_copied_without_calling_yt_dlp(self):
        definitions = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})}
        old = self.build(definitions)
        calls = len(ytdlp_calls(self.answers))
        tree = self.build(definitions, old=old, due=set())
        self.assertEqual(tree["courses"], old["courses"])
        self.assertEqual(len(ytdlp_calls(self.answers)), calls)

    def test_a_prefetched_answer_is_used_instead_of_asking_again(self):
        answer = web.fetch_playlist(PLAYLIST_URL)
        reads = [c for c in ytdlp_calls(self.answers) if PLAYLIST_URL in c]
        tree = web.build_tree({"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})}, {},
                              {"web:7f3a21"}, cover=self.cover, prefetch={PLAYLIST_URL: answer})
        lessons = tree["courses"][0]["lessons"]
        self.assertEqual(len(lessons), 3)
        self.assertEqual([c for c in ytdlp_calls(self.answers) if PLAYLIST_URL in c], reads)
        self.assertEqual(lessons[1]["duration"], 905.5)

    def test_the_password_of_a_source_is_found_by_url(self):
        definitions = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL, "password": "playlist-pass"},
                                          {"kind": "video", "url": "https://vimeo.com/111", "password": "one-pass"})}
        self.assertEqual(web.password_for(definitions, "web:7f3a21", {"url": "https://vimeo.com/111"}), "one-pass")
        self.assertEqual(web.password_for(definitions, "web:7f3a21",
                                          {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}), "playlist-pass")
        self.assertEqual(web.password_for({}, "web:nope", {"url": "x"}), "")

    def test_a_loose_video_that_cannot_be_read_keeps_what_was_known(self):
        one = "https://vimeo.com/111"
        ytdlp_answer(self.answers, one, {"id": "111", "ie_key": "Vimeo", "title": "Extra 1", "duration": 60})
        definitions = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL}, {"kind": "video", "url": one})}
        old = self.build(definitions)
        ytdlp_answer(self.answers, one, {"__error__": "ERROR: [vimeo] 111: Unable to download webpage"})
        tree = self.build(definitions, old=old)
        lessons = tree["courses"][0]["lessons"]
        self.assertEqual(lessons[-1]["title"], "Extra 1")
        self.assertTrue(lessons[-1]["available"])
        self.assertEqual(tree["sources"]["web:7f3a21"]["error"], "[vimeo] 111: Unable to download webpage")

    def test_a_loose_video_whose_source_was_removed_leaves_for_good(self):
        one = "https://vimeo.com/111"
        ytdlp_answer(self.answers, one, {"id": "111", "ie_key": "Vimeo", "title": "Extra 1", "duration": 60})
        with_video = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL}, {"kind": "video", "url": one})}
        old = self.build(with_video)
        self.assertIn("111", [l["videoId"] for l in old["courses"][0]["lessons"]])
        # The source is gone from the definition now, the way web.removeVideo leaves it.
        without_video = {"web:7f3a21": defs({"kind": "playlist", "url": PLAYLIST_URL})}
        first = self.build(without_video, old=old)
        lessons = first["courses"][0]["lessons"]
        self.assertNotIn("111", [l.get("videoId") for l in lessons])
        self.assertEqual(len(lessons), 3)
        # And it must not come back as a "not available" ghost on a further build either —
        # that was the whole bug: a dropped source can never be "seen" again, so it used to
        # be re-added forever.
        second = self.build(without_video, old=first)
        lessons = second["courses"][0]["lessons"]
        self.assertNotIn("111", [l.get("videoId") for l in lessons])
        self.assertEqual(len(lessons), 3)


class RemoteCover(TempHome):
    def test_a_thumbnail_is_copied_once_and_reused(self):
        calls = []

        class Fake:
            def __init__(self, body):
                self.body = body

            def read(self, size):
                return self.body[:size]

            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        def opener(url, timeout=0):
            calls.append(url)
            return Fake(b"imagen")

        url = "https://i.example.com/big.jpg?sqp=abc"
        path = covers.cache_remote(url, opener=opener)
        self.assertTrue(path.endswith(".jpg"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"imagen")
        self.assertEqual(covers.cache_remote(url, opener=opener), path)
        self.assertEqual(len(calls), 1)

    def test_a_thumbnail_that_is_too_big_or_fails_is_skipped(self):
        class Big:
            def read(self, size):
                return b"x" * size

            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        self.assertEqual(covers.cache_remote("https://i.example.com/huge.jpg",
                                             max_bytes=4, opener=lambda url, timeout=0: Big()), "")

        def boom(url, timeout=0):
            raise OSError("no network")

        self.assertEqual(covers.cache_remote("https://i.example.com/x.jpg", opener=boom), "")
        self.assertEqual(covers.cache_remote("ftp://nope/x.jpg", opener=boom), "")

    def test_a_download_that_fails_leaves_no_descriptor_and_no_temp_file(self):
        def boom(url, timeout=0):
            raise OSError("no network")

        before = len(os.listdir("/proc/self/fd"))
        for _ in range(5):
            self.assertEqual(covers.cache_remote("https://i.example.com/x.jpg", opener=boom), "")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        self.assertEqual(sorted(os.listdir(paths.covers_dir())), [])


class ReadmeSafety(unittest.TestCase):
    def test_the_safety_section_admits_syllabus_fetches_the_thumbnail_too(self):
        # cache_remote() (called from web._read_course) is a second thing that reaches the
        # network on its own, besides yt-dlp reading the page and mpv streaming the video.
        with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as f:
            text = f.read()
        safety = text.split("## Safety", 1)[1]
        self.assertIn("thumbnail", safety)
