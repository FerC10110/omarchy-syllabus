"""Turns the course folders on the disk into courses and lessons. It only reads
the disk: durations come from probe.py, and everything the user decides lives
in the library, never here."""
import datetime
import os
import re
from concurrent.futures import ThreadPoolExecutor

from . import store
from .probe import ProbeError

VIDEO_EXTS = {"mp4", "mkv", "webm", "avi", "mov", "m4v", "ts"}
IMAGE_EXTS = {"webp", "jpg", "jpeg", "png"}
LAYOUTS = ("auto", "course", "collection")

_DIGITS = re.compile(r"(\d+)")
_NUMBER_PREFIX = re.compile(r"^(\d{1,3})(?!\d)\s*[-_.)]?\s*")
_OBS_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2}$")


# --- names -------------------------------------------------------------------

def ext_of(name):
    """Lowercase extension without whitespace: one real file ends in ".\\nmkv"."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return ""
    return re.sub(r"\s", "", ext).lower()


def stem_of(name):
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def clean_spaces(text):
    return re.sub(r"\s+", " ", text).strip()


def natural_key(text):
    """Sort key that puts "2_x" before "10_x" and ignores case."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
            for part in _DIGITS.split(text) if part]


def normalized(name):
    return re.sub(r"[\W_]+", "", name.casefold())


def course_title(folder_name):
    return clean_spaces(folder_name.replace("_", " "))


def lesson_title(name, course, position):
    """(title, number) for a video file. The numeric prefix goes into `number`;
    OBS timestamps, empty rests and names that only repeat the course become "Part N"."""
    stem = clean_spaces(stem_of(name).replace("_", " "))
    if _OBS_STAMP.match(stem):
        return f"Part {position}", None
    number = None
    match = _NUMBER_PREFIX.match(stem)
    if match:
        number = int(match.group(1))
        stem = stem[match.end():].strip()
    if not stem or _OBS_STAMP.match(stem) or stem.casefold() == course.casefold():
        return f"Part {number if number is not None else position}", number
    return stem, number


def auto_cover(folder_name, images):
    """The loose image whose name is the folder's name (ignoring case and punctuation), or ""."""
    key = normalized(folder_name)
    for rel in images:
        if normalized(stem_of(os.path.basename(rel))) == key:
            return rel
    return ""


# --- walking -----------------------------------------------------------------

def _entries(path, skip=()):
    """(dirs, files) in natural order, without dotfiles. An unreadable folder is empty."""
    try:
        with os.scandir(path) as it:
            entries = [e for e in it if not e.name.startswith(".")]
    except OSError:
        return [], []
    dirs, files = [], []
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry)
            elif entry.is_file():
                files.append(entry)
        except OSError:
            continue
    dirs = [d for d in dirs if os.path.realpath(d.path) not in skip]
    key = lambda e: natural_key(e.name)  # noqa: E731
    return sorted(dirs, key=key), sorted(files, key=key)


def _has_videos(path):
    dirs, files = _entries(path)
    return any(ext_of(f.name) in VIDEO_EXTS for f in files) or any(_has_videos(d.path) for d in dirs)


def _collect(base, rel_dir, group, recursive, out, skip=()):
    """Files of rel_dir first, then each subfolder; lessons in subfolders carry the subfolder as group."""
    dirs, files = _entries(os.path.join(base, rel_dir), skip)
    for f in files:
        rel = f"{rel_dir}/{f.name}"
        try:
            st = f.stat()
        except OSError:
            continue
        ext = ext_of(f.name)
        if ext in VIDEO_EXTS:
            out["lessons"].append({"relpath": rel, "name": f.name, "group": group,
                                   "size": st.st_size, "mtimeNs": st.st_mtime_ns})
        elif ext in IMAGE_EXTS:
            out["images"].append(rel)
        else:
            out["docs"].append({"relpath": rel, "name": f.name, "size": st.st_size, "ext": ext})
    if recursive:
        for d in dirs:
            _collect(base, f"{rel_dir}/{d.name}", f"{group}/{d.name}" if group else d.name, True, out, skip)


