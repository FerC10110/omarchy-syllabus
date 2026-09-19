import datetime
import unittest

from support import local_tz
from syllabus import progress, store

T0 = datetime.datetime(2026, 9, 19, 15, 0, tzinfo=datetime.timezone.utc)
LESSON = "main:A/1.mp4"


class Reports(unittest.TestCase):
    def setUp(self):
        self.state = store.empty_state()

    def report(self, **overrides):
        args = dict(lesson_id=LESSON, course_id="main:A", pos=100.0, duration=1000.0, played=30.0,
                    seq=1, eof=False, threshold=0.9, moment=T0)
        args.update(overrides)
        return progress.apply_report(self.state, **args)

    def entry(self):
        return self.state["lessons"][LESSON]

    def test_first_report(self):
        self.assertTrue(self.report())
        e = self.entry()
        self.assertEqual((e["pos"], e["duration"], e["seq"], e["seen"], e["seenAt"]), (100.0, 1000.0, 1, False, None))
        self.assertEqual(e["updatedAt"], "2026-09-19T15:00:00+00:00")
        self.assertEqual(self.state["last"], {"lessonId": LESSON, "at": "2026-09-19T15:00:00+00:00"})

    def test_older_or_equal_seq_is_ignored(self):
        self.report(seq=5, pos=500.0)
        self.assertFalse(self.report(seq=4, pos=10.0))
        self.assertFalse(self.report(seq=5, pos=10.0))
        self.assertEqual(self.entry()["pos"], 500.0)

    def test_seen_at_threshold(self):
        self.report(pos=899.0)
        self.assertFalse(self.entry()["seen"])
        self.report(seq=2, pos=900.0)
        self.assertTrue(self.entry()["seen"])
        self.assertEqual(self.entry()["seenAt"], "2026-09-19T15:00:00+00:00")

    def test_seen_stays_when_rewatching(self):
        self.report(pos=950.0)
        self.report(seq=2, pos=10.0)
        self.assertEqual((self.entry()["seen"], self.entry()["pos"]), (True, 10.0))

    def test_eof_marks_seen_at_the_end(self):
        self.report(pos=400.0, eof=True)
        self.assertEqual((self.entry()["pos"], self.entry()["seen"]), (1000.0, True))

    def test_pos_is_clamped(self):
        self.report(pos=5000.0)
        self.assertEqual(self.entry()["pos"], 1000.0)
        self.report(seq=2, pos=-3.0)
        self.assertEqual(self.entry()["pos"], 0.0)

    def test_played_seconds_go_to_the_local_day(self):
        late = datetime.datetime(2026, 9, 19, 2, 30, tzinfo=datetime.timezone.utc)
        with local_tz("America/Argentina/Buenos_Aires"):
            self.report(moment=late, played=40.4)
            self.report(seq=2, moment=late, played=20.0)
        self.assertEqual(self.state["days"], {"2026-09-18": {"main:A": 60}})

    def test_keep_last_saves_everything_but_last(self):
        # The end-file report of a video mpv just replaced: `last` already names the new one.
        self.report(lesson_id="main:A/2.mp4")
        self.assertTrue(self.report(pos=950.0, seq=2, played=12.0, keep_last=True))
        self.assertEqual((self.entry()["pos"], self.entry()["seen"]), (950.0, True))
        self.assertEqual(self.state["last"]["lessonId"], "main:A/2.mp4")
        self.assertEqual(self.state["days"], {store.local_day(T0): {"main:A": 42}})

    def test_played_without_course_is_not_counted(self):
        self.report(course_id="")
        self.assertEqual(self.state["days"], {})


