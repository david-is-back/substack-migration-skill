import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

from make_fixture import build_full_export, build_subscribers_only, build_not_an_export


class TestFixtureBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_export_contains_expected_entries(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        self.assertIn("email_list.testpub.csv", names)
        self.assertIn("posts.csv", names)
        self.assertIn("posts/100001.abc.html", names)
        self.assertIn("posts/100002.def.html", names)
        self.assertIn("posts/999999.zzz.html", names)  # orphan: HTML with no posts.csv row

    def test_subscribers_only_export(self):
        path = build_subscribers_only(os.path.join(self.tmp.name, "subs.zip"))
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        self.assertEqual(names, {"email_list.testpub.csv"})

    def test_not_an_export(self):
        path = build_not_an_export(os.path.join(self.tmp.name, "other.zip"))
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        self.assertEqual(names, {"random.txt"})


if __name__ == "__main__":
    unittest.main()
