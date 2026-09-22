.pragma library

// Pure helpers for the Syllabus window: formatting, parsing and filtering.
// No QML in here, so tests/model.test.js runs them under Node.

var ICON = {
  school: 0xF0474, play: 0xF040A, check: 0xF012C, boxEmpty: 0xF0131, boxChecked: 0xF0135,
  bookmark: 0xF00C0, link: 0xF0337, plus: 0xF0415, trash: 0xF01B4, pencil: 0xF03EB,
  up: 0xF005D, down: 0xF0045, chevronLeft: 0xF0141, chevronRight: 0xF0142, chevronDown: 0xF0140,
  close: 0xF0156, cog: 0xF0493, roadmap: 0xF046A, library: 0xF0331, fire: 0xF0238, file: 0xF0219,
  copy: 0xF018F, open: 0xF03CC, eyeOff: 0xF0209, eye: 0xF0208, note: 0xF082E, refresh: 0xF0450,
  disk: 0xF02CA, save: 0xF0193, pin: 0xF0403, pinOff: 0xF0404,
  web: 0xF059F, download: 0xF01DA, stop: 0xF04DB
}

function icon(name) {
  return ICON[name] ? String.fromCodePoint(ICON[name]) : "?"
}

function pad2(n) {
  return (n < 10 ? "0" : "") + n
}

function fmtClock(seconds) {
  var total = Math.max(0, Math.floor(Number(seconds) || 0))
  var h = Math.floor(total / 3600)
  var m = Math.floor((total % 3600) / 60)
  var s = total % 60
  return h > 0 ? h + ":" + pad2(m) + ":" + pad2(s) : m + ":" + pad2(s)
}

// Totals and what is left: "45 min", "3h 05m".
function fmtDuration(seconds) {
  var minutes = Math.round((Number(seconds) || 0) / 60)
  if (minutes < 60) return minutes + " min"
  return Math.floor(minutes / 60) + "h " + pad2(minutes % 60) + "m"
}

// Study time, as `syllabus summary` writes it: "25 min", "1h20".
function fmtStudy(seconds) {
  var minutes = Math.round((Number(seconds) || 0) / 60)
  if (minutes < 60) return minutes + " min"
  return Math.floor(minutes / 60) + "h" + pad2(minutes % 60)
}

function fmtWhen(iso) {
  var t = Date.parse(String(iso || ""))
  if (isNaN(t)) return "never"
  var d = new Date(t)
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) + " "
    + pad2(d.getHours()) + ":" + pad2(d.getMinutes())
}

function fmtAgo(iso) {
  if (!iso) return ""
  var seconds = (Date.now() - Date.parse(iso)) / 1000
  if (!isFinite(seconds)) return ""
  if (seconds < 60) return "just now"
  if (seconds < 3600) return Math.floor(seconds / 60) + " min ago"
  if (seconds < 24 * 3600) return Math.floor(seconds / 3600) + " h ago"
  var days = Math.round(seconds / (24 * 3600))
  return days === 1 ? "yesterday" : days + " days ago"
}

// "YouTube playlist · 24 videos · updated 2 h ago", or why the last read failed.
function webSourceLine(course) {
  var web = course && course.web
  if (!web) return ""
  if (web.error) return "Couldn't refresh: " + web.error
  var site = /vimeo\.com/.test(web.url || "") ? "Vimeo" : "YouTube"
  var parts = [web.kind === "playlist" ? site + " playlist" : site,
               web.videoCount + (web.videoCount === 1 ? " video" : " videos")]
  if (web.goneCount > 0) parts.push(web.goneCount + " not available")
  if (web.fetchedAt) parts.push("updated " + fmtAgo(web.fetchedAt))
  return parts.join(" · ")
}

// "95", "1:35" or "1:23:40" (seconds may have decimals) to seconds; -1 when it is none of those.
function parseTimestamp(text) {
  var t = String(text || "").trim()
  if (!/^\d+(\.\d+)?$|^\d+:\d{1,2}(\.\d+)?$|^\d+:\d{1,2}:\d{1,2}(\.\d+)?$/.test(t)) return -1
  var parts = t.split(":").map(Number)
  for (var i = 1; i < parts.length; i++) if (parts[i] >= 60) return -1
  var seconds = 0
  for (var j = 0; j < parts.length; j++) seconds = seconds * 60 + parts[j]
  return seconds
}

function fraction(pos, duration) {
  var d = Number(duration) || 0
  if (d <= 0) return 0
  return Math.max(0, Math.min(1, (Number(pos) || 0) / d))
}

function lessonStatus(lesson) {
  if (!lesson) return "new"
  if (lesson.seen) return "seen"
  return (Number(lesson.pos) || 0) > 0 ? "started" : "new"
}

