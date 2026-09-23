import json
import os
import socket
import socketserver
import threading
import unittest

from support import TempHome
from syllabus import paths, player, store
from syllabus.errors import SyllabusError


class FakeMpv:
    """A Unix socket that answers like mpv's JSON IPC, with an event before every reply."""

    def __init__(self, path, props=None):
        self.commands = []
        self.props = props or {"pid": 1234}
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for raw in self.rfile:
                    message = json.loads(raw)
                    command = message["command"]
                    fake.commands.append(command)
                    self.wfile.write(b'{"event":"playback-restart"}\n')
                    if command[0] == "get_property":
                        known = command[1] in fake.props
                        reply = {"data": fake.props.get(command[1]),
                                 "error": "success" if known else "property unavailable"}
                    else:
                        reply = {"data": None, "error": "success"}
                    reply["request_id"] = message.get("request_id", 0)
                    self.wfile.write((json.dumps(reply) + "\n").encode())

        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.server = socketserver.ThreadingUnixStreamServer(path, Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class Argv(TempHome):
    def test_build_argv(self):
        config = store.load_config()
        config["player"]["args"] = ["--fs"]
        self.assertEqual(player.build_argv(config, "/disk/a b.mp4", 95.0, "/run/s.sock"), [
            "mpv", "--force-window=immediate", "--input-ipc-server=/run/s.sock", "--start=95.000",
            "--resume-playback=no", "--save-position-on-quit=no", f"--script={paths.LUA_PATH}",
            f"--script-opt=syllabus-bin={paths.BIN_PATH}", "--script-opt=syllabus-report=30",
            "--fs", "--", "/disk/a b.mp4"])


class WebOptions(TempHome):
    def setUp(self):
        super().setUp()
        self.config = store.load_config()

    def options(self, **web):
        self.config["web"].update(web)
        return player.web_options(self.config)[0]

    def test_the_format_crosses_quality_with_the_audio_language(self):
        self.assertEqual(player.format_selector({"quality": "720p", "audioLanguage": ""}),
                         "bv*[height<=720]+ba/b[height<=720]")
        self.assertEqual(player.format_selector({"quality": "1080p", "audioLanguage": "es"}),
                         "bv*[height<=1080]+ba[language^=es]/bv*[height<=1080]+ba/b[height<=1080]")
        self.assertEqual(player.format_selector({"quality": "best", "audioLanguage": ""}), "")
        self.assertEqual(player.format_selector({"quality": "best", "audioLanguage": "pt"}),
                         "bv*+ba[language^=pt]/b")

    def test_subtitles_travel_in_the_raw_options(self):
        options = dict(self.options(subtitleLanguages=["es", "en"], autoSubtitles=True))
        self.assertEqual(options["slang"], "es,en")
        self.assertEqual(options["ytdl-raw-options"], "sub-langs=%5%es,en,write-auto-subs=")
        self.assertNotIn("sid", options)

    def test_automatic_subtitles_can_be_left_out(self):
        options = dict(self.options(subtitleLanguages=["es"], autoSubtitles=False))
        self.assertEqual(options["ytdl-raw-options"], "sub-langs=es")

    def test_no_subtitle_languages_means_none_are_shown(self):
        options = dict(self.options(subtitleLanguages=[]))
        self.assertEqual(options["sid"], "no")
        self.assertNotIn("slang", options)
        self.assertNotIn("ytdl-raw-options", options)

    def test_the_password_never_travels_with_the_plain_options(self):
        self.config["web"].update({"subtitleLanguages": ["es"], "autoSubtitles": False})
        options, secret = player.web_options(self.config, password="abre,sésamo")
        self.assertEqual(dict(options)["ytdl-raw-options"], "sub-langs=es")
        self.assertEqual(secret, ["video-password=%12%abre,sésamo"])
        # The socket is this session's own; there the password may ride along.
        self.assertEqual(dict(player.with_secret(options, secret))["ytdl-raw-options"],
                         "sub-langs=es,video-password=%12%abre,sésamo")

    def test_the_password_reaches_mpv_through_a_file_no_one_can_open(self):
        _, secret = player.web_options(self.config, password="abre,sésamo")
        fd = player.secret_include(secret)
        self.addCleanup(os.close, fd)
        argv = player.build_argv(self.config, "https://vimeo.com/1", 0.0, "/tmp/s",
                                 player.web_options(self.config)[0], fd)
        self.assertFalse([a for a in argv if "sésamo" in a], argv)
        self.assertIn(f"--include=/dev/fd/{fd}", argv)
        # After the plain options, or the append would be overwritten by them.
        self.assertGreater(argv.index(f"--include=/dev/fd/{fd}"),
                           max(i for i, a in enumerate(argv) if a.startswith("--ytdl-raw-options=")))
        self.assertEqual(os.read(fd, 4096).decode("utf-8"),
                         "ytdl-raw-options-append=%31%video-password=%12%abre,sésamo\n")

    def test_without_a_password_there_is_no_extra_file(self):
        options, secret = player.web_options(self.config)
        self.assertEqual(secret, [])
        self.assertIsNone(player.secret_include(secret))
        self.assertFalse([a for a in player.build_argv(self.config, "/a.mkv", 0.0, "/tmp/s", options)
                          if a.startswith("--include=")])

    def test_the_options_reach_the_command_line_and_the_socket(self):
        options, _ = player.web_options(self.config)
        argv = player.build_argv(self.config, "https://www.youtube.com/watch?v=aaa", 12.0, "/tmp/s", options)
        self.assertIn("--ytdl-format=bv*[height<=1080]+ba/b[height<=1080]", argv)
        self.assertIn("--slang=es,en", argv)
        self.assertIn("--ytdl-raw-options=sub-langs=%5%es,en,write-auto-subs=", argv)
        self.assertEqual(argv[-2:], ["--", "https://www.youtube.com/watch?v=aaa"])
        # mpv parses the loadfile string with the same escape, one level deeper.
        self.assertEqual(player.file_options(12.0, options),
                         "start=12.000,ytdl-format=bv*[height<=1080]+ba/b[height<=1080],slang=%5%es,en,"
                         "ytdl-raw-options=%35%sub-langs=%5%es,en,write-auto-subs=")

    def test_a_disk_video_gets_no_web_options(self):
        argv = player.build_argv(self.config, "/disk/a.mkv", 0.0, "/tmp/s")
        self.assertFalse([a for a in argv if a.startswith(("--ytdl-", "--slang", "--sid"))])
        self.assertEqual(player.file_options(0.0, ()), "start=0.000")


class Play(TempHome):
    def setUp(self):
        super().setUp()
        self.config = store.load_config()
        self.sock = paths.socket_path()

    def test_spawns_mpv_when_none_is_running(self):
        os.makedirs(os.path.dirname(self.sock), exist_ok=True)
        open(self.sock, "w").close()  # left behind by an mpv that was killed
        spawned = []
        mode = player.play(self.config, "/disk/x.mp4", 12.0, spawn=lambda argv, **kw: spawned.append((argv, kw)))
        self.assertEqual(mode, "started")
        argv, kwargs = spawned[0]
        self.assertEqual(argv[-2:], ["--", "/disk/x.mp4"])
        self.assertIn("--start=12.000", argv)
        self.assertTrue(kwargs["start_new_session"])
        self.assertFalse(os.path.exists(self.sock))

    def test_reuses_a_running_mpv(self):
        fake = FakeMpv(self.sock)
        self.addCleanup(fake.stop)
        spawned = []
        mode = player.play(self.config, "/disk/línea\nnueva.mkv", 95.0, spawn=lambda *a, **k: spawned.append(a))
        self.assertEqual((mode, spawned), ("loaded", []))
        self.assertEqual(fake.commands[-1], ["loadfile", "/disk/línea\nnueva.mkv", "replace", -1, "start=95.000"])

    def test_a_busy_mpv_is_not_replaced(self):
        # A socket that accepts the connection and never answers: an mpv too busy to reply in time.
        os.makedirs(os.path.dirname(self.sock), exist_ok=True)
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(silent.close)
        silent.bind(self.sock)
        silent.listen(1)
        spawned = []
        with self.assertRaises(SyllabusError) as caught:
            player.play(self.config, "/disk/x.mp4", 0, spawn=lambda *a, **k: spawned.append(a))
        self.assertEqual((caught.exception.code, str(caught.exception)), (5, "mpv is busy"))
        self.assertEqual(spawned, [])
        self.assertTrue(os.path.exists(self.sock))

    def test_spawns_mpv_when_there_is_no_socket(self):
        spawned = []
        self.assertEqual(player.play(self.config, "/disk/x.mp4", 0, spawn=lambda *a, **k: spawned.append(a)), "started")
        self.assertEqual(len(spawned), 1)

    def test_spawn_failure(self):
        def spawn(argv, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")
        with self.assertRaises(SyllabusError) as caught:
            player.play(self.config, "/x.mp4", 0, spawn=spawn)
        self.assertEqual(caught.exception.code, 5)
        self.assertIn("No such file or directory", str(caught.exception))

    def test_current_position(self):
        fake = FakeMpv(self.sock, {"pid": 1, "path": "/disk/x.mp4", "time-pos": 12.5})
        self.addCleanup(fake.stop)
        self.assertEqual(player.current(), ("/disk/x.mp4", 12.5))

    def test_current_without_mpv(self):
        with self.assertRaises(SyllabusError) as caught:
            player.current()
        self.assertEqual(caught.exception.code, 5)

    def test_loadfile_carries_the_web_options(self):
        fake = FakeMpv(paths.socket_path())
        self.addCleanup(fake.stop)
        config = store.load_config()
        options, secret = player.web_options(config, password="abre,sésamo")
        player.play(config, "https://www.youtube.com/watch?v=aaa", 30.0, options=options, secret=secret)
        command = fake.commands[-1]
        self.assertEqual(command[:4], ["loadfile", "https://www.youtube.com/watch?v=aaa", "replace", -1])
        self.assertTrue(command[4].startswith("start=30.000,ytdl-format="))
        # mpv is already running: the options go over its socket, not a command line.
        self.assertIn("video-password=%12%abre,sésamo", command[4])


if __name__ == "__main__":
    unittest.main()
