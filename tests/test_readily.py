import json
import os
import stat
import unittest

from support import TempHome
from syllabus import readily
from syllabus.errors import SyllabusError

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
data = sys.stdin.read() if "--stdin" in sys.argv else ""
with open(os.environ["FAKE_READILY_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "stdin": data}) + "\n")
command = sys.argv[1]
if command == "list":
    print(json.dumps({"folder": "/v", "tags": [], "sections": [{"name": "Cursos", "error": "", "tags": [], "items": [
        {"index": 0, "kind": "text", "title": "Repo", "description": "", "tags": ["cursos/llm"], "inheritedTags": [],
         "preview": "https://github.com/x", "lineCount": 1, "search": "https://github.com/x", "image": "",
         "missing": False, "hash": "abc"},
        {"index": 1, "kind": "image", "title": "Diagram", "description": "", "tags": [], "inheritedTags": [],
         "preview": "", "lineCount": 0, "search": "", "image": "/v/a.png", "missing": False, "hash": "def"},
        {"index": 2, "kind": "text", "title": "Long", "description": "", "tags": [], "inheritedTags": [],
         "preview": "x", "lineCount": 1, "search": "x" * 4096, "image": "", "missing": False, "hash": "ghi"}]}]}))
elif command == "save":
    # Parsed the way the real Readily parses it, so a value that looks like an option fails here too.
    import argparse
    parser = argparse.ArgumentParser(prog="readily save")
    parser.add_argument("section")
    parser.add_argument("--title", default="")
    parser.add_argument("--tag", action="append")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--stdin", action="store_true")
    parser.parse_args(sys.argv[2:])
    print("Saved to " + sys.argv[2])
elif command == "copy" and sys.argv[3] == "9":
    print("readily: That item changed", file=sys.stderr)
    sys.exit(3)
elif command == "copy" and sys.argv[3] == "8":
    print("readily: Nothing to copy", file=sys.stderr)
    sys.exit(1)
'''


def install_fake_readily(tmp):
    """Point SYLLABUS_READILY_BIN at the fake; returns the log it appends every call to."""
    binary = os.path.join(tmp, "fake-readily")
    with open(binary, "w", encoding="utf-8") as f:
        f.write(FAKE)
    os.chmod(binary, os.stat(binary).st_mode | stat.S_IXUSR)
    log = os.path.join(tmp, "readily.log")
    os.environ["SYLLABUS_READILY_BIN"] = binary
    os.environ["FAKE_READILY_LOG"] = log
    return log


def read_calls(log):
    if not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class Tags(unittest.TestCase):
    def test_normalize_tag_matches_readily(self):
        self.assertEqual(readily.normalize_tag("#Chi Project"), "chi-project")
        self.assertEqual(readily.normalize_tag("  ##pepe/ "), "pepe")
        self.assertEqual(readily.normalize_tag("chi//db"), "chi/db")
        self.assertEqual(readily.normalize_tag("a+b!c"), "abc")
        self.assertEqual(readily.normalize_tag("Configuración"), "configuración")
        for value in ("", "#", "123", "1/2", "!!!"):
            self.assertEqual(readily.normalize_tag(value), "", value)

    def test_course_and_roadmap_tags(self):
        self.assertEqual(readily.course_tag("Search, Graphs and AI Agents with Python"),
                         "cursos/search-graphs-and-ai-agents-with-python")
        self.assertEqual(readily.course_tag("A/B"), "cursos/a-b")
        self.assertEqual(readily.course_tag("123"), "cursos/course")
        self.assertEqual(readily.roadmap_tag("AI Engineering"), "cursos/roadmap-ai-engineering")


class Cli(TempHome):
    def setUp(self):
        super().setUp()
        self.log = install_fake_readily(self.tmp)

    def test_save(self):
        self.assertEqual(readily.save("Cursos", "Repo", "cursos/llm", "https://github.com/x"), "Saved to Cursos")
        self.assertEqual(read_calls(self.log), [{"argv": ["save", "Cursos", "--stdin", "--create", "--title=Repo",
                                                          "--tag=cursos/llm"], "stdin": "https://github.com/x"}])

    def test_save_without_title(self):
        readily.save("Cursos", "  ", "cursos/llm", "pip install x")
        self.assertEqual(read_calls(self.log)[0]["argv"], ["save", "Cursos", "--stdin", "--create", "--tag=cursos/llm"])

    def test_save_a_title_and_tag_that_look_like_options(self):
        self.assertEqual(readily.save("Cursos", "-intro", "-v", "pip install x"), "Saved to Cursos")
        self.assertEqual(read_calls(self.log)[0]["argv"],
                         ["save", "Cursos", "--stdin", "--create", "--title=-intro", "--tag=-v"])

    def test_list_items(self):
        result = readily.list_items("cursos/llm")
        self.assertEqual(result["warning"], "")
        self.assertEqual([i["title"] for i in result["items"]], ["Repo", "Long"])
        repo, long_item = result["items"]
        self.assertEqual((repo["section"], repo["index"], repo["hash"], repo["isUrl"], repo["truncated"]),
                         ("Cursos", 0, "abc", True, False))
        self.assertTrue(long_item["truncated"])
        self.assertEqual(read_calls(self.log)[0]["argv"], ["list", "--json", "--tag=cursos/llm"])

    def test_copy(self):
        readily.copy("Cursos", 0, "abc")
        self.assertEqual(read_calls(self.log)[0]["argv"], ["copy", "Cursos", "0", "abc"])

    def test_copy_stale_item(self):
        with self.assertRaises(SyllabusError) as caught:
            readily.copy("Cursos", 9, "abc")
        self.assertEqual(caught.exception.code, 6)
        self.assertIn("changed", str(caught.exception))

    def test_copy_error_message(self):
        with self.assertRaises(SyllabusError) as caught:
            readily.copy("Cursos", 8, "x")
        self.assertEqual(str(caught.exception), "Nothing to copy")

    def test_missing_binary(self):
        os.environ["SYLLABUS_READILY_BIN"] = os.path.join(self.tmp, "nope")
        self.assertEqual(readily.list_items("cursos/x"), {"items": [], "warning": "Readily is not installed"})
        with self.assertRaises(SyllabusError) as caught:
            readily.save("Cursos", "", "cursos/x", "t")
        self.assertEqual(caught.exception.code, 6)


class NoFakeInstalled(TempHome):
    """A plain TempHome, with no install_fake_readily() call: must never reach the user's
    real Readily binary, even though it exists on this machine."""

    def test_find_binary_is_none_without_a_fake(self):
        self.assertIsNone(readily.find_binary())

    def test_save_raises_without_running_anything(self):
        def run(*args, **kwargs):
            self.fail("must not run a subprocess when no Readily binary is configured")

        with self.assertRaises(SyllabusError) as caught:
            readily.save("Cursos", "", "cursos/x", "t", run=run)
        self.assertEqual(caught.exception.code, 6)


if __name__ == "__main__":
    unittest.main()
