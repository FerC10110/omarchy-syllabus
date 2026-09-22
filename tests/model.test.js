const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")

const source = fs.readFileSync(path.join(__dirname, "..", "SyllabusModel.js"), "utf8").replace(/^\.pragma library\s*$/m, "")
const M = new Function(source + `
return { ICON, icon, fmtClock, fmtDuration, fmtStudy, fmtWhen, parseTimestamp, fraction, lessonStatus, isUrl,
         fold, filterCourses, groupByTopic, topicCounts, visibleLessons, hiddenCount, showGroup, daysLabel,
         initials, fmtBytes, preview, progressLabel, courseOptions, linkText, splitArgs, nextCourse,
         fmtAgo, webSourceLine, splitLangs }`)()

test("icons are single glyphs", () => {
  assert.equal(M.icon("play"), String.fromCodePoint(0xF040A))
  assert.equal(M.icon("nope"), "?")
  for (const name of Object.keys(M.ICON)) assert.equal([...M.icon(name)].length, 1, name)
})

test("clock and durations", () => {
  assert.equal(M.fmtClock(5020.7), "1:23:40")
  assert.equal(M.fmtClock(65), "1:05")
  assert.equal(M.fmtClock(-3), "0:00")
  assert.equal(M.fmtClock(null), "0:00")
  assert.equal(M.fmtDuration(45 * 60), "45 min")
  assert.equal(M.fmtDuration(3 * 3600 + 5 * 60), "3h 05m")
  assert.equal(M.fmtStudy(4800), "1h20")
  assert.equal(M.fmtStudy(1500), "25 min")
})

test("fmtWhen is local time, or never", () => {
  assert.equal(M.fmtWhen(new Date(2026, 8, 19, 9, 5).toISOString()), "2026-09-19 09:05")
  assert.equal(M.fmtWhen(""), "never")
  assert.equal(M.fmtWhen("garbage"), "never")
})

test("parseTimestamp", () => {
  assert.equal(M.parseTimestamp("95"), 95)
  assert.equal(M.parseTimestamp("1:35"), 95)
  assert.equal(M.parseTimestamp(" 1:23:40 "), 5020)
  assert.equal(M.parseTimestamp("12.5"), 12.5)
  assert.equal(M.parseTimestamp("1:75"), -1)
  assert.equal(M.parseTimestamp("abc"), -1)
  assert.equal(M.parseTimestamp(""), -1)
  assert.equal(M.parseTimestamp("1:2:3:4"), -1)
})

test("progress helpers", () => {
  assert.equal(M.fraction(50, 200), 0.25)
  assert.equal(M.fraction(500, 200), 1)
  assert.equal(M.fraction(5, 0), 0)
  assert.equal(M.lessonStatus({ seen: true, pos: 0 }), "seen")
  assert.equal(M.lessonStatus({ seen: false, pos: 10 }), "started")
  assert.equal(M.lessonStatus({ seen: false, pos: 0 }), "new")
  assert.equal(M.progressLabel({ duration: 0 }), "No videos")
  assert.equal(M.progressLabel({ duration: 7200, remaining: 0, percent: 100 }), "Done")
  assert.equal(M.progressLabel({ duration: 7200, remaining: 3000, percent: 58.3 }), "58% · 50 min left")
})

const COURSES = [
  { id: "a", title: "RAG avanzado", topic: "LLM", duration: 3600, remaining: 0, lessonCount: 2 },
  { id: "b", title: "Agents", topic: "LLM", duration: 7200, remaining: 7200, lessonCount: 3 },
  { id: "c", title: "Statistics", topic: "", duration: 600, remaining: 600, lessonCount: 1 },
]

test("filter and group courses", () => {
  assert.deepEqual(M.filterCourses(COURSES, "rag", "").map(c => c.id), ["a"])
  assert.deepEqual(M.filterCourses(COURSES, "avanzádo", "").map(c => c.id), ["a"])
  assert.deepEqual(M.filterCourses(COURSES, "llm", "").map(c => c.id), ["a", "b"])
  assert.deepEqual(M.filterCourses(COURSES, "", "LLM").map(c => c.id), ["a", "b"])
  assert.deepEqual(M.filterCourses(COURSES, "", "__none__").map(c => c.id), ["c"])
  assert.deepEqual(M.groupByTopic(COURSES).map(g => [g.topic, g.courses.length]), [["LLM", 2], ["", 1]])
  assert.deepEqual(M.topicCounts(COURSES), [{ topic: "LLM", count: 2 }, { topic: "", count: 1 }])
  assert.deepEqual(M.topicCounts([COURSES[2]]), [])
  assert.deepEqual(M.courseOptions(COURSES, ["a"]).map(o => o.value), ["b", "c"])
  assert.equal(M.courseOptions(COURSES, [])[1].description, "LLM · 2h 00m")
  assert.equal(M.courseOptions(COURSES, [])[2].description, "10 min")
})

