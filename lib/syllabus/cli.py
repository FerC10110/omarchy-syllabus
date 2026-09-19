"""syllabus: study roadmaps for the video courses on the disk. Every command
prints one JSON object; errors print {"error", "code"} and exit with the code."""
import argparse
import json
import os
import subprocess
import sys

from . import covers, ops, paths, player, probe, progress, readily, scan, store, view
from .errors import GENERAL, OFFLINE, UNKNOWN, USAGE, SyllabusError


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SyllabusError(message, USAGE)


def current_view():
    return view.build_view(store.load_config(), store.load_library(), store.load_state(), store.load_scan())


def lesson_for_path(config, path):
    """The lesson id of a file under one of the roots, or None."""
    path = os.path.normpath(path)
    for root in config["roots"]:
        base = root["path"].rstrip("/")
        if path.startswith(base + "/"):
            return f"{root['id']}:{path[len(base) + 1:]}"
    return None


def root_path(config, root_id):
    root = next((r for r in config["roots"] if r["id"] == root_id), None)
    return root["path"] if root else ""


def known_course(cache, course_id):
    course = scan.course_index(cache).get(course_id)
    if course is None:
        raise SyllabusError("Unknown course", UNKNOWN)
    return course


# --- reading -----------------------------------------------------------------

def cmd_view(args):
    store.ensure_files()
    emit(current_view())


def do_scan(force=False, probe_fn=None):
    """Walk the mounted roots (outside the lock: it can take a minute), then fold the
    result in under the lock: moved videos keep their progress."""
    config = store.load_config()
    layouts = {k: v.get("layout") for k, v in store.load_library()["folders"].items()}
    old = store.load_scan()
    new = scan.scan_all(config, layouts, old, probe_fn or probe.probe_duration, force)
    probed = new.pop("probed")
    online = [r["id"] for r in config["roots"] if os.path.isdir(r["path"])]
    moves = scan.find_moves(old, new, online)
    for root in config["roots"]:
        if root["id"] not in online:
            continue
        for course in new["roots"][root["id"]]["courses"]:
            if course["autoCover"]:
                try:
                    covers.cache_cover(os.path.join(root["path"], course["autoCover"]))
                except OSError:
                    pass
    with store.transaction() as docs:
        scan.apply_moves(docs.library, docs.state, moves)
        store.save_scan(new)
    lessons = [l for tree in new["roots"].values() for c in tree["courses"] for l in c["lessons"]]
    files = new["files"]
    return {
        "courses": sum(len(tree["courses"]) for tree in new["roots"].values()),
        "lessons": len(lessons),
        "hours": round(sum(float((files.get(l["id"]) or {}).get("duration") or 0) for l in lessons) / 3600, 1),
        "probed": probed,
        "errors": [{"id": l["id"], "error": files[l["id"]]["error"]}
                   for l in lessons if (files.get(l["id"]) or {}).get("error")],
        "moved": len(moves),
    }


def cmd_scan(args):
    emit(do_scan(args.force))


def cmd_summary(args):
    built = current_view()
    cont, today = built["continue"], built["today"]
    if cont:
        first = (f"Continue: {cont['courseTitle']} · {cont['title']} · "
                 f"{view.fmt_clock(cont['pos'])} / {view.fmt_clock(cont['duration'])}")
    else:
        first = "Nothing in progress"
    days = today["streak"]
    second = f"Today {view.fmt_study(today['seconds'])} · Streak {days} day{'' if days == 1 else 's'}"
    emit({"text": f"{first}\n{second}", "continue": cont, "today": today})


def cmd_files(args):
    config, cache = store.load_config(), store.load_scan()
    course = known_course(cache, args.course_id)
    base = root_path(config, course["rootId"])
    emit({"courseId": course["id"], "root": base, "online": bool(base) and os.path.isdir(base),
          "files": [dict(doc, path=os.path.join(base, doc["relpath"])) for doc in course.get("docs", [])]})


def cmd_covers(args):
    config, cache = store.load_config(), store.load_scan()
    course = known_course(cache, args.course_id)
    base = root_path(config, course["rootId"])
    tree = (cache["roots"].get(course["rootId"]) or {})
    images = [{"path": os.path.join(base, rel), "name": os.path.basename(rel), "where": "course"}
              for rel in course.get("images", [])]
    images += [{"path": os.path.join(base, rel), "name": os.path.basename(rel), "where": "root"}
               for rel in tree.get("images", [])]
    emit({"courseId": course["id"], "online": bool(base) and os.path.isdir(base), "images": images})


