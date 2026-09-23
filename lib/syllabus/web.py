"""Courses that live on the web: what yt-dlp says about a playlist or a video, and
the tree that `scan` puts under the `web` root. Nothing here raises on a network
failure: the error comes back as text, to be shown and tried again later."""
import concurrent.futures
import json
import os
import secrets
import selectors
import shlex
import shutil
import subprocess
import time

from . import covers, store

# yt-dlp titles a video it cannot read like this; the entry stays, marked gone.
GONE_TITLES = ("[private video]", "[deleted video]", "[unavailable video]")

# Nothing on the other side of a link is trusted to be small. A course endpoint is
# chosen by whoever wrote the link, and these ceilings are all that stands between it
# and this machine's memory: a playlist of ten million entries, a title a megabyte
# long, or a yt-dlp that is made to print forever, all stop here.
MAX_STDOUT = 8 * 1024 * 1024
MAX_STDERR = 64 * 1024
MAX_ENTRIES = 1000
MAX_TEXT = 300
MAX_URL = 2048
MAX_DURATION_LOOKUPS = 300


def ytdlp_bin():
    return os.environ.get("SYLLABUS_YTDLP") or shutil.which("yt-dlp") or "yt-dlp"


def new_course_id(taken):
    """web:<6 hex>, never one already in use."""
    while True:
        candidate = "web:" + secrets.token_hex(3)
        if candidate not in taken:
            return candidate


def lesson_id(course_id, site, video_id):
    return f"{course_id}/{site}:{video_id}"


def normalize_url(site, video_id, url=""):
    """The canonical link: what mpv gets, and what its reports are matched against."""
    if site == "youtube" and video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    if site == "vimeo" and str(video_id).isdigit():
        return f"https://vimeo.com/{video_id}"
    return url


def _last_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1].replace("ERROR: ", "") if lines else ""


def _close(proc):
    """Every pipe this process opened for the child. A scan reads many links, and a
    descriptor left behind on each one adds up to a process that cannot open files."""
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass


def _kill(proc):
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def _collect(proc, timeout):
    """Both of yt-dlp's streams, each under its own ceiling, within one deadline.

    Returns (stdout, stderr, why) where `why` is "", "timeout" or "flood". Reading as
    it comes is the point: `capture_output` would happily buffer whatever the other
    side decides to send."""
    caps = {proc.stdout: MAX_STDOUT, proc.stderr: MAX_STDERR}
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    deadline = None if timeout is None else time.monotonic() + timeout
    why = ""
    with selectors.DefaultSelector() as sel:
        for stream in caps:
            sel.register(stream, selectors.EVENT_READ)
        while sel.get_map() and not why:
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                why = "timeout"
                break
            for key, _ in sel.select(timeout=0.5 if left is None else min(left, 0.5)):
                chunk = key.fileobj.read1(65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                buffers[key.fileobj] += chunk
                if len(buffers[key.fileobj]) > caps[key.fileobj]:
                    why = "flood"
                    break
    return bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr]), why


