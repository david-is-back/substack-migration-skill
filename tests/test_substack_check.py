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


import substack_check as sc


class TestDetectionAndIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_a_zip_exits_2(self):
        path = os.path.join(self.tmp.name, "fake.zip")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("this is not a zip")
        result, code = sc.run(path)
        self.assertEqual(code, sc.EXIT_NOT_AN_EXPORT)
        self.assertIn("error", result)
        self.assertIn("expected", result)

    def test_not_an_export_exits_2(self):
        path = build_not_an_export(os.path.join(self.tmp.name, "other.zip"))
        result, code = sc.run(path)
        self.assertEqual(code, sc.EXIT_NOT_AN_EXPORT)
        self.assertEqual(result["error"], "not_a_substack_export")

    def test_integrity_on_full_fixture(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_OK)
        integ = result["sections"]["export_integrity"]
        self.assertEqual(integ["status"], "ran")
        self.assertEqual(integ["email_list_files"], ["email_list.testpub.csv"])
        self.assertTrue(integ["posts_csv_present"])
        self.assertEqual(integ["post_html_count"], 3)
        self.assertEqual(integ["empty_files"], [])
        self.assertEqual(integ["missing_html"], ["100003"])
        self.assertEqual(integ["orphan_html"], ["999999"])


if __name__ == "__main__":
    unittest.main()
