"""Readily, the user's snippet plugin: save links and texts into it, list what it
holds for a course, copy an item back. Its CLI is the only way in (as runbook does)."""
import json
import os
import re
import shutil
import subprocess

from . import paths
from .errors import READILY, SyllabusError

READILY_PLUGIN_ID = "io.github.ferc10110.readily"
TAG_PREFIX = "cursos"
SEARCH_CAP = 4096
_URL = re.compile(r"^https?://\S+$")


def _clean(body):
    # Same rules as readily/lib/readily/tags.py: no empty or digits-only tags.
    body = re.sub(r"/+", "/", body).strip("/").lower()
    if not body or all(c.isdigit() or c == "/" for c in body):
        return ""
    return body


def normalize_tag(value):
    """A tag the way Readily writes it: "#Chi Project" -> "chi-project"; "" when nothing valid is left."""
    v = re.sub(r"^#+", "", value.strip()).lower()
    v = re.sub(r"\s+", "-", v)
    v = re.sub(r"[^\w/-]", "", v)
    return _clean(v)


def course_tag(title):
    return f"{TAG_PREFIX}/{normalize_tag(title.replace('/', ' ')) or 'course'}"


def roadmap_tag(title):
    return f"{TAG_PREFIX}/roadmap-{normalize_tag(title.replace('/', ' ')) or 'roadmap'}"


def find_binary(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("SYLLABUS_READILY_BIN")
    if override:
        return override if os.path.isfile(override) else None
    sibling = os.path.join(os.path.dirname(paths.PLUGIN_DIR), READILY_PLUGIN_ID, "bin", "readily")
    if os.path.isfile(sibling):
        return sibling
    return shutil.which("readily", path=environ.get("PATH"))


def _binary():
    binary = find_binary()
    if not binary:
        raise SyllabusError("Readily is not installed", READILY)
    return binary


def _run(argv, stdin=None, run=subprocess.run):
    # Never let Readily read the caller's stdin (the panel's pipe) when there is nothing to send.
    feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        return run(argv, capture_output=True, text=True, timeout=15, **feed)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SyllabusError(f"Readily failed: {e}", READILY)


def _message(result):
    lines = (result.stderr or "").strip().splitlines()
    return (lines[-1] if lines else "Readily failed").removeprefix("readily: ")


def save(section, title, tag, content, run=subprocess.run):
    # "--title=<v>" as one argument: a title like "-intro" would otherwise read as an option.
    argv = [_binary(), "save", section, "--stdin", "--create"]
    if title.strip():
        argv.append(f"--title={title.strip()}")
    argv.append(f"--tag={tag}")
    result = _run(argv, content, run)
    if result.returncode != 0:
        raise SyllabusError(_message(result), READILY)
    return (result.stdout or "").strip()


def list_items(tag, run=subprocess.run):
    """Text items with the tag (nested tags included). Never raises: problems become a warning."""
    binary = find_binary()
    if not binary:
        return {"items": [], "warning": "Readily is not installed"}
    try:
        result = _run([binary, "list", "--json", f"--tag={tag}"], None, run)
    except SyllabusError as e:
        return {"items": [], "warning": str(e)}
    if result.returncode != 0:
        return {"items": [], "warning": _message(result)}
    try:
        data = json.loads(result.stdout or "")
    except ValueError:
        return {"items": [], "warning": "Readily returned an unexpected response"}
    sections = data.get("sections") if isinstance(data, dict) else None
    items = []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if not isinstance(item, dict) or item.get("kind") != "text":
                continue
            text = item.get("search") or ""
            items.append({"section": section.get("name", ""), "index": item.get("index", 0),
                          "hash": item.get("hash", ""), "title": item.get("title", ""),
                          "preview": item.get("preview", ""), "text": text,
                          "truncated": len(text) >= SEARCH_CAP, "isUrl": bool(_URL.match(text.strip()))})
    return {"items": items, "warning": ""}


def copy(section, index, item_hash, run=subprocess.run):
    result = _run([_binary(), "copy", section, str(int(index)), item_hash], None, run)
    if result.returncode == 3:
        raise SyllabusError("That Readily item changed; refresh the list", READILY)
    if result.returncode != 0:
        raise SyllabusError(_message(result), READILY)