test("lessons", () => {
  const lessons = [{ id: "1", hidden: false, group: "" }, { id: "2", hidden: true, group: "" },
                   { id: "3", hidden: false, group: "extras" }, { id: "4", hidden: false, group: "extras" }]
  assert.deepEqual(M.visibleLessons(lessons, false).map(l => l.id), ["1", "3", "4"])
  assert.equal(M.visibleLessons(lessons, true).length, 4)
  assert.equal(M.hiddenCount(lessons), 1)
  assert.deepEqual([0, 1, 2, 3].map(i => M.showGroup(lessons, i)), [false, false, true, false])
})

test("text helpers", () => {
  assert.equal(M.daysLabel(1), "1 day")
  assert.equal(M.daysLabel(0), "0 days")
  assert.equal(M.initials("Graphs of Agents"), "GA")
  assert.equal(M.initials("RAG"), "R")
  assert.equal(M.initials(""), "?")
  assert.equal(M.fmtBytes(512), "512 B")
  assert.equal(M.fmtBytes(1536), "1.5 KB")
  assert.equal(M.fmtBytes(25 * 1024 * 1024), "25 MB")
  assert.equal(M.preview("\n  first line  \nsecond", 80), "first line")
  assert.equal(M.preview("abcdefghij", 5), "abcd…")
  assert.equal(M.isUrl(" https://x.org/a "), true)
  assert.equal(M.isUrl("see https://x.org"), false)
  assert.equal(M.linkText({ kind: "link", url: "u" }), "u")
  assert.equal(M.linkText({ kind: "snippet", text: "t" }), "t")
  assert.deepEqual(M.splitArgs("  --fs   --volume=50 "), ["--fs", "--volume=50"])
  assert.deepEqual(M.splitArgs(""), [])
})

test("nextCourse skips finished and missing courses", () => {
  const map = Object.fromEntries(COURSES.map(c => [c.id, c]))
  assert.equal(M.nextCourse({ stages: [{ courseIds: ["a"] }, { courseIds: ["zz", "b", "c"] }] }, map), "b")
  assert.equal(M.nextCourse({ stages: [{ courseIds: ["a"] }] }, map), "")
  assert.equal(M.nextCourse(null, map), "")
})

test("fmtAgo reads as a person would say it", () => {
  const now = Date.now()
  assert.equal(M.fmtAgo(new Date(now - 30 * 1000).toISOString()), "just now")
  assert.equal(M.fmtAgo(new Date(now - 90 * 60 * 1000).toISOString()), "1 h ago")
  assert.equal(M.fmtAgo(new Date(now - 26 * 3600 * 1000).toISOString()), "yesterday")
  assert.equal(M.fmtAgo(new Date(now - 5 * 24 * 3600 * 1000).toISOString()), "5 days ago")
  assert.equal(M.fmtAgo(""), "")
})

test("splitLangs reads a comma-separated list", () => {
  assert.deepEqual(M.splitLangs(" es , en "), ["es", "en"])
  assert.deepEqual(M.splitLangs(""), [])
  assert.deepEqual(M.splitLangs("es,,"), ["es"])
})

test("the source line says where a web course came from", () => {
  const fresh = new Date(Date.now() - 2 * 3600 * 1000).toISOString()
  assert.equal(M.webSourceLine({ web: { kind: "playlist", videoCount: 24, goneCount: 0, fetchedAt: fresh } }),
               "YouTube playlist · 24 videos · updated 2 h ago")
  assert.equal(M.webSourceLine({ web: { kind: "video", videoCount: 1, goneCount: 0, fetchedAt: fresh,
                                        url: "https://vimeo.com/1" } }),
               "Vimeo · 1 video · updated 2 h ago")
  assert.equal(M.webSourceLine({ web: { kind: "playlist", videoCount: 3, goneCount: 1, fetchedAt: fresh } }),
               "YouTube playlist · 3 videos · 1 not available · updated 2 h ago")
  assert.equal(M.webSourceLine({ web: { error: "no internet" } }), "Couldn't refresh: no internet")
  assert.equal(M.webSourceLine({ web: null }), "")
})