def build_course(root_id, root_path, rel_dir, folder_id, topic, root_images, recursive=True, skip=()):
    out = {"lessons": [], "docs": [], "images": []}
    _collect(root_path, rel_dir, "", recursive, out, skip)
    title = course_title(os.path.basename(rel_dir))
    lessons = []
    for position, rec in enumerate(out["lessons"], 1):
        name_title, number = lesson_title(rec["name"], title, position)
        lessons.append(dict(rec, id=f"{root_id}:{rec['relpath']}", title=name_title, number=number))
    return {"id": f"{root_id}:{rel_dir}", "rootId": root_id, "relpath": rel_dir, "folderId": folder_id,
            "title": title, "topic": topic, "lessons": lessons, "docs": out["docs"], "images": out["images"],
            "autoCover": auto_cover(os.path.basename(rel_dir), root_images)}


def walk_root(root_id, root_path, layouts, skip=()):
    """Courses under one root. `layouts` maps a top-level folder id to "course" or "collection"."""
    dirs, files = _entries(root_path, skip)
    images = [f.name for f in files if ext_of(f.name) in IMAGE_EXTS]
    courses, folders = [], {}
    for d in dirs:
        folder_id = f"{root_id}:{d.name}"
        sub_dirs, sub_files = _entries(d.path, skip)
        direct = any(ext_of(f.name) in VIDEO_EXTS for f in sub_files)
        with_videos = [s for s in sub_dirs if _has_videos(s.path)]
        if not direct and not with_videos:
            continue
        detected = "course" if direct or len(with_videos) < 2 else "collection"
        folders[folder_id] = detected
        layout = layouts.get(folder_id)
        if layout not in ("course", "collection"):
            layout = detected
        if layout == "collection":
            if direct:
                courses.append(build_course(root_id, root_path, d.name, folder_id, "", images,
                                            recursive=False, skip=skip))
            for sub in with_videos:
                courses.append(build_course(root_id, root_path, f"{d.name}/{sub.name}", folder_id,
                                            course_title(d.name), images, skip=skip))
        else:
            courses.append(build_course(root_id, root_path, d.name, folder_id, "", images, skip=skip))
    return {"courses": courses, "images": images, "folders": folders}


# --- lookups over a scan cache ----------------------------------------------

def course_index(cache):
    return {c["id"]: c for tree in (cache.get("roots") or {}).values() for c in tree.get("courses", [])}


def lesson_index(cache):
    return {l["id"]: (c["rootId"], c, l)
            for tree in (cache.get("roots") or {}).values()
            for c in tree.get("courses", []) for l in c.get("lessons", [])}


# --- scanning with durations -------------------------------------------------

def _cached_ok(cached, lesson):
    return (isinstance(cached, dict) and cached.get("size") == lesson["size"]
            and cached.get("mtimeNs") == lesson["mtimeNs"]
            and (cached.get("duration") or cached.get("error")))


def web_due(old_tree, defs, hours, force=False):
    """The web courses whose last read is older than `hours` (all of them with force)."""
    if force:
        return set(defs)
    sources = (old_tree or {}).get("sources") or {}
    limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max(1.0, float(hours)))
    due = set()
    for course_id in defs:
        stamp = (sources.get(course_id) or {}).get("fetchedAt") or ""
        try:
            when = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            due.add(course_id)
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        if when <= limit:
            due.add(course_id)
    return due


