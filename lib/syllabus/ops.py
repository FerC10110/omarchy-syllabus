"""Every change the window can make, as one table of named operations on the
user's documents. Each op validates its fields and raises SyllabusError with
USAGE (bad input) or UNKNOWN (an id that does not exist)."""
import os
import re
import secrets

from . import covers, downloads, paths, progress, readily, scan, store, view as view_mod
from .errors import NOTE_CHANGED, READILY, UNKNOWN, USAGE, SyllabusError

SECTION_RE = re.compile(r"^[^\W_][\w -]{0,63}$")
URL_RE = re.compile(r"^https?://\S+$")


def new_id():
    return secrets.token_hex(4)


class Context:
    """What the ops check ids against: the view of the documents as they are now."""

    def __init__(self, docs, cache):
        self.cache = cache
        self.view = view_mod.build_view(docs.config, docs.library, docs.state, cache)
        self.courses = {c["id"]: c for c in self.view["courses"]}
        self.lessons = {l["id"]: l for c in self.view["courses"] for l in c["lessons"]}
        self.folders = set(self.view["folders"])


# --- field helpers -----------------------------------------------------------

def _str(p, key, required=False):
    value = p.get(key)
    if value is None:
        if required:
            raise SyllabusError(f"Missing {key}", USAGE)
        return None
    if not isinstance(value, str):
        raise SyllabusError(f"{key} must be text", USAGE)
    value = value.strip()
    if required and not value:
        raise SyllabusError(f"{key} cannot be empty", USAGE)
    return value


def _bool(p, key):
    value = p.get(key)
    if not isinstance(value, bool):
        raise SyllabusError(f"{key} must be true or false", USAGE)
    return value


def _number(p, key, low, high):
    value = p.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SyllabusError(f"{key} must be a number", USAGE)
    if not low <= value <= high:
        raise SyllabusError(f"{key} must be between {low} and {high}", USAGE)
    return value


def _delta(p):
    value = p.get("delta")
    if isinstance(value, bool) or value not in (-1, 1):
        raise SyllabusError("delta must be -1 or 1", USAGE)
    return value


def _find(items, item_id, what):
    for i, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == item_id:
            return i
    raise SyllabusError(f"Unknown {what}", UNKNOWN)


def _move(items, index, delta):
    target = index + delta
    if 0 <= target < len(items):
        items.insert(target, items.pop(index))


def _set_tag(target, p):
    raw = _str(p, "readilyTag") or ""
    tag = readily.normalize_tag(raw) if raw else ""
    if raw and not tag:
        raise SyllabusError("That is not a valid Readily tag", USAGE)
    if tag:
        target["readilyTag"] = tag
    else:
        target.pop("readilyTag", None)


def _set_title(target, p):
    title = _str(p, "title") or ""
    if title:
        target["title"] = title
    else:
        target.pop("title", None)


# --- owners ------------------------------------------------------------------

def _course(docs, ctx, course_id):
    if course_id not in ctx.courses:
        raise SyllabusError("Unknown course", UNKNOWN)
    return docs.library["courses"].setdefault(course_id, {})


def _lesson(docs, ctx, lesson_id):
    if lesson_id not in ctx.lessons:
        raise SyllabusError("Unknown video", UNKNOWN)
    return docs.library["lessons"].setdefault(lesson_id, {})


def _roadmap(docs, roadmap_id):
    roadmaps = docs.library["roadmaps"]
    return roadmaps[_find(roadmaps, roadmap_id, "roadmap")]


def _stage(roadmap, stage_id):
    stages = roadmap.setdefault("stages", [])
    return stages[_find(stages, stage_id, "stage")]


def _owner(docs, ctx, p, allow_stage=True):
    owner = p.get("owner")
    if not isinstance(owner, dict):
        raise SyllabusError("Missing owner", USAGE)
    kind = owner.get("kind")
    if kind == "course":
        return _course(docs, ctx, _str(owner, "id", True))
    if kind == "roadmap":
        return _roadmap(docs, _str(owner, "id", True))
    if kind == "stage" and allow_stage:
        return _stage(_roadmap(docs, _str(owner, "roadmapId", True)), _str(owner, "id", True))
    raise SyllabusError("That cannot hold this", USAGE)


