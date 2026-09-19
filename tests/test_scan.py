import os
import unittest

from support import TempHome, make_tree
from syllabus import scan


class Names(unittest.TestCase):
    def test_ext_of(self):
        self.assertEqual(scan.ext_of("1_Intro.\nmkv"), "mkv")
        self.assertEqual(scan.ext_of("Clase.MP4"), "mp4")
        self.assertEqual(scan.ext_of("link"), "")
        self.assertEqual(scan.ext_of(".hidden"), "")

    def test_natural_sort(self):
        names = ["10_b.mp4", "2_a.mp4", "1_c.mp4", "10_b_parte1.mp4", "Intro.mp4"]
        self.assertEqual(sorted(names, key=scan.natural_key),
                         ["1_c.mp4", "2_a.mp4", "10_b.mp4", "10_b_parte1.mp4", "Intro.mp4"])

    def test_course_title(self):
        self.assertEqual(scan.course_title("Intro_to_LLMs_in_8_weeks"), "Intro to LLMs in 8 weeks")

    def test_lesson_titles(self):
        cases = [
            ("1_Intro to RAG.mp4", "Course", 1, ("Intro to RAG", 1)),
            ("17 3 ways to use it.mp4", "Markets", 5, ("3 ways to use it", 17)),
            ("2The role of data.mp4", "Markets", 2, ("The role of data", 2)),
            ("3_2026-07-30 22-07-25.mkv", "Deploying", 3, ("Part 3", 3)),
            ("2026-06-21 11-15-25.mkv", "Models", 4, ("Part 4", None)),
            ("Embeddings.mkv", "Embeddings", 1, ("Part 1", None)),
            ("1_Vector search: the basics\n.mp4", "Vector search: the basics", 1, ("Part 1", 1)),
            ("Résumé review (3).mp4", "Markets", 7, ("Résumé review (3)", None)),
            ("intro_to_embeddings_1.mkv", "Intro to embeddings", 1, ("intro to embeddings 1", None)),
            ("10_Week 5_part1.mp4", "Course", 11, ("Week 5 part1", 10)),
        ]
        for name, course, position, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(scan.lesson_title(name, course, position), expected)


class Walk(TempHome):
    FILES = {
        "Flat_Course/1_a.mp4": 100,
        "Flat_Course/2_b.mp4": 100,
        "Flat_Course/10_c.mp4": 100,
        "Flat_Course/slides.pdf": "pdf",
        "Flat_Course/extras/2026-06-21 11-15-25.mkv": 50,
        "Shorts/LLM/1 Intro.mp4": 100,
        "Shorts/LLM/mkv2mp4.sh": "sh",
        "Shorts/RAG/1 Eval.mp4": 100,
        "Markets/wrapped/1One.mp4": 100,
        "Markets/wrapped/2Two.mp4": 100,
        "Markets/wrapped/cover.png": "png",
        "Weird/1_Intro.\nmkv": 100,
        "Empty/notes.txt": "x",
        "cover_flat_course.webp": "img",
        "Flat_Course.webp": "img",
        ".hidden/1.mp4": 10,
    }

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "cursos")
        make_tree(self.root, self.FILES)

    def courses(self, layouts=None):
        return {c["id"]: c for c in scan.walk_root("main", self.root, layouts or {})["courses"]}

    def test_detected_courses(self):
        tree = scan.walk_root("main", self.root, {})
        self.assertEqual([c["id"] for c in tree["courses"]],
                         ["main:Flat_Course", "main:Markets", "main:Shorts/LLM", "main:Shorts/RAG", "main:Weird"])
        self.assertEqual(tree["folders"], {"main:Flat_Course": "course", "main:Markets": "course",
                                           "main:Shorts": "collection", "main:Weird": "course"})
        self.assertEqual(tree["images"], ["cover_flat_course.webp", "Flat_Course.webp"])

    def test_flat_course(self):
        c = self.courses()["main:Flat_Course"]
        self.assertEqual((c["title"], c["topic"], c["folderId"]), ("Flat Course", "", "main:Flat_Course"))
        self.assertEqual([l["relpath"] for l in c["lessons"]],
                         ["Flat_Course/1_a.mp4", "Flat_Course/2_b.mp4", "Flat_Course/10_c.mp4",
                          "Flat_Course/extras/2026-06-21 11-15-25.mkv"])
        self.assertEqual([l["group"] for l in c["lessons"]], ["", "", "", "extras"])
        self.assertEqual([l["title"] for l in c["lessons"]], ["a", "b", "c", "Part 4"])
        self.assertEqual(c["lessons"][0]["id"], "main:Flat_Course/1_a.mp4")
        self.assertEqual([d["name"] for d in c["docs"]], ["slides.pdf"])
        self.assertEqual(c["autoCover"], "Flat_Course.webp")

    def test_collection(self):
        c = self.courses()["main:Shorts/LLM"]
        self.assertEqual((c["title"], c["topic"], c["folderId"]), ("LLM", "Shorts", "main:Shorts"))
        self.assertEqual([l["title"] for l in c["lessons"]], ["Intro"])
        self.assertEqual([d["name"] for d in c["docs"]], ["mkv2mp4.sh"])

    def test_wrapper_folder_is_one_course_with_a_group(self):
        c = self.courses()["main:Markets"]
        self.assertEqual([l["group"] for l in c["lessons"]], ["wrapped", "wrapped"])
        self.assertEqual([l["title"] for l in c["lessons"]], ["One", "Two"])
        self.assertEqual(c["images"], ["Markets/wrapped/cover.png"])

    def test_newline_in_file_name(self):
        c = self.courses()["main:Weird"]
        self.assertEqual([l["title"] for l in c["lessons"]], ["Intro"])

    def test_layout_overrides(self):
        courses = self.courses({"main:Shorts": "course", "main:Markets": "collection"})
        self.assertEqual([l["group"] for l in courses["main:Shorts"]["lessons"]], ["LLM", "RAG"])
        self.assertEqual(courses["main:Markets/wrapped"]["topic"], "Markets")
        self.assertNotIn("main:Markets", courses)

    def test_hidden_and_empty_folders_are_skipped(self):
        ids = self.courses().keys()
        self.assertFalse(any("hidden" in i or "Empty" in i for i in ids))

    def test_indexes(self):
        cache = {"roots": {"main": scan.walk_root("main", self.root, {})}}
        self.assertIn("main:Shorts/RAG", scan.course_index(cache))
        root_id, course, lesson = scan.lesson_index(cache)["main:Flat_Course/2_b.mp4"]
        self.assertEqual((root_id, course["id"], lesson["title"]), ("main", "main:Flat_Course", "b"))


if __name__ == "__main__":
    unittest.main()
