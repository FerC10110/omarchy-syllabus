"""Shared test setup: every test runs against its own XDG folders, never the user's."""
import contextlib
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
# The shell reloads the plugin when anything in its folder changes.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(PLUGIN, "lib"))

ENV_KEYS = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
            "SYLLABUS_FFPROBE", "SYLLABUS_READILY_BIN", "FAKE_READILY_LOG",
            "SYLLABUS_YTDLP", "SYLLABUS_FAKE_YTDLP")


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="syllabus-test-")
        self._saved_env = {key: os.environ.get(key) for key in ENV_KEYS}
        for key, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                         ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
            path = os.path.join(self.tmp, sub)
            os.makedirs(path)
            os.environ[key] = path
        for key in ("SYLLABUS_FFPROBE", "FAKE_READILY_LOG", "SYLLABUS_YTDLP", "SYLLABUS_FAKE_YTDLP"):
            os.environ.pop(key, None)
        # Point at a path that does not exist rather than unsetting it: unset would let
        # find_binary() fall back to the user's real Readily install (and its real vault
        # and clipboard). A test must call install_fake_readily() to get a working binary.
        os.environ["SYLLABUS_READILY_BIN"] = os.path.join(self.tmp, "no-readily")

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)


def make_tree(root, files):
    """Create files under root. A number becomes "duration=<n>", which the fake ffprobe reads."""
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(content, (int, float)) and not isinstance(content, bool):
                f.write(f"duration={content}")
            else:
                f.write(str(content))


FAKE_FFPROBE = """#!/usr/bin/env python3
import sys
path = sys.argv[-1]
with open(path, encoding="utf-8", errors="replace") as f:
    text = f.read()
if text.startswith("duration="):
    print(text.split("=", 1)[1].strip())
    sys.exit(0)
print(path + ": Invalid data found when processing input", file=sys.stderr)
sys.exit(1)
"""


def install_fake_ffprobe(tmp):
    path = os.path.join(tmp, "fake-ffprobe")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_FFPROBE)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    os.environ["SYLLABUS_FFPROBE"] = path
    return path


@contextlib.contextmanager
def local_tz(name):
    """Run a block with the process in another local time zone."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()


FAKE_YTDLP = '''#!/usr/bin/env python3
"""A yt-dlp that answers from files instead of the network.

SYLLABUS_FAKE_YTDLP is a folder. Every call is appended to calls.log, and the
answer for a url is <folder>/<sha1(url)[:16]>.json:
  {"__error__": "text"}  -> printed on stderr, exit 1
  {"__file__": "body"}   -> writes the -o target (a download) and exits 0
  anything else          -> printed on stdout, like -J does
A url with no file fails the way yt-dlp fails on a dead link."""
import hashlib, json, os, sys

args = sys.argv[1:]
folder = os.environ["SYLLABUS_FAKE_YTDLP"]
url = args[-1]
config = sys.stdin.read() if "--config-locations" in args else ""
with open(os.path.join(folder, "calls.log"), "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
with open(os.path.join(folder, "stdin.log"), "a", encoding="utf-8") as log:
    log.write(json.dumps(config) + "\\n")
path = os.path.join(folder, hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".json")
if not os.path.exists(path):
    print("ERROR: [generic] Unable to download webpage: <urlopen error>", file=sys.stderr)
    sys.exit(1)
with open(path, encoding="utf-8") as f:
    data = json.load(f)
if "__error__" in data:
    print(data["__error__"], file=sys.stderr)
    sys.exit(1)
if "__flood__" in data:
    chunk = "x" * (1 << 16)
    while True:
        sys.stdout.write(chunk)
        sys.stdout.flush()
if "__file__" in data:
    template = args[args.index("-o") + 1]
    target = template.replace("%(ext)s", data.get("__ext__", "mkv"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as out:
        out.write(data["__file__"])
    sys.exit(0)
print(json.dumps(data))
'''


def install_fake_ytdlp(tmp):
    """A fake yt-dlp on SYLLABUS_YTDLP; returns the folder its answers live in."""
    folder = os.path.join(tmp, "ytdlp")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(tmp, "fake-ytdlp")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_YTDLP)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    os.environ["SYLLABUS_YTDLP"] = path
    os.environ["SYLLABUS_FAKE_YTDLP"] = folder
    return folder


def ytdlp_answer(folder, url, data):
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".json"
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(data, f)


def ytdlp_stdins(folder):
    """What each call read on stdin: where a password travels now."""
    path = os.path.join(folder, "stdin.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ytdlp_calls(folder):
    path = os.path.join(folder, "calls.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
