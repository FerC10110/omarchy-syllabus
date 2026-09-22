"""syllabus: study roadmaps for the video courses on the disk. Every command
prints one JSON object; errors print {"error", "code"} and exit with the code."""
import argparse
import json
import os
import subprocess
import sys

from . import covers, downloads, ops, paths, player, probe, progress, readily, scan, store, view, web
from .errors import GENERAL, OFFLINE, UNKNOWN, USAGE, SyllabusError


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SyllabusError(message, USAGE)


def current_view():
    return view.build_view(store.load_config(), store.load_library(), store.load_state(), store.load_scan())


def lesson_for_path(config, path, cache=None, state=None):
    """The lesson a report is about: a file under a root, a link, or a downloaded file."""
    text = str(path or "")
    if text.startswith(("http://", "https://")):
        cache = store.load_scan() if cache is None else cache
        for lesson_id, (root_id, _course, lesson) in scan.lesson_index(cache).items():
            if root_id == "web" and lesson.get("url") == text:
                return lesson_id
        return None
    normalized = os.path.normpath(text)
    # A downloaded file can sit under a scanned root (the scan skips web.downloadFolder on
    # purpose): checking the registry first keeps it resolving to its web lesson instead of
    # a phantom entry under that root.
    state = store.load_state() if state is None else state
    for lesson_id, record in (state.get("downloads") or {}).items():
        if os.path.normpath(str(record.get("path") or "")) == normalized:
            return lesson_id
    for root in config["roots"]:
        base = root["path"].rstrip("/")
        if normalized.startswith(base + "/"):
            return f"{root['id']}:{normalized[len(base) + 1:]}"
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


def do_scan(force=False, probe_fn=None, web_ids=None, prefetch=None):
    """Walk the mounted roots and read the web courses (outside the lock: both can take
    a minute), then fold the result in under the lock: moved videos keep their progress."""
    config = store.load_config()
    library = store.load_library()
    layouts = {k: v.get("layout") for k, v in library["folders"].items()}
    web_defs = {k: v for k, v in library["web"].items() if isinstance(v, dict)}
    old = store.load_scan()
    new = scan.scan_all(config, layouts, old, probe_fn or probe.probe_duration, force,
                        web_defs=web_defs, web_ids=web_ids, prefetch=prefetch)
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
        "webErrors": [{"id": cid, "error": info["error"]}
                      for cid, info in ((new["roots"].get("web") or {}).get("sources") or {}).items()
                      if info.get("error")],
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
        result["scan"] = do_scan(web_ids=result.pop("webIds", None))
    emit({"view": current_view(), "result": result})


# --- web courses -------------------------------------------------------------

def cmd_web_add(args):
    """Read the link first, with no lock held, and only write once it answered."""
    url = args.url.strip()
    if not url.startswith(("http://", "https://")):
        raise SyllabusError("Paste a link that starts with http", USAGE)
    password = (args.password or "").strip()
    answer = web.fetch_playlist(url, password)
    if answer["error"]:
        raise SyllabusError(answer["error"], OFFLINE)
    if not answer["entries"]:
        raise SyllabusError("That link has no video", USAGE)
    source = {"kind": answer["kind"], "url": url if answer["kind"] == "playlist" else answer["entries"][0]["url"]}
    if password:
        source["password"] = password
    course_id = (args.course or "").strip()
    with store.transaction() as docs:
        defs = docs.library["web"]
        if course_id:
            if course_id not in defs:
                raise SyllabusError("Unknown web course", UNKNOWN)
            if answer["kind"] != "video":
                raise SyllabusError("A playlist makes a course of its own", USAGE)
            if any(s.get("url") == source["url"] for s in defs[course_id].get("sources", [])):
                raise SyllabusError("That video is already in the course", USAGE)
            defs[course_id].setdefault("sources", []).append(source)
        else:
            course_id = web.new_course_id(set(defs))
            defs[course_id] = {"sources": [source], "addedAt": store.now_iso()}
        over = docs.library["courses"].setdefault(course_id, {})
        if args.title:
            over["title"] = args.title.strip()
        if args.topic:
            over["topic"] = args.topic.strip()
    result = do_scan(web_ids={course_id}, prefetch={source["url"]: answer})
    emit({"courseId": course_id, "title": answer["title"], "videos": len(answer["entries"]), "scan": result})


def cmd_web_refresh(args):
    """Read one web course again, or every one of them, right now."""
    defs = store.load_library()["web"]
    if args.course_id:
        if args.course_id not in defs:
            raise SyllabusError("Unknown web course", UNKNOWN)
        ids = {args.course_id}
    else:
        ids = set(defs)
    emit(do_scan(web_ids=ids))


# --- playing -----------------------------------------------------------------

