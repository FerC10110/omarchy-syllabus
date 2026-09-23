import os
import struct
import unittest
from unittest import mock

from support import PLUGIN, TempHome, install_fake_ytdlp, ytdlp_answer, ytdlp_calls, ytdlp_stdins
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

    def test_a_password_reaches_yt_dlp_without_touching_the_command_line(self):
        url = "https://vimeo.com/999"
        ytdlp_answer(self.answers, url, {"id": "999", "ie_key": "Vimeo", "title": "Privada", "duration": 60})
        web.fetch_video(url, password="abre-sésamo")
        call = ytdlp_calls(self.answers)[0]
        # /proc/<pid>/cmdline is readable by anyone on the machine; stdin is not.
        self.assertNotIn("--video-password", call)
        self.assertFalse([a for a in call if "sésamo" in a], call)
        self.assertEqual(call[:2], ["--config-locations", "-"])
        self.assertEqual(ytdlp_stdins(self.answers)[0], "--video-password 'abre-sésamo'\n")

    def test_a_password_with_spaces_survives_the_config_quoting(self):
        url = "https://vimeo.com/998"
        ytdlp_answer(self.answers, url, {"id": "998", "ie_key": "Vimeo", "title": "Privada", "duration": 60})
        web.fetch_video(url, password="abre sésamo #1")
        self.assertEqual(ytdlp_stdins(self.answers)[0], "--video-password 'abre sésamo #1'\n")

    def test_a_link_without_a_password_is_told_nothing(self):
        url = "https://vimeo.com/997"
        ytdlp_answer(self.answers, url, {"id": "997", "ie_key": "Vimeo", "title": "Abierta", "duration": 60})
        web.fetch_video(url)
        self.assertNotIn("--config-locations", ytdlp_calls(self.answers)[0])

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


class Ceilings(TempHome):
    """What comes back from a link is bounded, whatever the other side decides to send."""

    def setUp(self):
        super().setUp()
        self.answers = install_fake_ytdlp(self.tmp)

    def test_a_link_that_never_stops_printing_is_cut_off_and_killed(self):
        url = "https://vimeo.com/flood"
        ytdlp_answer(self.answers, url, {"__flood__": True})
        answer = web.fetch_video(url)
        self.assertEqual(answer["error"], "That link sent back far too much")
        self.assertEqual(answer["entries"], [])

    def test_a_playlist_past_the_ceiling_keeps_what_fits_and_says_so(self):
        url = "https://www.youtube.com/playlist?list=PLhuge"
        entries = [{"id": f"v{n}", "ie_key": "Youtube", "title": f"Clase {n}", "duration": 60}
                   for n in range(10)]
        ytdlp_answer(self.answers, url, {"_type": "playlist", "title": "Enorme", "entries": entries})
        with mock.patch.object(web, "MAX_ENTRIES", 3):
            answer = web.fetch_playlist(url)
        self.assertEqual(len(answer["entries"]), 3)
        self.assertEqual(answer["dropped"], 7)
        self.assertEqual([e["videoId"] for e in answer["entries"]], ["v0", "v1", "v2"])

    def test_a_truncated_playlist_tells_the_user_on_the_course(self):
        url = "https://www.youtube.com/playlist?list=PLhuge2"
        entries = [{"id": f"v{n}", "ie_key": "Youtube", "title": f"Clase {n}", "duration": 60}
                   for n in range(6)]
        ytdlp_answer(self.answers, url, {"_type": "playlist", "title": "Enorme", "entries": entries})
        defs = {"web:aaaaaa": {"sources": [{"kind": "playlist", "url": url}], "addedAt": ""}}
        with mock.patch.object(web, "MAX_ENTRIES", 2):
            tree = web.build_tree(defs, {}, {"web:aaaaaa"}, cover=lambda t: "")
        self.assertIn("more than 2 videos", tree["sources"]["web:aaaaaa"]["error"])
        self.assertEqual(len(tree["courses"][0]["lessons"]), 2)

    def test_a_field_is_never_longer_than_its_ceiling(self):
        url = "https://vimeo.com/long"
        ytdlp_answer(self.answers, url, {"id": "9" * 5000, "ie_key": "V" * 5000,
                                         "title": "t" * 5000, "webpage_url": "https://x/" + "u" * 9000,
                                         "duration": 60})
        entry = web.fetch_video(url)["entries"][0]
        self.assertEqual(len(entry["videoId"]), web.MAX_TEXT)
        self.assertEqual(len(entry["title"]), web.MAX_TEXT)
        self.assertLessEqual(len(entry["url"]), web.MAX_URL)
        self.assertLessEqual(len(entry["site"]), 40)

    def test_one_scan_only_looks_up_so_many_durations(self):
        asked = []

        def fetch(url, password=""):
            asked.append(url)
            return {"kind": "video", "title": "", "thumbnail": "", "entries": [], "error": "", "dropped": 0}

        entries = [{"site": "youtube", "videoId": f"v{n}", "url": f"https://www.youtube.com/watch?v=v{n}",
                    "title": "t", "duration": 0.0, "available": True} for n in range(20)]
        with mock.patch.object(web, "MAX_DURATION_LOOKUPS", 4):
            web.fetch_durations(entries, fetch=fetch)
        self.assertEqual(len(asked), 4)

    def test_a_thumbnail_offered_over_plain_http_is_ignored(self):
        self.assertEqual(web._thumbnail({"thumbnail": "http://i.example.com/x.jpg"}), "")
        self.assertEqual(web._thumbnail({"thumbnails": [{"url": "http://i.example.com/x.jpg"}]}), "")
        self.assertEqual(web._thumbnail({"thumbnail": "https://i.example.com/x.jpg"}),
                         "https://i.example.com/x.jpg")
        self.assertEqual(web._thumbnail({"thumbnail": "https://x/" + "a" * 4000}), "")