def owner_tag(built_view, owner):
    """The Readily tag of a course or roadmap: the saved one, or one derived from its title."""
    kind, owner_id = owner.get("kind"), owner.get("id")
    if kind == "course":
        course = next((c for c in built_view["courses"] if c["id"] == owner_id), None)
        if course is None:
            raise SyllabusError("Unknown course", UNKNOWN)
        return course["readilyTag"] or readily.course_tag(course["title"])
    if kind == "roadmap":
        roadmap = next((r for r in built_view["roadmaps"] if r["id"] == owner_id), None)
        if roadmap is None:
            raise SyllabusError("Unknown roadmap", UNKNOWN)
        return roadmap["readilyTag"] or readily.roadmap_tag(roadmap["title"])
    raise SyllabusError("Only courses and roadmaps have a Readily tag", USAGE)


# --- courses and lessons -----------------------------------------------------

def op_course_set(docs, ctx, p):
    course = _course(docs, ctx, _str(p, "courseId", True))
    if "title" in p:
        _set_title(course, p)
    if "topic" in p:
        topic = _str(p, "topic") or ""
        if topic:
            course["topic"] = topic
        else:
            course.pop("topic", None)
    if "readilyTag" in p:
        _set_tag(course, p)


def op_cover_set(docs, ctx, p):
    course = _course(docs, ctx, _str(p, "courseId", True))
    source = _str(p, "source") or ""
    if not source:
        course.pop("cover", None)
        return
    if scan.ext_of(source) not in scan.IMAGE_EXTS or not os.path.isfile(source):
        raise SyllabusError("That is not an image", USAGE)
    course["cover"] = covers.cache_cover(source)


def op_folder_layout(docs, ctx, p):
    folder_id = _str(p, "folderId", True)
    if folder_id not in ctx.folders:
        raise SyllabusError("Unknown folder", UNKNOWN)
    layout = _str(p, "layout", True)
    if layout not in scan.LAYOUTS:
        raise SyllabusError("layout must be auto, course or collection", USAGE)
    if layout == "auto":
        docs.library["folders"].pop(folder_id, None)
    else:
        docs.library["folders"][folder_id] = {"layout": layout}
    return {"rescan": True}


def _web_definition(docs, course_id):
    definition = docs.library["web"].get(course_id)
    if not isinstance(definition, dict):
        raise SyllabusError("Unknown web course", UNKNOWN)
    return definition


def op_web_remove(docs, ctx, p):
    """A whole web course: its sources, its downloaded files and everything on it."""
    course_id = _str(p, "courseId", True)
    _web_definition(docs, course_id)
    # Stop the worker before anything is deleted: left running, it would keep
    # writing files and re-registering downloads for a course that no longer exists.
    downloads.stop(course_id)
    prefix = course_id + "/"
    ours = [k for k in docs.state.get("downloads", {}) if k.startswith(prefix)]
    removed = downloads.delete_files(docs.config, docs.state, ours)
    docs.library["web"].pop(course_id, None)
    docs.library["courses"].pop(course_id, None)
    for table in (docs.library["lessons"], docs.state["lessons"]):
        for lesson_id in [k for k in table if k.startswith(prefix)]:
            table.pop(lesson_id, None)
    if str(((docs.state.get("last") or {}).get("lessonId") or "")).startswith(prefix):
        docs.state["last"] = None
    for roadmap in docs.library["roadmaps"]:
        for stage in roadmap.get("stages", []):
            stage["courseIds"] = [c for c in stage.get("courseIds", []) if c != course_id]
    try:
        os.unlink(paths.note_path(course_id))
    except OSError:
        pass
    return {"rescan": True, "removed": removed["removed"]}