def media_path(config, cache, state, lesson_id):
    """Where the video is: a file under a root, a file that was downloaded, or a link.
    Returns (target, course, kind) with kind "file" or "link"."""
    entry = scan.lesson_index(cache).get(lesson_id)
    if entry is None:
        raise SyllabusError("Unknown video", UNKNOWN)
    root_id, course, lesson = entry
    if root_id == "web":
        # Downloading a course is precisely what should survive the uploader taking a video
        # down: a registered file that still exists plays, whatever "available" says.
        saved = (state.get("downloads") or {}).get(lesson_id) or {}
        if saved.get("path") and os.path.isfile(saved["path"]):
            return saved["path"], course, "file"
        if not lesson.get("available", True):
            raise SyllabusError("That video is not available any more", OFFLINE)
        if not lesson.get("url"):
            raise SyllabusError("That video has no link any more", UNKNOWN)
        return lesson["url"], course, "link"
    base = root_path(config, root_id)
    if not base or not os.path.isdir(base):
        raise SyllabusError("The course disk is not mounted", OFFLINE)
    path = os.path.join(base, lesson["relpath"])
    if not os.path.isfile(path):
        raise SyllabusError("That video is no longer on the disk; rescan the library", OFFLINE)
    return path, course, "file"


def start_playing(lesson_id, at=None):
    config, cache, state = store.load_config(), store.load_scan(), store.load_state()
    target, course, kind = media_path(config, cache, state, lesson_id)
    options = []
    if kind == "link":
        lesson = scan.lesson_index(cache)[lesson_id][2]
        options = player.web_options(config, web.password_for(store.load_library()["web"], course["id"], lesson))
    if at is None:
        at = progress.start_position(state["lessons"].get(lesson_id), config["resumeRewind"])
    at = max(0.0, float(at))
    mode = player.play(config, target, at, options=options)
    stale = kind == "link" and lesson_id in (state.get("downloads") or {})
    with store.transaction() as docs:
        docs.state["last"] = {"lessonId": lesson_id, "at": store.now_iso()}
        if stale:
            # The file was deleted behind our back: the registry would keep pointing at it.
            docs.state["downloads"].pop(lesson_id, None)
    return {"lessonId": lesson_id, "courseId": course["id"], "start": round(at, 3), "mode": mode, "kind": kind}


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


def cmd_download(args):
    """--run is the worker; without it the panel gets a detached one and returns at once."""
    if args.stop:
        emit({"courseId": args.course_id, "stopped": downloads.stop(args.course_id)})
        return
    if args.run:
        summary = downloads.run(args.course_id)
        if summary["failed"]:
            notify(f"{summary['done']} of {summary['total']} downloaded, {len(summary['failed'])} failed: "
                   + ", ".join(summary["failed"][:3]))
        elif summary["total"]:
            notify(f"{summary['done']} video{'' if summary['done'] == 1 else 's'} downloaded")
        emit(summary)
        return
    config, cache = store.load_config(), store.load_scan()
    library, state = store.load_library(), store.load_state()
    if downloads.progress(args.course_id):
        raise SyllabusError("That course is already downloading", USAGE)
    _folder, items = downloads.plan(config, cache, library, state, args.course_id)
    subprocess.Popen([paths.BIN_PATH, "download", args.course_id, "--run"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     close_fds=True)
    emit({"courseId": args.course_id, "started": True, "pending": len(items)})


def cmd_downloads_delete(args):
    config = store.load_config()
    cache = store.load_scan()
    course = known_course(cache, args.course_id)
    ids = [l["id"] for l in course["lessons"]]
    # Stop a running worker before anything is deleted: left running, it would keep
    # writing into the folder this command is about to empty.
    downloads.stop(args.course_id)
    with store.transaction() as docs:
        result = downloads.delete_files(config, docs.state, ids)
    emit({"courseId": args.course_id, **result})


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
    down = sub.add_parser("download", help="download a web course to watch it offline")
    down.add_argument("course_id")
    down.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    down.add_argument("--stop", action="store_true")
    down.set_defaults(func=cmd_download)

    wipe = sub.add_parser("downloads-delete", help="delete the files a web course downloaded")
    wipe.add_argument("course_id")
    wipe.set_defaults(func=cmd_downloads_delete)

    add = sub.add_parser("web-add", help="add a playlist or a video from the web")
    add.add_argument("url")
    add.add_argument("--course", help="add a loose video to this web course")
    add.add_argument("--title")
    add.add_argument("--topic")
    add.add_argument("--password", help="the video's password, if the site asks for one")
    add.set_defaults(func=cmd_web_add)

    refresh = sub.add_parser("web-refresh", help="read the web courses again now")
    refresh.add_argument("course_id", nargs="?")
    refresh.set_defaults(func=cmd_web_refresh)

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
