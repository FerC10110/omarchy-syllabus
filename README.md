# Syllabus

An [Omarchy](https://omarchy.org) shell plugin to study the video courses on your disk.

- **Roadmaps**: stages in order, each with courses in order. A course can be in several roadmaps.
  A roadmap shows just its progress, courses, tasks and links; "Edit" brings up the controls to change it.
- **Resume anywhere**: videos play in mpv and start again where you left them, even the next day.
  A video counts as watched from 90 %.
- **Progress**: per video, per course (percent and hours left), per stage and roadmap.
- **Tasks**: checklists per course, per stage and per roadmap.
- **Bookmarks**: press `b` in mpv to bookmark a moment; they show as chapters and in the panel.
- **Links and snippets** per course and roadmap, saved to and read from the Readily plugin
  (`io.github.ferc10110.readily`) with a `cursos/<course>` tag (`cursos/roadmap-<roadmap>` for a roadmap's).
- **Notes** (Markdown) and the **course files** (PDFs, text…) one click away.
- **Study time**: minutes per day and a streak.
- **Curation without touching the disk**: rename, hide, reorder, topics, covers, and how a folder
  splits into courses. Everything lives in `~/.config/syllabus`; the course files are never changed.

## Install

```bash
git clone https://github.com/FerC10110/omarchy-syllabus ~/.config/omarchy/plugins/io.github.ferc10110.syllabus
omarchy bar put io.github.ferc10110.syllabus
```

The panel opens from the bar icon, so it only works while the widget is in the bar (removing it from
`bar.layout` in `~/.config/omarchy/shell.json`, or `omarchy plugin disable io.github.ferc10110.syllabus`,
disables both).

Needs `mpv`, `ffprobe` (ffmpeg), `wl-clipboard` and `xdg-utils`, all part of Omarchy.

## Use

| | |
|---|---|
| Click the icon, or `SUPER+ALT+E` | open or close the panel, under the icon like the shell's own panels |
| Right click, or `SUPER+ALT+R` | continue the last video (then the next course of its roadmap) |
| `b` in mpv | bookmark the current moment |
| `Esc` | back, or close the panel |
| Pin button (bottom of the sidebar) | keep the panel open: clicks outside it reach the windows below (mpv) |
| Drag the `◢` corner | resize the panel; the size is remembered |

A click outside the panel closes it, and so does starting a video, unless the panel is pinned.
With more than one monitor, a pinned panel still takes the clicks on the other monitors
(it stays open, but the click doesn't reach the window there).

Syllabus looks for courses in `~/Videos/Courses`. For another folder or disk, set it in
`~/.config/syllabus/config.json`:

```json
{ "roots": [{ "id": "main", "path": "/run/media/you/disk/courses" }] }
```

The disk does not need to be mounted to browse and edit; only to play.

A video renamed or moved on the disk keeps its progress, title and bookmarks if the very next scan
sees the old file gone and the new one there (same name and size, or the only file of that size). If
a scan in between saw neither, it comes back as a new, unwatched video.

How folders become courses: a folder with videos is a course (videos in its subfolders are
grouped by subfolder). A folder without videos of its own but with two or more subfolders that
have videos is a collection: each subfolder is a course, and the folder is their topic. Change it
per folder in "Edit course".

## Files

| Path | What |
|---|---|
| `~/.config/syllabus/config.json` | settings |
| `~/.config/syllabus/library.json` | roadmaps, tasks, links, bookmarks and your edits |
| `~/.config/syllabus/notes/` | one Markdown note per course |
| `~/.local/state/syllabus/state.json` | where each video was left, watched videos, study time |
| `~/.cache/syllabus/` | durations and folder tree of the last scan, cached covers |

## Command line

`bin/syllabus` prints JSON: `view`, `scan [--force]`, `summary`, `play <videoId> [--at S]`,
`resume [courseId] [--notify]`, `files`, `covers`, `note-get`, `readily-items`, `config`, and
`apply` (one change as JSON on stdin). mpv calls `report`, `bookmarks` and `bookmark-here`.

## Development

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node --test tests/model.test.js
```

The shell reloads every plugin when anything in this folder changes: nothing may write here while
it runs (no `__pycache__`: the launcher and the tests turn bytecode off). That reload does not pick
up changes to QML files the shell has already loaded: run `omarchy restart shell` to see them.

## License

MIT
