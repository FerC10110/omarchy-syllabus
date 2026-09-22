"""Where Syllabus keeps its files. Nothing here ever points inside the plugin folder
except the program files themselves."""
import hashlib
import os
import tempfile

APP = "syllabus"
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BIN_PATH = os.path.join(PLUGIN_DIR, "bin", "syllabus")
LUA_PATH = os.path.join(PLUGIN_DIR, "mpv", "syllabus.lua")


def _xdg(var, *fallback):
    base = os.environ.get(var) or os.path.join(os.path.expanduser("~"), *fallback)
    return os.path.join(base, APP)


def config_dir():
    return _xdg("XDG_CONFIG_HOME", ".config")


def state_dir():
    return _xdg("XDG_STATE_HOME", ".local", "state")


def cache_dir():
    return _xdg("XDG_CACHE_HOME", ".cache")


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return os.path.join(base, APP)
    return os.path.join(tempfile.gettempdir(), f"{APP}-{os.getuid()}")


def config_path():
    return os.path.join(config_dir(), "config.json")


def library_path():
    return os.path.join(config_dir(), "library.json")


def notes_dir():
    return os.path.join(config_dir(), "notes")


def note_path(course_id):
    digest = hashlib.sha1(course_id.encode("utf-8")).hexdigest()[:16]
    return os.path.join(notes_dir(), f"{digest}.md")


def state_path():
    return os.path.join(state_dir(), "state.json")


def scan_path():
    return os.path.join(cache_dir(), "scan.json")


def covers_dir():
    return os.path.join(cache_dir(), "covers")


def socket_path():
    return os.path.join(runtime_dir(), "mpv.sock")


def lock_path():
    return os.path.join(runtime_dir(), "lock")


def download_path(course_id):
    """Where a running download writes its progress; the panel reads it, nobody else."""
    name = str(course_id).replace(":", "-").replace("/", "-")
    return os.path.join(runtime_dir(), f"download-{name}.json")