def op_web_remove_video(docs, ctx, p):
    """One of the loose videos added to a web course; the playlist's videos are not ours to drop."""
    course_id = _str(p, "courseId", True)
    lesson_id = _str(p, "lessonId", True)
    definition = _web_definition(docs, course_id)
    entry = scan.lesson_index(ctx.cache).get(lesson_id)
    if entry is None or entry[1]["id"] != course_id:
        raise SyllabusError("Unknown video", UNKNOWN)
    lesson = entry[2]
    if lesson.get("source") != "video":
        raise SyllabusError("That video comes from the playlist, not from a link you added", USAGE)
    definition["sources"] = [s for s in definition.get("sources", []) if s.get("url") != lesson.get("url")]
    downloads.delete_files(docs.config, docs.state, [lesson_id])
    docs.library["lessons"].pop(lesson_id, None)
    docs.state["lessons"].pop(lesson_id, None)
    over = docs.library["courses"].get(course_id) or {}
    if isinstance(over.get("order"), list):
        over["order"] = [i for i in over["order"] if i != lesson_id]
    return {"rescan": True, "webIds": [course_id]}


def op_lesson_set(docs, ctx, p):
    lesson = _lesson(docs, ctx, _str(p, "lessonId", True))
    if "title" in p:
        _set_title(lesson, p)
    if "hidden" in p:
        lesson["hidden"] = _bool(p, "hidden")


def op_lesson_move(docs, ctx, p):
    course_id = _str(p, "courseId", True)
    course = ctx.courses.get(course_id)
    if course is None:
        raise SyllabusError("Unknown course", UNKNOWN)
    lesson_id = _str(p, "lessonId", True)
    delta = _delta(p)
    ids = [l["id"] for l in course["lessons"]]
    visible = [l["id"] for l in course["lessons"] if not l["hidden"]]
    if lesson_id not in visible:
        raise SyllabusError("Unknown video", UNKNOWN)
    target = visible.index(lesson_id) + delta
    if not 0 <= target < len(visible):
        return
    neighbor = visible[target]
    # Jump over hidden lessons: land right before/after the next visible one.
    ids.remove(lesson_id)
    ids.insert(ids.index(neighbor) + (1 if delta > 0 else 0), lesson_id)
    _course(docs, ctx, course_id)["order"] = ids


def op_seen_set(docs, ctx, p):
    lesson_id = _str(p, "lessonId", True)
    if lesson_id not in ctx.lessons:
        raise SyllabusError("Unknown video", UNKNOWN)
    progress.set_seen(docs.state, lesson_id, _bool(p, "seen"))


def add_bookmark(library, lesson_id, at, text):
    if at < 0:
        raise SyllabusError("at must be 0 or more", USAGE)
    mark = {"id": new_id(), "at": round(float(at), 3), "text": (text or "").strip(), "createdAt": store.now_iso()}
    library["lessons"].setdefault(lesson_id, {}).setdefault("bookmarks", []).append(mark)
    return mark


def op_bookmark_add(docs, ctx, p):
    lesson_id = _str(p, "lessonId", True)
    if lesson_id not in ctx.lessons:
        raise SyllabusError("Unknown video", UNKNOWN)
    mark = add_bookmark(docs.library, lesson_id, _number(p, "at", -1e12, 1e12), _str(p, "text") or "")
    return {"id": mark["id"]}


def _bookmarks(docs, ctx, p):
    return _lesson(docs, ctx, _str(p, "lessonId", True)).setdefault("bookmarks", [])


def op_bookmark_set(docs, ctx, p):
    marks = _bookmarks(docs, ctx, p)
    mark = marks[_find(marks, _str(p, "bookmarkId", True), "bookmark")]
    if "at" in p:
        mark["at"] = round(float(_number(p, "at", 0, 1e12)), 3)
    if "text" in p:
        mark["text"] = _str(p, "text") or ""


def op_bookmark_remove(docs, ctx, p):
    marks = _bookmarks(docs, ctx, p)
    marks.pop(_find(marks, _str(p, "bookmarkId", True), "bookmark"))


