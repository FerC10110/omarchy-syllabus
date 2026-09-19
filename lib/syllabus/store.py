"""config.json, library.json, state.json and the scan cache: how Syllabus reads
them, and how it writes them without ever leaving half a file or losing a write."""
import contextlib
import copy
import datetime
import fcntl
import json
import os
import tempfile

from . import paths
from .errors import GENERAL, SyllabusError

DEFAULT_ROOT = "~/Videos/Courses"
DEFAULT_CONFIG = {
    "version": 1,
    "roots": [{"id": "main", "path": DEFAULT_ROOT}],
    "player": {"command": "mpv", "args": []},
    "seenThreshold": 0.9,
    "resumeRewind": 5,
    "reportSeconds": 30,
    "streakMinutes": 10,
    "readily": {"enabled": True, "section": "Cursos"},
}


def now_iso(moment=None):
    moment = moment or datetime.datetime.now(datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def local_day(moment=None):
    """The study day a moment belongs to, in the user's local time zone."""
    moment = moment or datetime.datetime.now(datetime.timezone.utc)
    return moment.astimezone().date().isoformat()


# --- files -------------------------------------------------------------------

def read_json(path, empty):
    """The parsed file, or `empty` when it does not exist. A file that is not a JSON object is an error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return copy.deepcopy(empty)
    except (OSError, ValueError) as e:
        raise SyllabusError(f"Could not read {os.path.basename(path)}: {e}", GENERAL)
    if not isinstance(data, dict):
        raise SyllabusError(f"Could not read {os.path.basename(path)}: not an object", GENERAL)
    return data


def write_text(path, text):
    """Write through a temp file in the same folder, so a crash never leaves half a file."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# --- config ------------------------------------------------------------------

def _kind(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    for name, types in (("str", str), ("list", list), ("dict", dict)):
        if isinstance(value, types):
            return name
    return "other"


def _merge(defaults, data):
    """Defaults overlaid with the values of `data` that have the same kind; unknown keys are dropped."""
    out = copy.deepcopy(defaults)
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        if key not in out:
            continue
        if isinstance(out[key], dict):
            out[key] = _merge(out[key], value)
        elif _kind(out[key]) == _kind(value):
            out[key] = copy.deepcopy(value)
    return out


def _valid_root(root):
    return (isinstance(root, dict) and isinstance(root.get("id"), str) and root["id"] != ""
            and ":" not in root["id"] and isinstance(root.get("path"), str) and root["path"] != "")


def load_config():
    config = _merge(DEFAULT_CONFIG, read_json(paths.config_path(), {}))
    config["roots"] = [{"id": r["id"], "path": os.path.expanduser(r["path"]).rstrip("/") or "/"}
                       for r in config["roots"] if _valid_root(r)]
    config["player"]["args"] = [a for a in config["player"]["args"] if isinstance(a, str)]
    return config


def save_config(config):
    write_json(paths.config_path(), config)


# --- library -----------------------------------------------------------------

def empty_library():
    return {"version": 1, "folders": {}, "courses": {}, "lessons": {}, "roadmaps": []}


def load_library():
    data = read_json(paths.library_path(), {})
    library = empty_library()
    for key in ("folders", "courses", "lessons"):
        if isinstance(data.get(key), dict):
            library[key] = {k: v for k, v in data[key].items() if isinstance(v, dict)}
    if isinstance(data.get("roadmaps"), list):
        library["roadmaps"] = [r for r in data["roadmaps"] if isinstance(r, dict) and isinstance(r.get("id"), str)]
    return library


def save_library(library):
    write_json(paths.library_path(), library)


# --- state -------------------------------------------------------------------

def empty_state():
    return {"version": 1, "lessons": {}, "last": None, "days": {}, "window": {}}


def _window(data):
    """The panel's size and pin, keeping only well-formed values."""
    if not isinstance(data, dict):
        return {}
    kept = {k: data[k] for k in ("width", "height")
            if isinstance(data.get(k), (int, float)) and not isinstance(data.get(k), bool)}
    if isinstance(data.get("pinned"), bool):
        kept["pinned"] = data["pinned"]
    return kept


def load_state():
    data = read_json(paths.state_path(), {})
    state = empty_state()
    if isinstance(data.get("lessons"), dict):
        state["lessons"] = {k: v for k, v in data["lessons"].items() if isinstance(v, dict)}
    last = data.get("last")
    if isinstance(last, dict) and isinstance(last.get("lessonId"), str):
        state["last"] = last
    if isinstance(data.get("days"), dict):
        state["days"] = {k: v for k, v in data["days"].items() if isinstance(v, dict)}
    state["window"] = _window(data.get("window"))
    return state


def save_state(state):
    write_json(paths.state_path(), state)


# --- scan cache --------------------------------------------------------------

def empty_scan():
    return {"version": 1, "roots": {}, "files": {}}


def load_scan():
    data = read_json(paths.scan_path(), {})
    cache = empty_scan()
    if isinstance(data.get("roots"), dict):
        cache["roots"] = {k: v for k, v in data["roots"].items() if isinstance(v, dict)}
    if isinstance(data.get("files"), dict):
        cache["files"] = {k: v for k, v in data["files"].items() if isinstance(v, dict)}
    return cache


def save_scan(cache):
    write_json(paths.scan_path(), cache)


# --- locking -----------------------------------------------------------------

@contextlib.contextmanager
def locked():
    """One writer at a time across the panel, the mpv reports and the CLI."""
    os.makedirs(paths.runtime_dir(), exist_ok=True)
    with open(paths.lock_path(), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def ensure_files():
    """Create state.json and library.json when missing: the window watches both,
    and a watched file that does not exist yet never reports changes."""
    if os.path.exists(paths.state_path()) and os.path.exists(paths.library_path()):
        return
    with locked():
        if not os.path.exists(paths.state_path()):
            save_state(empty_state())
        if not os.path.exists(paths.library_path()):
            save_library(empty_library())


class Docs:
    """Config, library and state loaded together; save() writes back only what changed."""

    def __init__(self):
        self.config = load_config()
        self.library = load_library()
        self.state = load_state()
        self._before = self._dump()

    def _dump(self):
        return tuple(json.dumps(d, sort_keys=True) for d in (self.config, self.library, self.state))

    def save(self):
        after = self._dump()
        if after[0] != self._before[0]:
            save_config(self.config)
        if after[1] != self._before[1]:
            save_library(self.library)
        if after[2] != self._before[2]:
            save_state(self.state)
        self._before = after


@contextlib.contextmanager
def transaction():
    """Load, hand out, save — under the lock. An exception discards every change."""
    with locked():
        docs = Docs()
        yield docs
        docs.save()