function progressLabel(item) {
  if (!item || !(item.duration > 0)) return "No videos"
  if (item.remaining <= 0) return "Done"
  return Math.round(item.percent) + "% · " + fmtDuration(item.remaining) + " left"
}

function isUrl(text) {
  return /^https?:\/\/\S+$/.test(String(text || "").trim())
}

// Lowercase without accents, for searching: "Avanzádo" -> "avanzado".
function fold(text) {
  var s = String(text || "")
  if (typeof s.normalize === "function") s = s.normalize("NFD")
  return s.replace(/[̀-ͯ]/g, "").toLowerCase()
}

// topic: "" every course, "__none__" courses without topic, else that topic.
function filterCourses(courses, query, topic) {
  var q = fold(query).trim()
  return (courses || []).filter(function(c) {
    if (topic === "__none__" && c.topic !== "") return false
    if (topic && topic !== "__none__" && c.topic !== topic) return false
    return q === "" || fold(c.title + " " + c.topic).indexOf(q) !== -1
  })
}

// Groups in the order the courses come (bin/syllabus sorts them by topic, then title).
function groupByTopic(courses) {
  var groups = []
  var index = {}
  var list = courses || []
  list.forEach(function(c) {
    var key = c.topic || ""
    if (!(key in index)) {
      index[key] = groups.length
      groups.push({ topic: key, courses: [] })
    }
    groups[index[key]].courses.push(c)
  })
  return groups
}

// Topics with their course count; courses without topic last, as topic "".
// Empty when no course has a topic (the sidebar then shows only "All courses").
function topicCounts(courses) {
  var out = []
  var index = {}
  var none = 0
  var list = courses || []
  list.forEach(function(c) {
    if (!c.topic) { none++; return }
    if (!(c.topic in index)) {
      index[c.topic] = out.length
      out.push({ topic: c.topic, count: 0 })
    }
    out[index[c.topic]].count++
  })
  if (none > 0 && out.length > 0) out.push({ topic: "", count: none })
  return out
}

function visibleLessons(lessons, showHidden) {
  return (lessons || []).filter(function(l) { return showHidden || !l.hidden })
}

function hiddenCount(lessons) {
  return (lessons || []).filter(function(l) { return l.hidden }).length
}

// True where a lesson starts a new subfolder group ("extras", "part 2").
function showGroup(lessons, i) {
  var lesson = lessons[i]
  if (!lesson || !lesson.group) return false
  return i === 0 || lessons[i - 1].group !== lesson.group
}

function daysLabel(n) {
  return n + (n === 1 ? " day" : " days")
}

function initials(title) {
  var words = String(title || "").split(/[\s_\-]+/).filter(function(w) { return w.length > 0 })
  var big = words.filter(function(w) { return w.length > 2 })
  var use = big.length > 0 ? big : words
  return use.slice(0, 2).map(function(w) { return w.charAt(0).toUpperCase() }).join("") || "?"
}

function fmtBytes(n) {
  var v = Number(n) || 0
  if (v < 1024) return v + " B"
  var units = ["KB", "MB", "GB", "TB"]
  var i = -1
  do {
    v /= 1024
    i++
  } while (v >= 1024 && i < units.length - 1)
  return (v < 10 ? v.toFixed(1) : String(Math.round(v))) + " " + units[i]
}

// First non-empty line, cut to max characters.
function preview(text, max) {
  var lines = String(text || "").split("\n").map(function(s) { return s.trim() }).filter(function(s) { return s !== "" })
  var line = lines.length > 0 ? lines[0] : ""
  var limit = max || 80
  return line.length > limit ? line.slice(0, limit - 1) + "…" : line
}

function courseOptions(courses, excludeIds) {
  var skip = {}
  var ids = excludeIds || []
  ids.forEach(function(id) { skip[id] = true })
  return (courses || []).filter(function(c) { return !skip[c.id] }).map(function(c) {
    return { value: c.id, label: c.title, description: (c.topic ? c.topic + " · " : "") + fmtDuration(c.duration) }
  })
}

function linkText(link) {
  return link.kind === "link" ? link.url : link.text
}

function splitArgs(text) {
  return String(text || "").trim().split(/\s+/).filter(function(s) { return s !== "" })
}

// "es, en" or "es,en " -> ["es", "en"]; anything empty falls out.
function splitLangs(text) {
  return String(text || "").split(",").map(function(part) { return part.trim() }).filter(function(part) {
    return part !== ""
  })
}

// The first course of the roadmap, in stage order, with something left to watch.
function nextCourse(roadmap, courseMap) {
  var stages = (roadmap && roadmap.stages) || []
  for (var i = 0; i < stages.length; i++) {
    for (var j = 0; j < stages[i].courseIds.length; j++) {
      var c = courseMap[stages[i].courseIds[j]]
      if (c && c.lessonCount > 0 && c.remaining > 0) return c.id
    }
  }
  return ""
}