class Finished:
    """What `run_capped` gives back: the same three fields a caller reads off
    subprocess.run, so it can stand in for it."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run_capped(args, capture_output=True, text=True, input="", timeout=None):
    """subprocess.run with a ceiling on each stream. A download is a long-lived child
    talking to a site nobody here chose, and it does not get to decide how much of this
    machine's memory its output takes."""
    proc = subprocess.Popen(list(args), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        try:
            proc.stdin.write((input or "").encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        out, err, why = _collect(proc, timeout)
        if why:
            _kill(proc)
            return Finished(1, "", f"yt-dlp {'took too long' if why == 'timeout' else 'sent back far too much'}")
        return Finished(proc.wait(), out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
    finally:
        _close(proc)


def password_config(password):
    """The one line of yt-dlp configuration that carries a password, for its stdin."""
    return "--video-password " + shlex.quote(password) + "\n" if password else ""


def _run(args, timeout, password=""):
    """yt-dlp's JSON, or (None, "why it failed")."""
    argv = [ytdlp_bin()]
    config = ""
    if password:
        # The password goes in on stdin, never on the command line: /proc/<pid>/cmdline
        # is readable by every process on the machine, and process accounting logs it.
        argv += ["--config-locations", "-"]
        config = password_config(password)
    try:
        proc = subprocess.Popen(argv + list(args), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None, "yt-dlp is not installed"
    except OSError as e:
        return None, f"yt-dlp could not run: {e}"
    try:
        try:
            proc.stdin.write(config.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        out, err, why = _collect(proc, timeout)
        if why:
            _kill(proc)
            return None, "yt-dlp took too long" if why == "timeout" else "That link sent back far too much"
        if proc.wait() != 0:
            return None, _last_line(err.decode("utf-8", "replace")) or "yt-dlp could not read that link"
        try:
            data = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            return None, "yt-dlp gave no answer"
        return (data, "") if isinstance(data, dict) else (None, "yt-dlp gave no answer")
    finally:
        _close(proc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return round(max(0.0, float(value)), 3)


def _clip(value, limit=MAX_TEXT):
    """A field as it is allowed to be: text, trimmed, and never longer than `limit`.

    Every one of these comes from the other side of a link, so none of them decides
    how much memory a course takes."""
    return str(value or "").strip()[:limit]


def _entry(raw):
    """One video, or None when there is no id to build an id from."""
    if not isinstance(raw, dict):
        return None
    video_id = _clip(raw.get("id"))
    if not video_id:
        return None
    site = _clip(raw.get("ie_key") or raw.get("extractor_key") or raw.get("extractor") or "web", 40).lower()
    title = _clip(raw.get("title"))
    url = _clip(normalize_url(site, video_id, _clip(raw.get("webpage_url") or raw.get("url"), MAX_URL)), MAX_URL)
    return {"site": site or "web", "videoId": video_id, "url": url, "title": title or video_id,
            "duration": _number(raw.get("duration")), "available": title.lower() not in GONE_TITLES}


def _usable_thumbnail(url):
    """A thumbnail link this code is willing to follow: https, and no longer than a url
    has any business being. Plain http is refused — the address is chosen by the site,
    and there is no reason to fetch a cover in the clear."""
    return isinstance(url, str) and url.startswith("https://") and len(url) <= MAX_URL


def _thumbnail(raw):
    """The biggest thumbnail yt-dlp offers: the list comes smallest first."""
    if _usable_thumbnail(raw.get("thumbnail")):
        return raw.get("thumbnail")
    for item in reversed((raw.get("thumbnails") or [])[-20:]):
        if isinstance(item, dict) and _usable_thumbnail(item.get("url")):
            return item["url"]
    return ""


def _answer(kind="", title="", thumbnail="", entries=None, error="", dropped=0):
    return {"kind": kind, "title": title, "thumbnail": thumbnail, "entries": entries or [],
            "error": error, "dropped": dropped}


def _entries_of(data):
    """The videos of a playlist, up to the ceiling, and how many were left out."""
    raw = data.get("entries")
    raw = raw if isinstance(raw, list) else []
    entries = [e for e in (_entry(item) for item in raw[:MAX_ENTRIES]) if e]
    return entries, max(0, len(raw) - MAX_ENTRIES)


def fetch_playlist(url, password="", timeout=120):
    """What is behind a link: a playlist with its entries, or a single video."""
    data, error = _run(["--flat-playlist", "-J", "--no-warnings", url], timeout, password)
    if error:
        return _answer(error=error)
    if data.get("_type") == "playlist":
        entries, dropped = _entries_of(data)
        return _answer("playlist", _clip(data.get("title")), _thumbnail(data), entries, dropped=dropped)
    entry = _entry(data)
    if entry is None:
        return _answer(error="That link has no video")
    return _answer("video", entry["title"], _thumbnail(data), [entry])


def fetch_video(url, password="", timeout=60):
    data, error = _run(["-J", "--no-playlist", "--no-warnings", url], timeout, password)
    if error:
        return _answer(error=error)
    entry = _entry(data)
    if entry is None:
        return _answer(error="That link has no video")
    return _answer("video", entry["title"], _thumbnail(data), [entry])


def fetch_durations(entries, password="", workers=4, fetch=fetch_video):
    """A flat playlist has no durations: ask for the missing ones, a few at a time.

    One scan is worth a bounded amount of work: past `MAX_DURATION_LOOKUPS` the rest
    keep the duration they have, which the next scan fills in."""
    todo = [e for e in entries if e["available"] and not e["duration"] and e["url"]][:MAX_DURATION_LOOKUPS]
    if not todo:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        answers = list(pool.map(lambda entry: fetch(entry["url"], password), todo))
    for entry, answer in zip(todo, answers):
        if answer["entries"]:
            entry["duration"] = answer["entries"][0]["duration"]


def password_for(defs, course_id, lesson):
    """The password of the source a lesson came from, if the site asked for one."""
    sources = (defs.get(course_id) or {}).get("sources") or []
    url = str(lesson.get("url") or "")
    for source in sources:
        if source.get("kind") == "video" and source.get("url") == url:
            return str(source.get("password") or "")
    playlist = next((s for s in sources if s.get("kind") == "playlist"), None)
    return str((playlist or {}).get("password") or "")


def _lessons_from(course_id, kind, entries, old_by_id):
    """One block of lessons: what came back, and then what used to be here and did not."""
    out, seen = [], set()
    for entry in entries:
        new_id = lesson_id(course_id, entry["site"], entry["videoId"])
        seen.add(new_id)
        out.append({"id": new_id, "title": entry["title"], "name": entry["title"], "number": None,
                    "group": "", "relpath": "", "url": entry["url"], "site": entry["site"],
                    "videoId": entry["videoId"], "available": entry["available"], "source": kind,
                    "duration": entry["duration"]})
    for lesson in old_by_id.values():
        if lesson["id"] not in seen and lesson.get("source") == kind:
            out.append(dict(lesson, available=False))
    return out


def _entry_of(lesson):
    """The entry a lesson came from, to carry it over when its source cannot be read."""
    return {"site": lesson["site"], "videoId": lesson["videoId"], "url": lesson["url"],
            "title": lesson["title"], "duration": lesson["duration"], "available": lesson["available"]}


def _read_course(course_id, definition, old, info, fetch_list, fetch_one, cover, prefetch):
    """One web course read again. Returns (course, source info)."""
    sources = definition.get("sources") or []
    playlist = next((s for s in sources if s.get("kind") == "playlist"), None)
    loose = [s for s in sources if s.get("kind") == "video"]
    title, thumbnail, error = info.get("title", ""), info.get("thumbnail", ""), ""
    blocks, found = [], []
    if playlist:
        answer = prefetch.get(playlist["url"]) or fetch_list(playlist["url"], str(playlist.get("password") or ""))
        if answer["error"]:
            # The playlist is the course: without it there is nothing to merge into.
            return (old, dict(info, error=answer["error"])) if old else (None, dict(info, error=answer["error"]))
        title = answer["title"] or title
        thumbnail = answer["thumbnail"] or thumbnail
        if answer.get("dropped"):
            error = f"This playlist has more than {MAX_ENTRIES} videos; the rest are not shown"
        fetch_durations(answer["entries"], str(playlist.get("password") or ""), fetch=fetch_one)
        blocks.append(("playlist", answer["entries"]))
    old_by_id = {l["id"]: l for l in (old or {}).get("lessons", [])}
    old_by_url = {l["url"]: l for l in old_by_id.values() if l.get("source") == "video"}
    for source in loose:
        answer = prefetch.get(source["url"]) or fetch_one(source["url"], str(source.get("password") or ""))
        if answer["error"]:
            error = error or answer["error"]
            # A blip is not a video that went away: keep what the last good read knew.
            known = old_by_url.get(source["url"])
            if known is not None:
                found.append(_entry_of(known))
            continue
        found += answer["entries"]
        thumbnail = thumbnail or answer["thumbnail"]
        title = title or answer["title"]
    blocks.append(("video", found))
    loose_urls = {str(s.get("url") or "") for s in loose}
    lessons = []
    for kind, entries in blocks:
        # A loose video whose source was removed is gone for good; only one whose source
        # is still here may stay as a lesson marked "not available".
        known = old_by_id if kind == "playlist" else {
            lid: l for lid, l in old_by_id.items() if l.get("url") in loose_urls}
        lessons += _lessons_from(course_id, kind, entries, known)
    cover_path = (cover(thumbnail) if thumbnail else "") or (old or {}).get("coverPath", "")
    first = playlist or (loose[0] if loose else {})
    course = {"id": course_id, "rootId": "web", "relpath": "", "folderId": "",
              "title": title or "Web course", "topic": "", "lessons": lessons, "docs": [], "images": [],
              "autoCover": "", "coverPath": cover_path, "sourceUrl": str(first.get("url") or ""),
              "sourceKind": "playlist" if playlist else "video"}
    return course, {"fetchedAt": store.now_iso(), "error": error, "title": title, "thumbnail": thumbnail}


def build_tree(defs, old_tree, due, fetch_list=fetch_playlist, fetch_one=fetch_video, cover=None, prefetch=None):
    """The `web` root: every course, read again when it is due and copied over when it is not.

    `prefetch` lets `web-add` reuse the answer it already paid for, so adding a
    course does not read the same playlist twice."""
    cover = covers.cache_remote if cover is None else cover
    prefetch = prefetch or {}
    old_courses = {c["id"]: c for c in (old_tree.get("courses") or [])}
    old_sources = old_tree.get("sources") or {}
    tree = {"courses": [], "images": [], "folders": {}, "sources": {}, "fetchedAt": store.now_iso(), "error": ""}
    for course_id, definition in defs.items():
        old = old_courses.get(course_id)
        info = dict(old_sources.get(course_id) or {})
        if course_id not in due and old is not None:
            tree["courses"].append(old)
            tree["sources"][course_id] = info
            continue
        course, info = _read_course(course_id, definition, old, info, fetch_list, fetch_one, cover, prefetch)
        if course is not None:
            tree["courses"].append(course)
        tree["sources"][course_id] = info
    return tree
