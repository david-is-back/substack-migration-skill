import os
import struct
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


class TestPostAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        self.out = os.path.join(self.tmp.name, "out")
        self.result, self.code = sc.run(self.zip_path, out_dir=self.out)
        self.section = self.result["sections"]["posts"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        self.assertEqual(self.section["status"], "ran")
        self.assertEqual(self.section["total"], 4)        # 3 csv rows + 1 orphan html
        self.assertEqual(self.section["published"], 2)
        self.assertEqual(self.section["drafts"], 1)
        self.assertEqual(self.section["paywalled"], 1)
        self.assertEqual(self.section["missing_title"], 2)  # draft + orphan

    def test_dependency_totals(self):
        self.assertEqual(self.section["cdn_images_total"], 2)
        self.assertEqual(self.section["substack_links_total"], 1)
        self.assertEqual(self.section["embeds_total"], 1)

    def test_inventory_artifact(self):
        path = os.path.join(self.out, "posts-inventory.csv")
        self.assertIn(path, self.result["artifacts"])
        with open(path, encoding="utf-8", newline="") as fh:
            rows = {r["post_id"]: r for r in csv_mod.DictReader(fh)}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows["100001.abc"]["cdn_images"], "2")
        self.assertEqual(rows["100001.abc"]["substack_links"], "1")
        self.assertEqual(rows["100001.abc"]["embeds"], "1")
        self.assertEqual(rows["100002.def"]["paywalled"], "True")
        self.assertEqual(rows["100003.ghi"]["has_html"], "False")
        self.assertEqual(rows["999999"]["has_html"], "True")


import json as json_mod
import subprocess

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "substack_check.py")


class TestAssemblyAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_export_skips_posts(self):
        path = build_subscribers_only(os.path.join(self.tmp.name, "subs.zip"))
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertEqual(result["sections"]["subscribers"]["status"], "ran")
        self.assertEqual(result["sections"]["posts"]["status"], "skipped")

    def test_tables_markdown_present_and_exact(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        result, _ = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        tables = result["tables_markdown"]
        self.assertIn("| Importable (cleaned) | 5 |", tables["subscribers"])
        self.assertIn("| Total posts | 4 |", tables["posts"])

    def test_out_dir_collision_suffixes(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        default_out = os.path.join(self.tmp.name, "migration-check")
        os.makedirs(default_out)
        result, _ = sc.run(path)  # no out_dir -> default next to ZIP, which exists
        self.assertTrue(result["out_dir"].endswith("migration-check-2"))

    def test_cli_end_to_end(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        proc = subprocess.run(
            [sys.executable, SCRIPT, path,
             "--out", os.path.join(self.tmp.name, "cli-out")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json_mod.loads(proc.stdout)
        self.assertEqual(payload["sections"]["subscribers"]["importable"], 5)

    def test_cli_not_an_export_exit_2(self):
        path = build_not_an_export(os.path.join(self.tmp.name, "other.zip"))
        proc = subprocess.run(
            [sys.executable, SCRIPT, path], capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json_mod.loads(proc.stdout)
        self.assertEqual(payload["error"], "not_a_substack_export")


def _corrupt_first_deflated_member(zip_path):
    """Flip a run of bytes inside the first member's compressed data,
    strictly between its local-file-header data and the next signature
    (next local header or the central directory), so the end-of-central-
    directory record is left untouched."""
    with open(zip_path, "rb") as fh:
        data = bytearray(fh.read())
    sig = b"PK\x03\x04"
    start = data.find(sig)
    assert start != -1, "no local file header found"
    name_len, extra_len = struct.unpack("<HH", data[start + 26:start + 30])
    data_start = start + 30 + name_len + extra_len
    candidates = [
        pos for pos in (
            data.find(b"PK\x03\x04", data_start),
            data.find(b"PK\x01\x02", data_start),
        ) if pos != -1
    ]
    data_end = min(candidates) if candidates else len(data)
    assert data_end > data_start, "no compressed data to corrupt"
    flip_start = data_start + max(1, (data_end - data_start) // 4)
    flip_len = min(8, data_end - flip_start)
    assert flip_len > 0, "corruption window too small"
    for i in range(flip_start, flip_start + flip_len):
        data[i] ^= 0xFF
    with open(zip_path, "wb") as fh:
        fh.write(bytes(data))


class TestErrorPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrupt_zip_member_exits_audit_failed(self):
        path = build_full_export(os.path.join(self.tmp.name, "full.zip"))
        _corrupt_first_deflated_member(path)
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_AUDIT_FAILED)
        self.assertEqual(result["error"], "audit_failed")
        self.assertIn("detail", result)
        self.assertIn("expected", result)

    def test_non_utf8_email_list_exits_audit_failed(self):
        path = os.path.join(self.tmp.name, "badenc.zip")
        raw = (
            b"email,active_subscription,expiry,plan,email_disabled,"
            b"created_at,first_payment_at\n"
            b"caf\xe9@example.com,false,,,false,2024-01-01,\n"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("email_list.testpub.csv", raw)
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_AUDIT_FAILED)
        self.assertEqual(result["error"], "audit_failed")

    def test_unknown_plan_evidence_is_sanitized(self):
        path = os.path.join(self.tmp.name, "leak.zip")
        csv_text = (
            "email,active_subscription,expiry,plan,email_disabled,"
            "created_at,first_payment_at\n"
            "x@example.com,secret.person@private.example,,weird_plan,"
            "false,2024-01-01,\n"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("email_list.testpub.csv", csv_text)
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_OK)
        section = result["sections"]["subscribers"]
        self.assertEqual(sum(section["unknown_plan_values"].values()), 1)
        dumped = json_mod.dumps(result)
        self.assertNotIn("secret.person@private.example", dumped)

    def test_row_loss_detected_and_warned(self):
        path = os.path.join(self.tmp.name, "unbalanced.zip")
        csv_text = (
            "email,active_subscription,expiry,plan,email_disabled,"
            "created_at,first_payment_at\n"
            '"unterminated,false,,,false,2024-01-01,\n'
            "carol@example.com,false,,,false,2024-01-02,\n"
            "dave@example.com,false,,,false,2024-01-03,\n"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("email_list.testpub.csv", csv_text)
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_OK)
        section = result["sections"]["subscribers"]
        self.assertTrue(section["parse_warnings"])
        for warning in section["parse_warnings"]:
            self.assertIn(warning, result["warnings"])

    def test_bom_prefixed_email_list_parses_normally(self):
        path = os.path.join(self.tmp.name, "bom.zip")
        csv_text = (
            "﻿email,active_subscription,expiry,plan,email_disabled,"
            "created_at,first_payment_at\n"
            "alice@example.com,false,,,false,2024-01-01,\n"
            "bob@example.com,true,2026-01-01,monthly,false,2024-01-02,\n"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("email_list.testpub.csv", csv_text)
        result, code = sc.run(path, out_dir=os.path.join(self.tmp.name, "out"))
        self.assertEqual(code, sc.EXIT_OK)
        section = result["sections"]["subscribers"]
        self.assertEqual(section["total_rows"], 2)
        self.assertEqual(section["parse_warnings"], [])


if __name__ == "__main__":
    unittest.main()
