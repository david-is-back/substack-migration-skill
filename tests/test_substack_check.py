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


import csv as csv_mod


class TestSubscriberAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        self.out = os.path.join(self.tmp.name, "out")
        self.result, self.code = sc.run(self.zip_path, out_dir=self.out)
        self.section = self.result["sections"]["subscribers"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        self.assertEqual(self.section["status"], "ran")
        self.assertEqual(self.section["total_rows"], 9)
        self.assertEqual(self.section["importable"], 5)
        self.assertEqual(self.section["excluded_total"], 4)
        self.assertEqual(
            self.section["excluded_by_reason"],
            {"malformed_email": 2, "email_disabled": 1, "duplicate": 1},
        )

    def test_paid_classification_fail_loud(self):
        self.assertEqual(self.section["paid"], 3)   # bob, carol (paid dupe kept), erin
        self.assertEqual(self.section["free"], 1)   # alice
        self.assertEqual(sum(self.section["unknown_plan_values"].values()), 1)  # frank
        self.assertEqual(self.section["paid_missing_expiry"], 1)  # erin

    def test_samples_are_redacted(self):
        for sample in self.section["excluded_samples"]:
            self.assertNotRegex(sample["email"], r"^[a-z]{2,}[^*]*@")
            if "@" in sample["email"]:
                self.assertIn("***@", sample["email"])

    def test_cleaned_csv_artifact(self):
        path = os.path.join(self.out, "subscribers-cleaned.csv")
        self.assertIn(path, self.result["artifacts"])
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv_mod.DictReader(fh))
        self.assertEqual(len(rows), 5)
        by_email = {r["email"].lower(): r for r in rows}
        self.assertEqual(by_email["bob@example.com"]["is_paid"], "true")
        self.assertEqual(by_email["carol@example.com"]["is_paid"], "true")  # paid dupe won
        self.assertEqual(by_email["alice@example.com"]["is_paid"], "false")
        self.assertEqual(by_email["alice@example.com"]["source"], "substack")
        self.assertEqual(by_email["alice@example.com"]["name"], "")
        self.assertEqual(
            list(rows[0].keys()),
            ["email", "name", "status", "is_paid", "subscription_status",
             "subscription_expires_at", "created_at", "source", "tags"],
        )

    def test_excluded_csv_artifact(self):
        path = os.path.join(self.out, "subscribers-excluded.csv")
        self.assertIn(path, self.result["artifacts"])
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv_mod.DictReader(fh))
        self.assertEqual(len(rows), 4)
        reasons = sorted(r["reason"] for r in rows)
        self.assertEqual(
            reasons, ["duplicate", "email_disabled", "malformed_email", "malformed_email"]
        )
        # Excluded CSV must contain raw (unredacted) emails for human review
        emails = {r["email"] for r in rows}
        self.assertIn("dave@example.com", emails)       # disabled row, raw
        self.assertIn("carol@example.com", emails)      # losing duplicate, raw
        self.assertIn("not-an-email.example.com", emails)  # malformed, raw
        for r in rows:
            self.assertNotIn("***", r["email"])         # never redacted here
        self.assertEqual(rows[0]["file"], "email_list.testpub.csv")

    def test_cross_file_duplicate_merge(self):
        from make_fixture import build_split_lists
        path = build_split_lists(os.path.join(self.tmp.name, "split.zip"))
        result, _ = sc.run(path, out_dir=os.path.join(self.tmp.name, "out-split"))
        section = result["sections"]["subscribers"]
        self.assertEqual(section["total_rows"], 10)
        self.assertEqual(section["importable"], 5)
        self.assertEqual(section["excluded_by_reason"]["duplicate"], 2)
        self.assertEqual(section["paid"], 4)  # alice upgraded by the paid-segment file

    def test_original_zip_untouched(self):
        import hashlib
        with open(self.zip_path, "rb") as fh:
            before = hashlib.sha256(fh.read()).hexdigest()
        sc.run(self.zip_path, out_dir=os.path.join(self.tmp.name, "out2"))
        with open(self.zip_path, "rb") as fh:
            after = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