def cmd_note_get(args):
    known_course(store.load_scan(), args.course_id)
    emit({"courseId": args.course_id, "text": ops.read_note(args.course_id), "path": paths.note_path(args.course_id)})


def cmd_readily_items(args):
    if not store.load_config()["readily"]["enabled"]:
        emit({"tag": "", "items": [], "warning": "Readily integration is off"})
        return
    tag = ops.owner_tag(current_view(), {"kind": args.kind, "id": args.owner_id})
    emit(dict(readily.list_items(tag), tag=tag))


def cmd_config(args):
    emit(store.load_config())


# --- writing -----------------------------------------------------------------

def cmd_apply(args):
    try:
        payload = json.loads(sys.stdin.readline())
    except ValueError:
        raise SyllabusError("apply expects one JSON object on stdin", USAGE)
    if not isinstance(payload, dict):
        raise SyllabusError("apply expects one JSON object on stdin", USAGE)
    cache = store.load_scan()
    with store.transaction() as docs:
        result = ops.apply(docs, payload, cache)
    if result.pop("rescan", False):
        result["scan"] = do_scan()
    emit({"view": current_view(), "result": result})


# --- playing -----------------------------------------------------------------

def media_path(config, cache, lesson_id):
    entry = scan.lesson_index(cache).get(lesson_id)
    if entry is None:
        raise SyllabusError("Unknown video", UNKNOWN)
    root_id, course, lesson = entry
    base = root_path(config, root_id)
    if not base or not os.path.isdir(base):
        raise SyllabusError("The course disk is not mounted", OFFLINE)
    path = os.path.join(base, lesson["relpath"])
    if not os.path.isfile(path):
        raise SyllabusError("That video is no longer on the disk; rescan the library", OFFLINE)
    return path, course


def start_playing(lesson_id, at=None):
    config, cache = store.load_config(), store.load_scan()
    path, course = media_path(config, cache, lesson_id)
    if at is None:
        at = progress.start_position(store.load_state()["lessons"].get(lesson_id), config["resumeRewind"])
    at = max(0.0, float(at))
    mode = player.play(config, path, at)
    with store.transaction() as docs:
        docs.state["last"] = {"lessonId": lesson_id, "at": store.now_iso()}
    return {"lessonId": lesson_id, "courseId": course["id"], "start": round(at, 3), "mode": mode}


def cmd_play(args):
    emit(start_playing(args.lesson_id, args.at))


