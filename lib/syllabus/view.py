"""Everything the window shows, built from the user's documents and the scan cache.
Reading only: building a view never touches the disk beyond a few stat calls."""
import os

from . import covers, paths, progress, scan, store

SUSPECT_SECONDS = 60


def fmt_clock(seconds):
    total = max(0, int(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_study(seconds):
    minutes = int(round((seconds or 0) / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}" if hours else f"{minutes} min"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_tasks(items):
    if not isinstance(items, list):
        return []
    return [{"id": t["id"], "text": t["text"], "done": bool(t.get("done")), "doneAt": t.get("doneAt")}
            for t in items if isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("text"), str)]


def _valid_links(items):
    if not isinstance(items, list):
        return []
    out = []
    for link in items:
        if not isinstance(link, dict) or not isinstance(link.get("id"), str):
            continue
        if (link.get("kind") == "link" and isinstance(link.get("url"), str)) or \
           (link.get("kind") == "snippet" and isinstance(link.get("text"), str)):
            out.append(dict(link))
    return out


def valid_marks(items):
    if not isinstance(items, list):
        return []
    marks = [{"id": b["id"], "at": float(b["at"]), "text": b.get("text") if isinstance(b.get("text"), str) else ""}
             for b in items if isinstance(b, dict) and isinstance(b.get("id"), str) and _number(b.get("at"))]
    return sorted(marks, key=lambda b: b["at"])


def _ordered(lessons, order):
    """The saved order first (ids that still exist), then new lessons in scan order."""
    if not isinstance(order, list):
        return lessons
    position = {lesson_id: i for i, lesson_id in enumerate(order) if isinstance(lesson_id, str)}
    known = sorted((l for l in lessons if l["id"] in position), key=lambda l: position[l["id"]])
    return known + [l for l in lessons if l["id"] not in position]


def _lesson(rec, over, entry, files):
    record = files.get(rec["id"]) or {}
    duration = float(record.get("duration") or entry.get("duration") or 0)
    error = record.get("error") or ""
    suspect = bool(error) or 0 < duration < SUSPECT_SECONDS
    hidden = over["hidden"] if isinstance(over.get("hidden"), bool) else suspect
    pos = max(0.0, float(entry.get("pos") or 0))
    if duration > 0:
        pos = min(pos, duration)
    title = over.get("title") if isinstance(over.get("title"), str) and over.get("title") else rec["title"]
    return {"id": rec["id"], "title": title, "defaultTitle": rec["title"], "name": rec["name"],
            "group": rec.get("group", ""), "number": rec.get("number"), "duration": duration, "pos": pos,
            "seen": bool(entry.get("seen")), "hidden": hidden, "suspect": suspect, "error": error,
            "updatedAt": entry.get("updatedAt") or "", "bookmarks": valid_marks(over.get("bookmarks"))}


def _duration_stats(total, watched):
    """The duration/watched/remaining/percent quartet shared by course and roadmap totals."""
    return {"duration": round(total, 1), "watched": round(watched, 1),
            "remaining": round(max(0.0, total - watched), 1),
            "percent": round(100.0 * watched / total, 1) if total > 0 else 0.0}


def _totals(lessons):
    visible = [l for l in lessons if not l["hidden"]]
    total = sum(l["duration"] for l in visible)
    watched = sum(l["duration"] if l["seen"] else min(l["pos"], l["duration"]) for l in visible)
    stats = {"lessonCount": len(visible), "seenCount": sum(1 for l in visible if l["seen"])}
    stats.update(_duration_stats(total, watched))
    return stats


def _cover(tree_course, over, root_path):
    chosen = over.get("cover")
    if isinstance(chosen, str) and chosen and os.path.isfile(chosen):
        return chosen
    auto = tree_course.get("autoCover")
    if auto and root_path:
        cached = covers.cached_path(os.path.join(root_path, auto))
        if os.path.isfile(cached):
            return cached
    return ""


def _course(tree_course, library, state, files, online, root_path):
    course_id = tree_course["id"]
    over = library["courses"].get(course_id) or {}
    lessons = [_lesson(rec, library["lessons"].get(rec["id"]) or {}, state["lessons"].get(rec["id"]) or {}, files)
               for rec in tree_course.get("lessons", [])]
    lessons = _ordered(lessons, over.get("order"))
    tasks = _valid_tasks(over.get("tasks"))
    title = over.get("title") if isinstance(over.get("title"), str) and over.get("title") else tree_course["title"]
    course = {
        "id": course_id, "rootId": tree_course["rootId"], "folderId": tree_course["folderId"],
        "relpath": tree_course["relpath"], "title": title, "defaultTitle": tree_course["title"],
        "topic": over["topic"] if isinstance(over.get("topic"), str) and over["topic"] else tree_course.get("topic", ""),
        "cover": _cover(tree_course, over, root_path), "online": online,
        "readilyTag": over.get("readilyTag") if isinstance(over.get("readilyTag"), str) else "",
        "lessons": lessons, "tasks": tasks, "taskCount": len(tasks),
        "taskDone": sum(1 for t in tasks if t["done"]), "links": _valid_links(over.get("links")),
        "docCount": len(tree_course.get("docs", [])),
        "lastPlayedAt": max((l["updatedAt"] for l in lessons), default=""),
        "hasNote": os.path.exists(paths.note_path(course_id)),
    }
    course.update(_totals(lessons))
    return course


def _stats(course_ids, by_id):
    total = sum(by_id[c]["duration"] for c in course_ids)
    watched = sum(by_id[c]["watched"] for c in course_ids)
    return _duration_stats(total, watched)


def _roadmap(roadmap, by_id):
    stages, everything = [], []
    for stage in roadmap.get("stages") if isinstance(roadmap.get("stages"), list) else []:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
            continue
        raw = [c for c in stage.get("courseIds", []) if isinstance(c, str)] if isinstance(stage.get("courseIds"), list) else []
        ids = [c for c in raw if c in by_id]
        tasks = _valid_tasks(stage.get("tasks"))
        entry = {"id": stage["id"], "title": stage.get("title") or "", "courseIds": ids, "missing": len(raw) - len(ids),
                 "tasks": tasks, "taskCount": len(tasks), "taskDone": sum(1 for t in tasks if t["done"])}
        entry.update(_stats(ids, by_id))
        stages.append(entry)
        everything += [c for c in ids if c not in everything]
    tasks = _valid_tasks(roadmap.get("tasks"))
    out = {"id": roadmap["id"], "title": roadmap.get("title") or "",
           "readilyTag": roadmap.get("readilyTag") if isinstance(roadmap.get("readilyTag"), str) else "",
           "stages": stages, "tasks": tasks, "taskCount": len(tasks), "taskDone": sum(1 for t in tasks if t["done"]),
           "links": _valid_links(roadmap.get("links")), "courseCount": len(everything)}
    out.update(_stats(everything, by_id))
    return out


def resume_target(courses, roadmaps, state):
    """What "Continue" plays: the last video, or the next unseen one of its course; when
    that course is done, the next unfinished course of the roadmaps (the roadmap
    holding the last course first)."""
    order = {c["id"]: [l["id"] for l in c["lessons"] if not l["hidden"]] for c in courses}
    target = progress.resume_lesson(order, state)
    if target in order.get(_owner_of(order, target), []):
        return target
    last = (state.get("last") or {}).get("lessonId")
    last_course = _owner_of(order, last)
    ranked = sorted(roadmaps, key=lambda r: not any(last_course in s["courseIds"] for s in r["stages"]))
    for roadmap in ranked:
        for stage in roadmap["stages"]:
            for course_id in stage["courseIds"]:
                target = progress.resume_lesson(order, state, course_id)
                if target:
                    return target
    return None


def _owner_of(order, lesson_id):
    return next((cid for cid, ids in order.items() if lesson_id in ids), None)


def _continue(target, courses):
    for course in courses:
        lesson = next((l for l in course["lessons"] if l["id"] == target), None)
        if lesson:
            return {"lessonId": target, "courseId": course["id"], "title": lesson["title"],
                    "courseTitle": course["title"], "pos": lesson["pos"], "duration": lesson["duration"],
                    "seen": lesson["seen"], "online": course["online"]}
    return None


def build_view(config, library, state, cache, moment=None):
    files = cache.get("files") or {}
    roots, courses, folders = [], [], {}
    for root in config["roots"]:
        tree = (cache.get("roots") or {}).get(root["id"]) or {}
        online = os.path.isdir(root["path"])
        roots.append({"id": root["id"], "path": root["path"], "online": online,
                      "scannedAt": tree.get("scannedAt", ""), "courseCount": len(tree.get("courses", []))})
        for folder_id, detected in (tree.get("folders") or {}).items():
            override = (library["folders"].get(folder_id) or {}).get("layout")
            folders[folder_id] = {"layout": override if override in ("course", "collection") else "auto",
                                  "detected": detected}
        for tree_course in tree.get("courses", []):
            courses.append(_course(tree_course, library, state, files, online, root["path"]))
    courses.sort(key=lambda c: (c["topic"] == "", scan.natural_key(c["topic"]), scan.natural_key(c["title"])))
    by_id = {c["id"]: c for c in courses}
    roadmaps = [_roadmap(r, by_id) for r in library["roadmaps"]]
    today = store.local_day(moment)
    window = state.get("window") or {}
    return {
        "version": 1,
        "roots": roots,
        "folders": folders,
        "courses": courses,
        "topics": sorted({c["topic"] for c in courses if c["topic"]}, key=scan.natural_key),
        "roadmaps": roadmaps,
        "continue": _continue(resume_target(courses, roadmaps, state), courses),
        "today": {"day": today, "seconds": progress.day_total(state["days"], today),
                  "streak": progress.streak(state["days"], today, int(config["streakMinutes"]) * 60)},
        "config": config,
        "window": {"width": window.get("width", 1100), "height": window.get("height", 720),
                   "pinned": window.get("pinned", False)},
        "paths": {"state": paths.state_path(), "library": paths.library_path(),
                  "config": paths.config_path(), "configDir": paths.config_dir()},
    }