class RemoteCover(TempHome):
    def cached(self):
        folder = paths.covers_dir()
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 640, 360) + b"rest"

    def test_a_thumbnail_is_copied_once_and_reused(self):
        calls = []

        def get(url, max_bytes, timeout):
            calls.append(url)
            return self.PNG

        url = "https://i.example.com/big.png?sqp=abc"
        path = covers.cache_remote(url, get=get)
        self.assertTrue(path.endswith(".png"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.PNG)
        self.assertEqual(covers.cache_remote(url, get=get), path)
        self.assertEqual(len(calls), 1)

    def test_only_https_is_followed(self):
        def boom(url, max_bytes, timeout):
            raise AssertionError("this link should never have been opened: " + url)

        for url in ("http://i.example.com/x.png", "ftp://nope/x.jpg", "file:///etc/passwd",
                    "https://" + "a" * 3000 + "/x.png"):
            self.assertEqual(covers.cache_remote(url, get=boom), "")

    def test_an_address_on_this_machine_or_this_network_is_refused(self):
        # Numeric hosts, so the test never asks anyone to resolve a name.
        self.assertEqual(covers.resolve("127.0.0.1", 443), [])
        self.assertEqual(covers.resolve("::1", 443), [])
        self.assertEqual(covers.resolve("10.0.0.5", 443), [])
        self.assertEqual(covers.resolve("192.168.1.5", 443), [])
        self.assertEqual(covers.resolve("169.254.169.254", 443), [])
        self.assertEqual(covers.resolve("localhost", 443), [])
        self.assertEqual(covers.resolve("8.8.8.8", 443), ["8.8.8.8"])

    def test_every_redirect_is_checked_before_it_is_taken(self):
        hops = []

        class Response:
            def __init__(self, status, location=""):
                self.status, self._location = status, location

            def getheader(self, name):
                return self._location

            def read(self, size):
                return RemoteCover.PNG

        class Fake:
            def __init__(self, host, address, **rest):
                self.host = host

            def request(self, method, target, headers=None):
                hops.append(self.host)

            def getresponse(self):
                return Response(*plan.pop(0))

            def close(self):
                pass

        real_resolve = covers.resolve

        def resolve(host, port):
            # The one name in the test; every numeric host goes through the real check,
            # which getaddrinfo answers from the literal without asking anyone.
            return ["93.184.216.34"] if host == "i.example.com" else real_resolve(host, port)

        with mock.patch.object(covers, "_Pinned", Fake), \
                mock.patch.object(covers, "resolve", resolve):
            plan = [(302, "https://127.0.0.1/steal.png")]
            self.assertEqual(covers.fetch("https://i.example.com/a.png", 1000, 1), b"")
            self.assertEqual(hops, ["i.example.com"])

            hops.clear()
            plan = [(302, "http://8.8.8.8/plain.png")]
            self.assertEqual(covers.fetch("https://i.example.com/a.png", 1000, 1), b"")

            hops.clear()
            plan = [(302, "https://8.8.8.8/one.png"), (200, "")]
            self.assertEqual(covers.fetch("https://i.example.com/a.png", 1000, 1), self.PNG)

            hops.clear()
            plan = [(302, "https://8.8.8.8/%d.png" % n) for n in range(10)]
            self.assertEqual(covers.fetch("https://i.example.com/a.png", 1000, 1), b"")
            self.assertEqual(len(hops), covers.MAX_REDIRECTS + 1)

    def test_what_comes_back_has_to_be_an_image_of_a_sane_size(self):
        huge = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 50000, 50000) + b"r"
        for body in (b"", b"<html>not an image</html>" * 4, huge,
                     b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 0, 0) + b"r"):
            self.assertEqual(covers.cache_remote("https://i.example.com/x.png",
                                                 get=lambda u, m, t, b=body: b), "")
        self.assertEqual(self.cached(), [])

    def test_a_thumbnail_that_is_too_big_or_fails_is_skipped(self):
        self.assertEqual(covers.cache_remote("https://i.example.com/huge.png", max_bytes=4,
                                             get=lambda u, m, t: b""), "")

        def boom(url, max_bytes, timeout):
            raise OSError("no network")

        self.assertEqual(covers.cache_remote("https://i.example.com/x.png", get=boom), "")

    def test_a_download_that_fails_leaves_no_descriptor_and_no_temp_file(self):
        def boom(url, max_bytes, timeout):
            raise OSError("no network")

        before = len(os.listdir("/proc/self/fd"))
        for _ in range(5):
            self.assertEqual(covers.cache_remote("https://i.example.com/x.png", get=boom), "")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        self.assertEqual(self.cached(), [])


class ReadmeSafety(unittest.TestCase):
    def test_the_safety_section_admits_syllabus_fetches_the_thumbnail_too(self):
        # cache_remote() (called from web._read_course) is a second thing that reaches the
        # network on its own, besides yt-dlp reading the page and mpv streaming the video.
        with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as f:
            text = f.read()
        safety = text.split("## Safety", 1)[1]
        self.assertIn("thumbnail", safety)
