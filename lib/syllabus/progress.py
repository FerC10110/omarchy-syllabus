"""Where each video was left, what counts as watched, what to play next, and
how much was studied each day."""
import datetime

from . import store

FINISH_MARGIN = 30.0
MAX_PLAYED_PER_REPORT = 6 * 3600


def _margin(duration):
    """How close to the end counts as the end: 30 s, or 5 % of a short video."""
    return min(FINISH_MARGIN, duration * 0.05)


def is_finished(entry):
    if not entry:
        return False
    if entry.get("seen"):
        return True
    duration = float(entry.get("duration") or 0)
    return duration > 0 and float(entry.get("pos") or 0) >= duration - _margin(duration)


def start_position(entry, rewind):
    """Where playback should start: a little before the saved position, or 0 when it had ended."""
    if not entry:
        return 0.0
    pos = max(0.0, float(entry.get("pos") or 0))
    duration = float(entry.get("duration") or 0)
    if duration > 0 and pos >= duration - _margin(duration):
        return 0.0
    return max(0.0, pos - float(rewind))


def apply_report(state, lesson_id, course_id, pos, duration, played, seq, eof, threshold, moment=None,
                 keep_last=False):
    """Record what mpv reported. Returns False when the report is older than what is stored.
    keep_last: the report of a video mpv just replaced with another, which `play` already
    made the last one; everything is saved but `last`."""
    moment = moment or datetime.datetime.now(datetime.timezone.utc)
    lessons = state.setdefault("lessons", {})
    entry = dict(lessons.get(lesson_id) or {})
    if int(seq) <= int(entry.get("seq") or 0):
        return False
    duration = max(0.0, float(duration))
    pos = max(0.0, float(pos))
    if duration > 0:
        pos = duration if eof else min(pos, duration)
    entry.update(pos=round(pos, 3), duration=round(duration, 3), seq=int(seq), updatedAt=store.now_iso(moment))
    entry.setdefault("seen", False)
    entry.setdefault("seenAt", None)
    if not entry["seen"] and (eof or (duration > 0 and pos / duration >= threshold)):
        entry["seen"] = True
        entry["seenAt"] = store.now_iso(moment)
    lessons[lesson_id] = entry
    seconds = int(round(min(max(0.0, float(played)), MAX_PLAYED_PER_REPORT)))
    if seconds > 0 and course_id:
        day = state.setdefault("days", {}).setdefault(store.local_day(moment), {})
        day[course_id] = int(day.get(course_id) or 0) + seconds
    if not keep_last:
        state["last"] = {"lessonId": lesson_id, "at": store.now_iso(moment)}
    return True


def set_seen(state, lesson_id, seen, moment=None):
    entry = state.setdefault("lessons", {}).setdefault(lesson_id, {})
    if seen:
        entry["seen"] = True
        entry["seenAt"] = entry.get("seenAt") or store.now_iso(moment)
    else:
        entry["seen"] = False
        entry["seenAt"] = None
        entry["pos"] = 0.0


def day_total(days, day):
    values = (days or {}).get(day) or {}
    return int(sum(v for v in values.values() if isinstance(v, (int, float)) and not isinstance(v, bool)))


def streak(days, today, min_seconds):
    """Days in a row with at least min_seconds of study, ending today, or yesterday
    while today is not done yet."""
    min_seconds = max(1, int(min_seconds))
    day = datetime.date.fromisoformat(today)
    if day_total(days, today) < min_seconds:
        day -= datetime.timedelta(days=1)
    count = 0
    while day_total(days, day.isoformat()) >= min_seconds:
        count += 1
        day -= datetime.timedelta(days=1)
    return count


def _pick(ids, lessons, current):
    if current in ids and not is_finished(lessons.get(current)):
        return current
    start = ids.index(current) + 1 if current in ids else 0
    for lesson_id in ids[start:] + ids[:start]:
        if not is_finished(lessons.get(lesson_id)):
            return lesson_id
    return None


def resume_lesson(order, state, course_id=None):
    """The lesson to play. Without a course: the last one played, or the next unseen
    in its course. With a course: its most recent lesson, or its next unseen."""
    lessons = state.get("lessons") or {}
    if course_id is None:
        last = (state.get("last") or {}).get("lessonId")
        if not last:
            return None
        owner = next((cid for cid, ids in order.items() if last in ids), None)
        if owner is None:
            return None if is_finished(lessons.get(last)) else last
        return _pick(order[owner], lessons, last)
    ids = order.get(course_id)
    if ids is None:
        return None
    touched = [i for i in ids if (lessons.get(i) or {}).get("updatedAt")]
    recent = max(touched, key=lambda i: lessons[i]["updatedAt"]) if touched else None
    return _pick(ids, lessons, recent)
