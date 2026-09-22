"""Downloading a web course: where every file goes, what is already there, and the
registry in state.json that lets the panel and mpv find it."""
import glob
import os
import re
import signal
import subprocess

from . import paths, player, scan, store, web
from .errors import UNKNOWN, SyllabusError

VIDEO_EXTS = ("mkv", "mp4", "webm", "m4v", "mov")
_UNSAFE = re.compile(r"[\x00-\x1f/]+")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def safe_name(text, limit=120):
    """A file name that is only a file name: no slashes, no control characters, no run of two or
    more dots that could read as "..", and not endless."""
    cleaned = re.sub(r"\s+", " ", _UNSAFE.sub(" ", str(text or ""))).strip().strip(".")
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    return cleaned[:limit].strip() or "untitled"


def safe_id(text, limit=40):
    """A site name or a video id as it can appear in a file name: letters, digits, - and _."""
    return _ID_UNSAFE.sub("_", str(text or "")).strip("_")[:limit] or "x"


def course_folder(config, title):
    return os.path.join(config["web"]["downloadFolder"], safe_name(title))


def file_stem(position, lesson):
    return (f"{position:02d} - {safe_name(lesson['title'])} "
            f"[{safe_id(lesson.get('site'))}-{safe_id(lesson.get('videoId'))}]")


def existing_file(folder, stem):
    """The video already sitting there, whatever extension yt-dlp gave it."""
    for path in sorted(glob.glob(glob.escape(os.path.join(folder, stem)) + ".*")):
        if path.rsplit(".", 1)[-1].lower() in VIDEO_EXTS:
            return path
    return ""


def ytdlp_args(config, url, template, password=""):
    """The same format mpv streams with, plus the subtitles baked into the file."""
    web_config = config["web"]
    args = ["-f", player.format_selector(web_config) or "bv*+ba/b", "-o", template,
            "--no-playlist", "--continue", "--no-progress"]
    languages = [l for l in (web_config.get("subtitleLanguages") or []) if isinstance(l, str) and l]
    if languages:
        args += ["--write-subs", "--sub-langs", ",".join(languages), "--embed-subs",
                 "--merge-output-format", "mkv"]
        if web_config.get("autoSubtitles"):
            args.append("--write-auto-subs")
    if password:
        args += ["--video-password", password]
    return args + [url]


def plan(config, cache, library, state, course_id):
    """The folder and the videos of a course that are not on disk yet, in order."""
    course = scan.course_index(cache).get(course_id)
    if course is None or course.get("rootId") != "web":
        raise SyllabusError("Unknown web course", UNKNOWN)
    title = (library["courses"].get(course_id) or {}).get("title") or course["title"]
    folder = course_folder(config, title)
    saved = state.get("downloads") or {}
    items = []
    for position, lesson in enumerate(course["lessons"], 1):
        if not lesson.get("available", True):
            continue
        record = saved.get(lesson["id"]) or {}
        if record.get("path") and os.path.isfile(record["path"]):
            continue
        stem = file_stem(position, lesson)
        items.append({"lessonId": lesson["id"], "url": lesson["url"], "stem": stem,
                      "template": os.path.join(folder, stem + ".%(ext)s"),
                      "path": existing_file(folder, stem),
                      "password": web.password_for(library["web"], course_id, lesson)})
    return folder, items


def _write_progress(path, data):
    store.write_json(path, data)


def _register(lesson_id, path):
    course_id = lesson_id.split("/", 1)[0]
    with store.transaction() as docs:
        # The course may have been removed (or its downloads deleted) while this worker
        # was still running: a course no one can reach any more gets no new registry entry.
        if course_id not in docs.library["web"]:
            return
        docs.state["downloads"][lesson_id] = {"path": path, "size": int(os.path.getsize(path)),
                                              "at": store.now_iso()}