def read_note(course_id):
    """A course's note as it is on disk: "" when there is none."""
    try:
        with open(paths.note_path(course_id), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _note_file(text):
    """What a note file holds once `text` is saved: nothing for blank text, else a final newline."""
    if not text.strip():
        return ""
    return text if text.endswith("\n") else text + "\n"


def op_note_set(docs, ctx, p):
    course_id = _str(p, "courseId", True)
    if course_id not in ctx.courses:
        raise SyllabusError("Unknown course", UNKNOWN)
    text = p.get("text")
    if not isinstance(text, str):
        raise SyllabusError("text must be text", USAGE)
    base = p.get("base")
    if base is not None and not isinstance(base, str):
        raise SyllabusError("base must be text", USAGE)
    # `base` is the text the window's draft started from. If the file no longer
    # holds it (edited in an editor, say), saving would throw those edits away.
    if base is not None and _note_file(base) != _note_file(read_note(course_id)):
        raise SyllabusError("The note changed outside the window; what you typed here was not saved",
                            USAGE, NOTE_CHANGED)
    path = paths.note_path(course_id)
    content = _note_file(text)
    if content:
        store.write_text(path, content)
    elif os.path.exists(path):
        os.unlink(path)


# --- roadmaps and stages -----------------------------------------------------

def op_roadmap_add(docs, ctx, p):
    roadmap = {"id": new_id(), "title": _str(p, "title", True), "tasks": [], "links": [], "stages": []}
    docs.library["roadmaps"].append(roadmap)
    return {"id": roadmap["id"]}


def op_roadmap_set(docs, ctx, p):
    roadmap = _roadmap(docs, _str(p, "roadmapId", True))
    if "title" in p:
        roadmap["title"] = _str(p, "title", True)
    if "readilyTag" in p:
        _set_tag(roadmap, p)


def op_roadmap_remove(docs, ctx, p):
    roadmaps = docs.library["roadmaps"]
    roadmaps.pop(_find(roadmaps, _str(p, "roadmapId", True), "roadmap"))


def op_roadmap_move(docs, ctx, p):
    roadmaps = docs.library["roadmaps"]
    _move(roadmaps, _find(roadmaps, _str(p, "roadmapId", True), "roadmap"), _delta(p))


def op_stage_add(docs, ctx, p):
    roadmap = _roadmap(docs, _str(p, "roadmapId", True))
    stage = {"id": new_id(), "title": _str(p, "title", True), "courseIds": [], "tasks": []}
    roadmap.setdefault("stages", []).append(stage)
    return {"id": stage["id"]}


def op_stage_set(docs, ctx, p):
    stage = _stage(_roadmap(docs, _str(p, "roadmapId", True)), _str(p, "stageId", True))
    stage["title"] = _str(p, "title", True)


def op_stage_remove(docs, ctx, p):
    roadmap = _roadmap(docs, _str(p, "roadmapId", True))
    stages = roadmap.setdefault("stages", [])
    stages.pop(_find(stages, _str(p, "stageId", True), "stage"))


def op_stage_move(docs, ctx, p):
    roadmap = _roadmap(docs, _str(p, "roadmapId", True))
    stages = roadmap.setdefault("stages", [])
    index = _find(stages, _str(p, "stageId", True), "stage")
    _move(stages, index, _delta(p))


def _stage_courses(docs, p):
    stage = _stage(_roadmap(docs, _str(p, "roadmapId", True)), _str(p, "stageId", True))
    return stage.setdefault("courseIds", [])


def op_stage_add_course(docs, ctx, p):
    course_id = _str(p, "courseId", True)
    if course_id not in ctx.courses:
        raise SyllabusError("Unknown course", UNKNOWN)
    ids = _stage_courses(docs, p)
    if course_id not in ids:
        ids.append(course_id)


def op_stage_remove_course(docs, ctx, p):
    ids = _stage_courses(docs, p)
    course_id = _str(p, "courseId", True)
    if course_id not in ids:
        raise SyllabusError("That course is not in this stage", UNKNOWN)
    ids.remove(course_id)


def op_stage_move_course(docs, ctx, p):
    ids = _stage_courses(docs, p)
    course_id = _str(p, "courseId", True)
    if course_id not in ids:
        raise SyllabusError("That course is not in this stage", UNKNOWN)
    _move(ids, ids.index(course_id), _delta(p))


# --- tasks and links ---------------------------------------------------------

def _tasks(docs, ctx, p):
    return _owner(docs, ctx, p).setdefault("tasks", [])


def op_task_add(docs, ctx, p):
    task = {"id": new_id(), "text": _str(p, "text", True), "done": False, "doneAt": None}
    _tasks(docs, ctx, p).append(task)
    return {"id": task["id"]}


def op_task_set(docs, ctx, p):
    tasks = _tasks(docs, ctx, p)
    task = tasks[_find(tasks, _str(p, "taskId", True), "task")]
    if "text" in p:
        task["text"] = _str(p, "text", True)
    if "done" in p:
        task["done"] = _bool(p, "done")
        task["doneAt"] = store.now_iso() if task["done"] else None


def op_task_remove(docs, ctx, p):
    tasks = _tasks(docs, ctx, p)
    tasks.pop(_find(tasks, _str(p, "taskId", True), "task"))


def op_task_move(docs, ctx, p):
    tasks = _tasks(docs, ctx, p)
    _move(tasks, _find(tasks, _str(p, "taskId", True), "task"), _delta(p))


def _links(docs, ctx, p):
    return _owner(docs, ctx, p, allow_stage=False).setdefault("links", [])


def _set_content(link, p):
    content = p.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SyllabusError("Nothing to save", USAGE)
    kind = p.get("kind")
    if kind not in (None, "link", "snippet"):
        raise SyllabusError("kind must be link or snippet", USAGE)
    kind = kind or ("link" if URL_RE.match(content.strip()) else "snippet")
    link.pop("url", None)
    link.pop("text", None)
    link["kind"] = kind
    if kind == "link":
        link["url"] = content.strip()
    else:
        link["text"] = content.strip("\n").rstrip()


def op_link_add(docs, ctx, p):
    links = _links(docs, ctx, p)
    link = {"id": new_id(), "title": _str(p, "title") or "", "createdAt": store.now_iso()}
    _set_content(link, p)
    if p.get("truncated") is True:
        link["truncated"] = True
    links.append(link)
    return {"id": link["id"]}


def op_link_set(docs, ctx, p):
    links = _links(docs, ctx, p)
    link = links[_find(links, _str(p, "linkId", True), "link")]
    if "title" in p:
        link["title"] = _str(p, "title") or ""
    if "content" in p:
        before = link.get("url") or link.get("text")
        _set_content(link, p)
        # The window sends the content back even when only the title changed:
        # an import cut short by Readily stays marked until its text changes.
        if (link.get("url") or link.get("text")) != before:
            link.pop("truncated", None)


def op_link_remove(docs, ctx, p):
    links = _links(docs, ctx, p)
    links.pop(_find(links, _str(p, "linkId", True), "link"))


def op_link_move(docs, ctx, p):
    links = _links(docs, ctx, p)
    _move(links, _find(links, _str(p, "linkId", True), "link"), _delta(p))


# --- Readily -----------------------------------------------------------------

def op_readily_save(docs, ctx, p):
    if not docs.config["readily"]["enabled"]:
        raise SyllabusError("Readily integration is off", READILY)
    owner = _owner(docs, ctx, p, allow_stage=False)
    links = owner.setdefault("links", [])
    link = links[_find(links, _str(p, "linkId", True), "link")]
    ref = p["owner"]
    if not owner.get("readilyTag"):
        # Saved on first use, so renaming the course later keeps finding its items.
        owner["readilyTag"] = owner_tag(ctx.view, ref)
    readily.save(docs.config["readily"]["section"], link.get("title") or "", owner["readilyTag"],
                 link.get("url") or link.get("text") or "")
    link["readilySavedAt"] = store.now_iso()


def op_readily_copy(docs, ctx, p):
    index = p.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        raise SyllabusError("index must be a number", USAGE)
    readily.copy(_str(p, "section", True), index, _str(p, "hash", True))


# --- panel -------------------------------------------------------------------

def op_window_set(docs, ctx, p):
    window = docs.state.setdefault("window", {})
    changed = False
    for key, low in (("width", 600), ("height", 400)):
        if key in p:
            window[key] = round(_number(p, key, low, 10000))
            changed = True
    if "pinned" in p:
        window["pinned"] = _bool(p, "pinned")
        changed = True
    if not changed:
        raise SyllabusError("Nothing to change", USAGE)


# --- config ------------------------------------------------------------------

CONFIG_KEYS = {
    "seenThreshold": ("number", 0.5, 1.0),
    "resumeRewind": ("number", 0, 120),
    "reportSeconds": ("number", 5, 300),
    "streakMinutes": ("number", 1, 600),
    "player.command": ("text",),
    "player.args": ("list",),
    "readily.enabled": ("bool",),
    "readily.section": ("section",),
    "web.quality": ("choice", store.QUALITIES),
    "web.downloadFolder": ("folder",),
    "web.refreshHours": ("number", 1, 168),
    "web.subtitleLanguages": ("langs",),
    "web.autoSubtitles": ("bool",),
    "web.audioLanguage": ("lang",),
}


def op_config_set(docs, ctx, p):
    key = _str(p, "key", True)
    spec = CONFIG_KEYS.get(key)
    if spec is None:
        raise SyllabusError(f"{key} cannot be changed here", USAGE)
    kind = spec[0]
    if kind == "number":
        value = _number(p, "value", spec[1], spec[2])
    elif kind == "text":
        value = _str(p, "value", True)
    elif kind == "list":
        value = p.get("value")
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SyllabusError(f"{key} must be a list of words", USAGE)
    elif kind == "bool":
        value = _bool(p, "value")
    elif kind == "choice":
        value = _str(p, "value", True)
        if value not in spec[1]:
            raise SyllabusError(f"{key} must be one of: " + ", ".join(spec[1]), USAGE)
    elif kind == "folder":
        value = os.path.expanduser(_str(p, "value", True)).rstrip("/")
        if not os.path.isabs(value):
            raise SyllabusError("The download folder must be an absolute path", USAGE)
    elif kind == "langs":
        raw = p.get("value")
        if not isinstance(raw, list):
            raise SyllabusError("Subtitle languages are codes like es or en", USAGE)
        # One typo does not throw away the rest of the list: what reads as a code is
        # kept, and the field shows what was saved. Only a list where nothing at all
        # was a code is refused, because dropping every entry would silently turn the
        # subtitles off.
        value = [v for v in raw if isinstance(v, str) and store.LANG_RE.match(v)]
        if raw and not value:
            raise SyllabusError("Subtitle languages are codes like es or en", USAGE)
    elif kind == "lang":
        value = _str(p, "value") or ""
        if value and not store.LANG_RE.match(value):
            raise SyllabusError("An audio language is a code like es or en", USAGE)
    else:
        value = _str(p, "value", True)
        if not SECTION_RE.match(value):
            raise SyllabusError("A Readily section starts with a letter or digit and has up to 64 letters, "
                                "digits, spaces or dashes", USAGE)
    target = docs.config
    parts = key.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


OPS = {
    "course.set": op_course_set,
    "cover.set": op_cover_set,
    "folder.layout": op_folder_layout,
    "web.remove": op_web_remove,
    "web.removeVideo": op_web_remove_video,
    "lesson.set": op_lesson_set,
    "lesson.move": op_lesson_move,
    "seen.set": op_seen_set,
    "bookmark.add": op_bookmark_add,
    "bookmark.set": op_bookmark_set,
    "bookmark.remove": op_bookmark_remove,
    "note.set": op_note_set,
    "roadmap.add": op_roadmap_add,
    "roadmap.set": op_roadmap_set,
    "roadmap.remove": op_roadmap_remove,
    "roadmap.move": op_roadmap_move,
    "stage.add": op_stage_add,
    "stage.set": op_stage_set,
    "stage.remove": op_stage_remove,
    "stage.move": op_stage_move,
    "stage.addCourse": op_stage_add_course,
    "stage.removeCourse": op_stage_remove_course,
    "stage.moveCourse": op_stage_move_course,
    "task.add": op_task_add,
    "task.set": op_task_set,
    "task.remove": op_task_remove,
    "task.move": op_task_move,
    "link.add": op_link_add,
    "link.set": op_link_set,
    "link.remove": op_link_remove,
    "link.move": op_link_move,
    "readily.save": op_readily_save,
    "readily.copy": op_readily_copy,
    "config.set": op_config_set,
    "window.set": op_window_set,
}


def apply(docs, payload, cache):
    """Run one op on the documents (the caller holds the transaction). Returns its result."""
    name = payload.get("op") if isinstance(payload, dict) else None
    fn = OPS.get(name)
    if fn is None:
        raise SyllabusError(f"Unknown operation: {name}", USAGE)
    return fn(docs, Context(docs, cache), payload) or {}