def notify(message):
    """A desktop notification: `resume` runs from a key binding, with no window to show errors."""
    try:
        subprocess.run(["notify-send", "-a", "Syllabus", "Syllabus", message], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_resume(args):
    try:
        resume(args.course_id)
    except SyllabusError as e:
        if args.notify:
            notify(str(e))
        raise
    except Exception as e:
        if args.notify:
            notify(f"Syllabus: unexpected error: {type(e).__name__}: {e}")
        raise


def resume(course_id):
    built = current_view()
    state = store.load_state()
    if course_id is None:
        target = view.resume_target(built["courses"], built["roadmaps"], state)
    else:
        course = next((c for c in built["courses"] if c["id"] == course_id), None)
        if course is None:
            raise SyllabusError("Unknown course", UNKNOWN)
        order = {course["id"]: [l["id"] for l in course["lessons"] if not l["hidden"]]}
        target = progress.resume_lesson(order, state, course["id"])
    if not target:
        raise SyllabusError("Nothing left to watch", UNKNOWN)
    emit(start_playing(target))


def cmd_report(args):
    config, cache = store.load_config(), store.load_scan()
    lesson_id = lesson_for_path(config, args.path)
    if lesson_id is None:
        emit({"ignored": True})
        return
    entry = scan.lesson_index(cache).get(lesson_id)
    course_id = entry[1]["id"] if entry else ""
    with store.transaction() as docs:
        applied = progress.apply_report(docs.state, lesson_id, course_id, args.pos, args.duration, args.played,
                                        args.seq, args.eof, docs.config["seenThreshold"], keep_last=args.keep_last)
    emit({"lessonId": lesson_id, "applied": applied})


def cmd_bookmark_here(args):
    if args.path is None:
        path, at = player.current()
    elif args.at is None:
        raise SyllabusError("--path needs --at", USAGE)
    else:
        path, at = args.path, args.at
    lesson_id = lesson_for_path(store.load_config(), path)
    if lesson_id is None or lesson_id not in scan.lesson_index(store.load_scan()):
        raise SyllabusError("That video is not in the library", UNKNOWN)
    with store.transaction() as docs:
        mark = ops.add_bookmark(docs.library, lesson_id, at, args.text)
    emit({"lessonId": lesson_id, "bookmark": mark})


def cmd_bookmarks(args):
    lesson_id = lesson_for_path(store.load_config(), args.path)
    if lesson_id is None or lesson_id not in scan.lesson_index(store.load_scan()):
        emit({"lessonId": None, "bookmarks": []})
        return
    entry = store.load_library()["lessons"].get(lesson_id) or {}
    emit({"lessonId": lesson_id, "bookmarks": view.valid_marks(entry.get("bookmarks"))})


# --- wiring ------------------------------------------------------------------

def build_parser():
    parser = Parser(prog="syllabus", description="Study roadmaps for the video courses on the disk.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("view", help="everything the window shows").set_defaults(func=cmd_view)
    p = sub.add_parser("scan", help="read the course folders and video durations")
    p.add_argument("--force", action="store_true", help="probe every video again")
    p.set_defaults(func=cmd_scan)
    sub.add_parser("summary", help="the bar tooltip").set_defaults(func=cmd_summary)
    for name, func, text in (("files", cmd_files, "documents of a course"),
                             ("covers", cmd_covers, "images that can be a course's cover"),
                             ("note-get", cmd_note_get, "a course's note")):
        p = sub.add_parser(name, help=text)
        p.add_argument("course_id", metavar="COURSE_ID")
        p.set_defaults(func=func)
    p = sub.add_parser("readily-items", help="Readily items with a course's or roadmap's tag")
    p.add_argument("kind", choices=("course", "roadmap"))
    p.add_argument("owner_id", metavar="ID")
    p.set_defaults(func=cmd_readily_items)
    sub.add_parser("config", help="the effective configuration").set_defaults(func=cmd_config)
    sub.add_parser("apply", help="apply one operation read as JSON from stdin").set_defaults(func=cmd_apply)

    p = sub.add_parser("play", help="play a video where it was left")
    p.add_argument("lesson_id", metavar="LESSON_ID")
    p.add_argument("--at", type=float, help="start at this second instead")
    p.set_defaults(func=cmd_play)
    p = sub.add_parser("resume", help="play what comes next")
    p.add_argument("course_id", metavar="COURSE_ID", nargs="?")
    p.add_argument("--notify", action="store_true", help="also show errors as a desktop notification")
    p.set_defaults(func=cmd_resume)
    p = sub.add_parser("report", help="(mpv) where a video is and how long it was watched")
    p.add_argument("--path", required=True)
    p.add_argument("--pos", type=float, required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--played", type=float, default=0.0)
    p.add_argument("--seq", type=int, required=True)
    p.add_argument("--eof", action="store_true")
    p.add_argument("--keep-last", action="store_true",
                   help="mpv replaced this video with another: save it, but leave `last` alone")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("bookmark-here", help="bookmark a moment of a video (default: what mpv is playing)")
    p.add_argument("--text", default="")
    p.add_argument("--path")
    p.add_argument("--at", type=float)
    p.set_defaults(func=cmd_bookmark_here)
    p = sub.add_parser("bookmarks", help="(mpv) the bookmarks of a video")
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_bookmarks)
    return parser


def fail(message, code, reason=None):
    data = {"error": message, "code": code}
    if reason:
        data["reason"] = reason
    emit(data)
    print(f"syllabus: {message}", file=sys.stderr)
    return code


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        args.func(args)
        return 0
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0
    except SyllabusError as e:
        return fail(str(e), e.code, e.reason)
    except Exception as e:  # noqa: BLE001 - the panel needs JSON whatever happened
        return fail(f"{type(e).__name__}: {e}", GENERAL)