def scan_all(config, layouts, old, probe_fn, force=False, workers=4, web_defs=None, web_ids=None, build_web=None,
             prefetch=None):
    """A new scan cache. Mounted roots are walked again and only new or changed videos
    are probed (all of them with force); a root that is not mounted keeps its old tree.
    The web courses due for a refresh are read too, and folded in beside the disk roots."""
    new = {"version": 1, "roots": {}, "files": {}}
    old_roots = old.get("roots") or {}
    old_files = old.get("files") or {}
    downloads = ((config.get("web") or {}).get("downloadFolder") or "").strip()
    skip = {os.path.realpath(downloads)} if downloads else set()
    todo = []
    for root in config["roots"]:
        root_id, root_path = root["id"], root["path"]
        prefix = root_id + ":"
        if not os.path.isdir(root_path):
            if root_id in old_roots:
                new["roots"][root_id] = old_roots[root_id]
            new["files"].update({k: v for k, v in old_files.items() if k.startswith(prefix)})
            continue
        tree = walk_root(root_id, root_path, layouts, skip)
        tree["path"] = root_path
        tree["scannedAt"] = store.now_iso()
        new["roots"][root_id] = tree
        for course in tree["courses"]:
            for lesson in course["lessons"]:
                cached = old_files.get(lesson["id"])
                if not force and _cached_ok(cached, lesson):
                    new["files"][lesson["id"]] = cached
                else:
                    todo.append((lesson, os.path.join(root_path, lesson["relpath"])))

    if web_defs:
        # Imported here and not at the top: covers imports scan, so scan importing web
        # at module level would close the circle.
        from . import web
        old_web = old_roots.get("web") or {}
        hours = (config.get("web") or {}).get("refreshHours", 24)
        due = web_due(old_web, web_defs, hours, force) | (set(web_ids or ()) & set(web_defs))
        try:
            tree = (build_web or web.build_tree)(web_defs, old_web, due, prefetch=prefetch)
        except Exception as e:
            # Whatever the web step hits, the disk scan that already ran is kept.
            tree = dict(old_web) or {"courses": [], "images": [], "folders": {}, "sources": {}}
            tree["error"] = f"Could not read the web courses: {e}"
        new["roots"]["web"] = tree
        for course in tree["courses"]:
            for lesson in course["lessons"]:
                if lesson.get("duration"):
                    new["files"][lesson["id"]] = {"duration": round(float(lesson["duration"]), 3)}
                elif lesson["id"] in old_files:
                    new["files"][lesson["id"]] = old_files[lesson["id"]]

    def probe_one(item):
        lesson, path = item
        record = {"size": lesson["size"], "mtimeNs": lesson["mtimeNs"], "duration": 0.0, "error": ""}
        try:
            record["duration"] = round(float(probe_fn(path)), 3)
        except ProbeError as e:
            record["error"] = str(e) or "ffprobe failed"
        return lesson["id"], record

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for lesson_id, record in pool.map(probe_one, todo):
                new["files"][lesson_id] = record
    new["probed"] = len(todo)
    return new


def _lessons_of(cache, root_id):
    tree = (cache.get("roots") or {}).get(root_id) or {}
    return {l["id"]: l for c in tree.get("courses", []) for l in c.get("lessons", [])}


def find_moves(old, new, online_roots):
    """Videos that disappeared and reappeared elsewhere: same name and size, or
    else the only file of that size on both sides."""
    moves = {}
    for root_id in online_roots:
        before, after = _lessons_of(old, root_id), _lessons_of(new, root_id)
        gone = [l for i, l in before.items() if i not in after]
        fresh = [l for i, l in after.items() if i not in before]
        for lesson in list(gone):
            match = [f for f in fresh if f["name"] == lesson["name"] and f["size"] == lesson["size"]]
            if len(match) == 1:
                moves[lesson["id"]] = match[0]["id"]
                fresh.remove(match[0])
                gone.remove(lesson)
        for lesson in list(gone):
            same_size_gone = [g for g in gone if g["size"] == lesson["size"]]
            match = [f for f in fresh if f["size"] == lesson["size"]]
            if len(same_size_gone) == 1 and len(match) == 1:
                moves[lesson["id"]] = match[0]["id"]
                fresh.remove(match[0])
    return moves


def apply_moves(library, state, moves):
    """Carry titles, bookmarks, progress and order over to the new ids."""
    for old_id, new_id in moves.items():
        for doc in (library["lessons"], state["lessons"]):
            if old_id in doc and new_id not in doc:
                doc[new_id] = doc.pop(old_id)
        for course in library["courses"].values():
            order = course.get("order")
            if isinstance(order, list):
                course["order"] = [new_id if x == old_id else x for x in order]
        last = state.get("last")
        if isinstance(last, dict) and last.get("lessonId") == old_id:
            last["lessonId"] = new_id
    return len(moves)