class Positions(unittest.TestCase):
    def test_start_position(self):
        self.assertEqual(progress.start_position(None, 5), 0.0)
        self.assertEqual(progress.start_position({"pos": 100, "duration": 1000}, 5), 95.0)
        self.assertEqual(progress.start_position({"pos": 3, "duration": 1000}, 5), 0.0)
        self.assertEqual(progress.start_position({"pos": 980, "duration": 1000}, 5), 0.0)
        self.assertEqual(progress.start_position({"pos": 100, "duration": 0}, 5), 95.0)

    def test_is_finished(self):
        self.assertFalse(progress.is_finished(None))
        self.assertFalse(progress.is_finished({"pos": 100, "duration": 1000}))
        self.assertTrue(progress.is_finished({"seen": True, "pos": 0, "duration": 1000}))
        self.assertTrue(progress.is_finished({"pos": 975, "duration": 1000}))
        self.assertFalse(progress.is_finished({"pos": 0, "duration": 20}))

    def test_set_seen(self):
        state = store.empty_state()
        progress.set_seen(state, "x", True, T0)
        self.assertEqual(state["lessons"]["x"], {"seen": True, "seenAt": "2026-09-19T15:00:00+00:00"})
        state["lessons"]["x"]["pos"] = 500.0
        progress.set_seen(state, "x", False)
        self.assertEqual(state["lessons"]["x"], {"seen": False, "seenAt": None, "pos": 0.0})


class Streaks(unittest.TestCase):
    def test_streak_counts_back_from_today(self):
        days = {"2026-09-19": {"a": 700}, "2026-09-18": {"a": 300, "b": 400},
                "2026-09-17": {"a": 100}, "2026-09-16": {"a": 900}}
        self.assertEqual(progress.streak(days, "2026-09-19", 600), 2)

    def test_today_not_done_yet_keeps_yesterdays_streak(self):
        days = {"2026-09-18": {"a": 900}, "2026-09-17": {"a": 900}}
        self.assertEqual(progress.streak(days, "2026-09-19", 600), 2)

    def test_no_study(self):
        self.assertEqual(progress.streak({}, "2026-09-19", 600), 0)
        self.assertEqual(progress.streak({}, "2026-09-19", 0), 0)

    def test_day_total(self):
        days = {"2026-09-18": {"a": 300, "b": 400}}
        self.assertEqual(progress.day_total(days, "2026-09-18"), 700)
        self.assertEqual(progress.day_total(days, "2026-09-19"), 0)


class Resume(unittest.TestCase):
    ORDER = {"c1": ["a", "b", "c"], "c2": ["x", "y"]}

    def state(self, lessons, last=None):
        s = store.empty_state()
        s["lessons"] = lessons
        s["last"] = {"lessonId": last, "at": ""} if last else None
        return s

    def test_nothing_played(self):
        self.assertIsNone(progress.resume_lesson(self.ORDER, self.state({})))

    def test_last_unfinished(self):
        state = self.state({"b": {"pos": 10, "duration": 100}}, last="b")
        self.assertEqual(progress.resume_lesson(self.ORDER, state), "b")

    def test_last_finished_goes_to_the_next_unseen(self):
        state = self.state({"b": {"seen": True, "pos": 100, "duration": 100}}, last="b")
        self.assertEqual(progress.resume_lesson(self.ORDER, state), "c")

    def test_wraps_to_an_earlier_unseen(self):
        state = self.state({"c": {"seen": True}}, last="c")
        self.assertEqual(progress.resume_lesson(self.ORDER, state), "a")

    def test_course_all_seen(self):
        state = self.state({i: {"seen": True} for i in "abc"}, last="c")
        self.assertIsNone(progress.resume_lesson(self.ORDER, state))

    def test_course_without_history_starts_at_the_first_unseen(self):
        state = self.state({"a": {"seen": True}})
        self.assertEqual(progress.resume_lesson(self.ORDER, state, "c1"), "b")

    def test_course_uses_its_most_recent_lesson(self):
        state = self.state({"a": {"pos": 10, "duration": 100, "updatedAt": "2026-09-18T10:00:00+00:00"},
                            "c": {"pos": 50, "duration": 100, "updatedAt": "2026-09-19T10:00:00+00:00"}},
                           last="x")
        self.assertEqual(progress.resume_lesson(self.ORDER, state, "c1"), "c")

    def test_unknown_course(self):
        self.assertIsNone(progress.resume_lesson(self.ORDER, self.state({}), "zz"))


if __name__ == "__main__":
    unittest.main()
