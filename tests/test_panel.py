"""Panel.qml is QML, so it is not something unittest can import; these tests read it as
text and check it against ops.py, the one source of truth for which ops can rescan."""
import inspect
import os
import re
import unittest

from support import PLUGIN
from syllabus import ops

PANEL_QML = os.path.join(PLUGIN, "Panel.qml")


def ops_that_can_rescan():
    """Every op in ops.OPS whose handler can return "rescan" or "webIds" (folder.layout,
    web.remove and web.removeVideo today): these are the ones apply() can send to a real
    scan, so they need scanEngine's budget and not the fast one."""
    names = []
    for name, fn in ops.OPS.items():
        source = inspect.getsource(fn)
        if '"rescan"' in source or '"webIds"' in source:
            names.append(name)
    return sorted(names)


def panel_source():
    with open(PANEL_QML, encoding="utf-8") as f:
        return f.read()


class ApplyRouting(unittest.TestCase):
    def test_panel_declares_exactly_the_ops_that_can_rescan(self):
        text = panel_source()
        match = re.search(r'property var rescanOps:\s*\[([^\]]*)\]', text)
        self.assertIsNotNone(match, "Panel.qml must declare a rescanOps list")
        declared = sorted(re.findall(r'"([\w.]+)"', match.group(1)))
        self.assertEqual(declared, ops_that_can_rescan())

    def test_apply_routes_rescan_capable_ops_through_the_scan_engine(self):
        text = panel_source()
        body = re.search(r"function apply\(op[^)]*\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(body, "apply() is not where this test expects it")
        for needed in ("rescanOps", "scanEngine", "engine"):
            self.assertIn(needed, body.group(1))
        self.assertRegex(body.group(1), r'\.call\(\["apply"\]')

    def test_the_two_engines_keep_their_own_timeouts(self):
        text = panel_source()
        self.assertRegex(text, r'id: engine\b[\s\S]{0,200}?timeoutMs:\s*20000')
        self.assertRegex(text, r'id: scanEngine\b[\s\S]{0,200}?timeoutMs:\s*600000')


if __name__ == "__main__":
    unittest.main()