def _download(config, item, spawn):
    args = [web.ytdlp_bin()] + ytdlp_args(config, item["url"], item["template"], item["password"])
    try:
        done = spawn(args, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return existing_file(os.path.dirname(item["template"]), item["stem"])


def run(course_id, spawn=subprocess.run):
    """Download what the course is missing, one video at a time. Every finished video is
    registered right away, so the panel sees the progress through state.json."""
    config, cache = store.load_config(), store.load_scan()
    library, state = store.load_library(), store.load_state()
    folder, items = plan(config, cache, library, state, course_id)
    progress_path = paths.download_path(course_id)
    os.makedirs(folder, exist_ok=True)
    done, failed = 0, []
    try:
        for index, item in enumerate(items):
            _write_progress(progress_path, {"courseId": course_id, "pid": os.getpid(), "total": len(items),
                                            "done": index, "current": item["stem"], "failed": failed})
            path = item["path"] or _download(config, item, spawn)
            if not path:
                failed.append(item["stem"])
                continue
            _register(item["lessonId"], path)
            done += 1
    finally:
        try:
            os.unlink(progress_path)
        except OSError:
            pass
    return {"courseId": course_id, "total": len(items), "done": done, "failed": failed}


def _is_worker(pid, course_id):
    """Whether that pid is really the worker we started for this course.
    A pid can be recycled, so the process's own cmdline has to still name it."""
    if not isinstance(pid, int):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return course_id in f.read().decode("utf-8", "replace")
    except OSError:
        return False


def progress(course_id):
    """What a running download is doing, or None.

    A worker killed with SIGTERM never runs its own cleanup, so a leftover file
    here would otherwise keep the course "downloading" for the rest of the session."""
    path = paths.download_path(course_id)
    try:
        data = store.read_json(path, None)
    except SyllabusError:
        # A download's progress is decoration: a file left half-written by a
        # worker that was killed must not take the whole library down with it.
        data = None
    if isinstance(data, dict) and _is_worker(data.get("pid"), course_id):
        return data
    try:
        os.unlink(path)
    except OSError:
        pass
    return None


def stop(course_id):
    """Ask a running download to stop; what it already got is kept and resumed next time.
    A pid can be recycled, so this only signals a process whose own cmdline still names the
    worker it was started as: `[BIN_PATH, "download", course_id, "--run"]`."""
    running = progress(course_id)
    pid = (running or {}).get("pid")
    if not _is_worker(pid, course_id):
        return False
    try:
        group = os.getpgid(pid)
    except OSError:
        return False
    try:
        # The worker starts its own session, so yt-dlp is in its group: signalling the
        # group is what stops the download itself and not just its bookkeeping.
        if group == pid and group != os.getpgid(0):
            os.killpg(group, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    # SIGTERM never lets the worker reach its own `finally`, so the panel would
    # otherwise keep seeing this course as downloading until the next stale read.
    try:
        os.unlink(paths.download_path(course_id))
    except OSError:
        pass
    return True


def delete_files(config, state, lesson_ids):
    """Forget the given lessons' downloads and delete their files, but only when a file is
    registered under the download folder: a record whose path escapes it (a symlink, or a
    hand-edited state.json) is dropped from the registry without ever being touched on disk."""
    base = os.path.realpath(config["web"]["downloadFolder"])
    downloads_map = state.get("downloads") or {}
    removed, freed = 0, 0
    for lesson_id in list(lesson_ids):
        record = downloads_map.get(lesson_id)
        if not isinstance(record, dict):
            continue
        path = str(record.get("path") or "")
        real = os.path.realpath(path)
        inside = bool(path) and (real == base or real.startswith(base + os.sep))
        if inside and not os.path.islink(path) and os.path.isfile(path):
            try:
                freed += os.path.getsize(path)
                os.unlink(path)
                removed += 1
            except OSError:
                pass
        downloads_map.pop(lesson_id, None)
    return {"removed": removed, "freed": freed}
