# `substack-migration-check` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public, offline Claude Code skill that audits a Substack export ZIP against the Substack Migration Checklist and produces a report, a cleaned import-ready subscriber CSV, and a per-post dependency inventory.

**Architecture:** The repo root is the installable skill. A single stdlib-only Python script (`scripts/substack_check.py`) does all data processing in one streaming pass and emits a JSON summary (with pre-rendered markdown tables and redacted samples) to stdout; Claude (driven by `SKILL.md`) only ever reads that JSON and authors the narrative `report.md`. Deterministic artifacts (cleaned CSV, exclusions, post inventory) are written by the script, never by the model.

**Tech Stack:** Python 3.9+ standard library only (`zipfile`, `csv`, `io`, `json`, `re`, `argparse`, `os`, `sys`); `unittest` for tests; markdown for skill/docs.

**Spec:** `docs/superpowers/specs/2026-07-09-substack-migration-check-skill-design.md` — read it before starting any task.

## Global Constraints

- Python 3.9+, **standard library only** — no third-party dependencies anywhere (script or tests).
- All deliverable content (code, comments, SKILL.md, README, artifacts) in **English**.
- **100% offline**: the script must make no network calls.
- The input ZIP is **never modified** — tests assert its bytes are unchanged.
- Emails in JSON stdout are **redacted** (`a***@domain.com`); real emails may appear only in local CSV artifacts.
- All artifacts are UTF-8 with a header row; CSVs written with `newline=""`.
- Exit codes: `0` = at least one check section ran; `2` = not recognizable as a Substack export / unreadable ZIP.
- Cleaned CSV header (exact, from the checklist template): `email,name,status,is_paid,subscription_status,subscription_expires_at,created_at,source,tags`.
- Paid detection is **fail-loud**: unrecognized `active_subscription`/`plan` values go to an `unknown_plan_values` bucket, never silently classified as free.
- Run tests from the repo root with: `python -m unittest discover -s tests -v`

---

### Task 1: Repo scaffolding + test fixture builder

**Files:**
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `tests/__init__.py`
- Create: `tests/make_fixture.py`
- Test: `tests/test_substack_check.py` (started here, grows in later tasks)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `make_fixture.build_full_export(path: str) -> str`, `make_fixture.build_subscribers_only(path: str) -> str`, `make_fixture.build_not_an_export(path: str) -> str` — each writes a ZIP at `path` and returns `path`. Planted data below is the oracle every later test asserts against; do not alter it.

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty file) and `tests/test_substack_check.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'make_fixture'`

- [ ] **Step 3: Write the fixture builder**

Create `tests/make_fixture.py`:

```python
"""Builds anonymized Substack-export fixture ZIPs for tests (stdlib only).

The planted rows are the oracle for the whole test suite:
- 9 subscriber rows -> 5 importable (alice free, bob paid, carol paid via dupe
  resolution, erin paid-missing-expiry, frank unknown-plan), 2 malformed,
  1 disabled, 1 duplicate.
- 3 posts.csv rows + 3 HTML files (one orphan, one CSV row without HTML).
"""
import zipfile

EMAIL_LIST_CSV = """\
email,active_subscription,expiry,plan,email_disabled,created_at,first_payment_at
alice@example.com,false,,,false,2024-01-15T10:00:00.000Z,
bob@example.com,true,2026-12-01T00:00:00.000Z,monthly,false,2024-02-01T10:00:00.000Z,2024-02-01T10:00:00.000Z
carol@example.com,false,,,false,2024-03-01T10:00:00.000Z,
CAROL@example.com,true,2026-06-01T00:00:00.000Z,annually,false,2024-03-02T10:00:00.000Z,2024-03-02T10:00:00.000Z
not-an-email.example.com,false,,,false,2024-04-01T10:00:00.000Z,
,false,,,false,2024-05-01T10:00:00.000Z,
dave@example.com,false,,,true,2024-06-01T10:00:00.000Z,
erin@example.com,true,,monthly,false,2024-07-01T10:00:00.000Z,2024-07-01T10:00:00.000Z
frank@example.com,mystery_value,,vip_tier,false,2024-08-01T10:00:00.000Z,
"""

POSTS_CSV = """\
post_id,post_date,is_published,email_sent_at,inbox_sent_at,type,audience,title,subtitle,podcast_url
100001.abc,2024-01-01,true,2024-01-01,,newsletter,everyone,Hello World,First post,
100002.def,,false,,,newsletter,only_paid,,,
100003.ghi,2024-02-01,true,,,newsletter,everyone,Missing HTML,,
"""

POST_1_HTML = (
    '<p>Hi</p>'
    '<img src="https://substackcdn.com/image/fetch/one.png">'
    '<img src="https://substack-post-media.s3.amazonaws.com/two.png">'
    '<a href="https://mypub.substack.com/p/old-post">old</a>'
    '<div class="tweet-embed">embedded tweet</div>'
)
POST_2_HTML = "<p>draft body</p>"
ORPHAN_HTML = "<p>orphan body</p>"


def build_full_export(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("email_list.testpub.csv", EMAIL_LIST_CSV)
        zf.writestr("posts.csv", POSTS_CSV)
        zf.writestr("posts/100001.abc.html", POST_1_HTML)
        zf.writestr("posts/100002.def.html", POST_2_HTML)
        zf.writestr("posts/999999.zzz.html", ORPHAN_HTML)
    return path


def build_subscribers_only(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("email_list.testpub.csv", EMAIL_LIST_CSV)
    return path


def build_not_an_export(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("random.txt", "nothing to see here")
    return path


# Second subscriber file for cross-file merge tests: alice appears again, paid.
EMAIL_LIST_PAID_CSV = """\
email,active_subscription,expiry,plan,email_disabled,created_at,first_payment_at
alice@example.com,true,2027-01-01T00:00:00.000Z,monthly,false,2024-01-15T10:00:00.000Z,2025-01-01T00:00:00.000Z
"""


def build_split_lists(path):
    """Full subscriber list plus a second, paid-segment email_list file."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("email_list.testpub.csv", EMAIL_LIST_CSV)
        zf.writestr("email_list.paid.testpub.csv", EMAIL_LIST_PAID_CSV)
    return path
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
migration-check*/
```

Create `LICENSE` with the standard MIT license text, copyright line: `Copyright (c) 2026 David Orellana`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add .gitignore LICENSE tests/
git commit -m "feat: repo scaffolding and test fixture builder"
```

---

### Task 2: Script skeleton — component detection, export integrity, exit codes

**Files:**
- Create: `scripts/substack_check.py`
- Modify: `tests/test_substack_check.py` (append test class)

**Interfaces:**
- Consumes: fixture builders from Task 1.
- Produces (used by every later task):
  - `substack_check.run(zip_path: str, out_dir: str | None = None) -> tuple[dict, int]` — result JSON dict + exit code.
  - `substack_check.detect_components(zf: zipfile.ZipFile) -> dict` with keys `email_lists: list[str]`, `posts_csv: bool`, `post_html: list[str]`.
  - `substack_check.read_text(zf, name) -> str` (UTF-8, BOM-tolerant).
  - `substack_check.main(argv) -> int`, constants `EXIT_OK = 0`, `EXIT_NOT_AN_EXPORT = 2`.
  - Result dict shape: `{"zip": str, "sections": {...}, "artifacts": [], "warnings": []}`; section `export_integrity` with keys `status, email_list_files, posts_csv_present, post_html_count, empty_files, missing_html, orphan_html`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_substack_check.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'substack_check'`

- [ ] **Step 3: Write the script skeleton**

Create `scripts/substack_check.py`:

```python
#!/usr/bin/env python3
"""substack_check.py - offline audit of a Substack export ZIP.

Standard library only (Python 3.9+). Emits a JSON summary to stdout and
writes deterministic artifacts to an output directory. Never modifies the
input ZIP and never touches the network.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import zipfile

EXIT_OK = 0
EXIT_NOT_AN_EXPORT = 2

EMAIL_LIST_RE = re.compile(r"^email_list[\w.-]*\.csv$")
POST_HTML_RE = re.compile(r"^posts/(?P<post_id>[^.]+)\..*html$")

EXPECTED_MSG = (
    "A Substack export ZIP contains email_list*.csv, posts.csv and posts/*.html. "
    "Export guide: https://github.com/david-is-back/substack-migration-checklist/"
    "blob/main/guides/export-from-substack.md"
)


def detect_components(zf):
    names = zf.namelist()
    return {
        "email_lists": sorted(n for n in names if EMAIL_LIST_RE.match(n)),
        "posts_csv": "posts.csv" in names,
        "post_html": sorted(n for n in names if POST_HTML_RE.match(n)),
    }


def read_text(zf, name):
    with zf.open(name) as fh:
        return io.TextIOWrapper(fh, encoding="utf-8-sig", newline="").read()


def check_integrity(zf, components):
    tracked = list(components["email_lists"]) + components["post_html"]
    if components["posts_csv"]:
        tracked.append("posts.csv")
    empty = sorted(n for n in tracked if zf.getinfo(n).file_size == 0)

    result = {
        "status": "ran",
        "email_list_files": components["email_lists"],
        "posts_csv_present": components["posts_csv"],
        "post_html_count": len(components["post_html"]),
        "empty_files": empty,
        "missing_html": [],
        "orphan_html": [],
    }
    if components["posts_csv"]:
        ids_csv = set()
        for row in csv.DictReader(io.StringIO(read_text(zf, "posts.csv"))):
            pid = (row.get("post_id") or "").split(".")[0].strip()
            if pid:
                ids_csv.add(pid)
        ids_html = {
            POST_HTML_RE.match(n).group("post_id") for n in components["post_html"]
        }
        result["missing_html"] = sorted(ids_csv - ids_html)
        result["orphan_html"] = sorted(ids_html - ids_csv)
    return result


def run(zip_path, out_dir=None):
    if not zipfile.is_zipfile(zip_path):
        return (
            {"error": "not_a_zip_or_unreadable", "expected": EXPECTED_MSG,
             "zip": os.path.abspath(zip_path)},
            EXIT_NOT_AN_EXPORT,
        )
    with zipfile.ZipFile(zip_path) as zf:
        components = detect_components(zf)
        if not (components["email_lists"] or components["posts_csv"]
                or components["post_html"]):
            return (
                {"error": "not_a_substack_export", "expected": EXPECTED_MSG,
                 "zip": os.path.abspath(zip_path)},
                EXIT_NOT_AN_EXPORT,
            )
        result = {
            "zip": os.path.abspath(zip_path),
            "sections": {},
            "artifacts": [],
            "warnings": [],
        }
        result["sections"]["export_integrity"] = check_integrity(zf, components)
    return result, EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline audit of a Substack export ZIP."
    )
    parser.add_argument("zip_path", help="Path to the Substack export ZIP")
    parser.add_argument("--out", default=None,
                        help="Output directory for artifacts "
                             "(default: migration-check/ next to the ZIP)")
    args = parser.parse_args(argv)
    result, code = run(args.zip_path, out_dir=args.out)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
```

Note: `run()` accepts `out_dir` from day one (unused until Task 3) so the signature never changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 6 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/substack_check.py tests/test_substack_check.py
git commit -m "feat: export detection, integrity check, exit codes"
```

---

### Task 3: Subscriber audit + cleaned/excluded CSV artifacts

**Files:**
- Modify: `scripts/substack_check.py`
- Modify: `tests/test_substack_check.py` (append test class)

**Interfaces:**
- Consumes: `read_text`, `detect_components`, `run` from Task 2.
- Produces:
  - `audit_subscribers(zf, components) -> tuple[dict, list[dict], list[dict]]` — (section dict, cleaned rows, excluded rows).
  - `classify_paid(row: dict) -> tuple[str, str]` — (`"paid"|"free"|"unknown"`, evidence string).
  - `redact_email(email: str) -> str`.
  - `pick_out_dir(zip_path, requested) -> str` and `write_csv(path, header, rows)`.
  - Constants: `CLEANED_HEADER`, `EXCLUDED_HEADER = ["email", "reason", "file"]`, `TRUEISH`, `FALSISH`, `PAID_PLANS`, `FREE_PLANS`, `EMAIL_RE`, `DATE_RE`.
  - `run()` now writes `subscribers-cleaned.csv` and `subscribers-excluded.csv` into the out dir and lists them in `result["artifacts"]`; section key `subscribers`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_substack_check.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: ERROR/FAIL — `KeyError: 'subscribers'` (section not produced yet)

- [ ] **Step 3: Implement the subscriber audit**

Add to `scripts/substack_check.py` (below the existing constants):

```python
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
TRUEISH = {"true", "t", "yes", "1", "active"}
FALSISH = {"false", "f", "no", "0", "", "none", "inactive"}
PAID_PLANS = {"monthly", "month", "annually", "annual", "yearly", "year", "founding"}
FREE_PLANS = {"", "free", "none", "null"}

CLEANED_HEADER = [
    "email", "name", "status", "is_paid", "subscription_status",
    "subscription_expires_at", "created_at", "source", "tags",
]
EXCLUDED_HEADER = ["email", "reason", "file"]

UNSUBSCRIBE_NOTE = (
    "Substack's export has no unsubscribe column (only email_disabled). "
    "Verify your Substack export filter excluded unsubscribed contacts "
    "before importing anywhere."
)


def redact_email(email):
    if "@" not in email:
        return "<invalid>"
    local, _, domain = email.partition("@")
    return (local[:1] or "?") + "***@" + domain


def classify_paid(row):
    """Fail-loud paid detection: unrecognized values are 'unknown', never free."""
    sub = (row.get("active_subscription") or "").strip().lower()
    plan = (row.get("plan") or "").strip().lower()
    if sub in TRUEISH or plan in PAID_PLANS:
        return "paid", plan or sub
    if sub in FALSISH and plan in FREE_PLANS:
        return "free", ""
    return "unknown", "active_subscription=%r plan=%r" % (sub, plan)


def audit_subscribers(zf, components):
    kept = {}       # lower-cased email -> record
    excluded = []   # {"email": redacted, "raw_email": str, "reason": str, "file": str}
    unknown_values = {}
    total = 0

    for name in components["email_lists"]:
        for row in csv.DictReader(io.StringIO(read_text(zf, name))):
            total += 1
            email = (row.get("email") or "").strip()
            if not EMAIL_RE.match(email):
                excluded.append({"email": redact_email(email), "raw_email": email,
                                 "reason": "malformed_email", "file": name})
                continue
            if (row.get("email_disabled") or "").strip().lower() in TRUEISH:
                excluded.append({"email": redact_email(email), "raw_email": email,
                                 "reason": "email_disabled", "file": name})
                continue
            paid_class, evidence = classify_paid(row)
            if paid_class == "unknown":
                unknown_values[evidence] = unknown_values.get(evidence, 0) + 1
            record = {
                "email": email,
                "name": "",
                "status": "active",
                "is_paid": "true" if paid_class == "paid" else "false",
                "subscription_status": (row.get("active_subscription") or "").strip(),
                "subscription_expires_at": (row.get("expiry") or "").strip(),
                "created_at": (row.get("created_at") or "").strip(),
                "source": "substack",
                "tags": "",
                "_paid_class": paid_class,
                "_file": name,
            }
            key = email.lower()
            if key in kept:
                old = kept[key]
                if paid_class == "paid" and old["_paid_class"] != "paid":
                    excluded.append({"email": redact_email(old["email"]),
                                     "raw_email": old["email"],
                                     "reason": "duplicate", "file": old["_file"]})
                    kept[key] = record
                else:
                    excluded.append({"email": redact_email(email), "raw_email": email,
                                     "reason": "duplicate", "file": name})
            else:
                kept[key] = record

    reasons = {}
    for entry in excluded:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1

    section = {
        "status": "ran",
        "total_rows": total,
        "importable": len(kept),
        "excluded_total": len(excluded),
        "excluded_by_reason": reasons,
        "paid": sum(1 for r in kept.values() if r["_paid_class"] == "paid"),
        "free": sum(1 for r in kept.values() if r["_paid_class"] == "free"),
        "unknown_plan_values": unknown_values,
        "paid_missing_expiry": sum(
            1 for r in kept.values()
            if r["_paid_class"] == "paid" and not r["subscription_expires_at"]
        ),
        "created_at_unparseable": sum(
            1 for r in kept.values() if not DATE_RE.match(r["created_at"])
        ),
        "excluded_samples": [
            {"email": e["email"], "reason": e["reason"]} for e in excluded[:5]
        ],
        "unsubscribe_note": UNSUBSCRIBE_NOTE,
    }
    cleaned = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in sorted(kept.values(), key=lambda r: r["email"].lower())
    ]
    return section, cleaned, excluded


def pick_out_dir(zip_path, requested):
    base = requested or os.path.join(
        os.path.dirname(os.path.abspath(zip_path)), "migration-check"
    )
    out, n = base, 2
    while os.path.exists(out):
        out = "%s-%d" % (base, n)
        n += 1
    os.makedirs(out)
    return out


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
```

Then modify `run()`: after the `export_integrity` line and still inside the `with zipfile.ZipFile(...)` block, add:

```python
        out = pick_out_dir(zip_path, out_dir)
        result["out_dir"] = out

        if components["email_lists"]:
            section, cleaned, excluded = audit_subscribers(zf, components)
            result["sections"]["subscribers"] = section
            cleaned_path = os.path.join(out, "subscribers-cleaned.csv")
            write_csv(cleaned_path, CLEANED_HEADER, cleaned)
            result["artifacts"].append(cleaned_path)
            excluded_path = os.path.join(out, "subscribers-excluded.csv")
            write_csv(
                excluded_path, EXCLUDED_HEADER,
                [{"email": e["raw_email"], "reason": e["reason"], "file": e["file"]}
                 for e in excluded],
            )
            result["artifacts"].append(excluded_path)
            if section["paid"] > 0:
                result["warnings"].append(
                    "Paid subscribers detected. The export does not include billing "
                    "data - review your Stripe account and the paid-migration guide: "
                    "https://github.com/david-is-back/substack-migration-checklist/"
                    "blob/main/guides/migrate-paid-subscribers.md"
                )
        else:
            result["sections"]["subscribers"] = {
                "status": "skipped", "reason": "no email_list*.csv in export"
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 14 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/substack_check.py tests/test_substack_check.py
git commit -m "feat: subscriber audit with cleaned/excluded CSV artifacts"
```

---

### Task 4: Post audit + posts-inventory.csv

**Files:**
- Modify: `scripts/substack_check.py`
- Modify: `tests/test_substack_check.py` (append test class)

**Interfaces:**
- Consumes: `read_text`, `POST_HTML_RE`, `TRUEISH`, `write_csv`, `run` wiring pattern from Tasks 2-3.
- Produces:
  - `audit_posts(zf, components) -> tuple[dict, list[dict]]` — (section dict, per-post rows).
  - `INVENTORY_HEADER = ["post_id", "title", "is_published", "paywalled", "cdn_images", "substack_links", "embeds", "has_html"]`.
  - Regexes: `CDN_IMAGE_RE`, `SUBSTACK_LINK_RE`, `EMBED_RE`.
  - `run()` writes `posts-inventory.csv`; section key `posts`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_substack_check.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: ERROR/FAIL — `KeyError: 'posts'`

- [ ] **Step 3: Implement the post audit**

Add to `scripts/substack_check.py`:

```python
CDN_IMAGE_RE = re.compile(
    r"https?://[^\"'\s>]*(?:substackcdn\.com|substack-post-media)[^\"'\s>]*"
)
SUBSTACK_LINK_RE = re.compile(r"href=[\"']https?://[^\"']*substack\.com[^\"']*[\"']")
EMBED_RE = re.compile(r"class=[\"'][^\"']*(?:embed|tweet|youtube)[^\"']*[\"']")

INVENTORY_HEADER = [
    "post_id", "title", "is_published", "paywalled",
    "cdn_images", "substack_links", "embeds", "has_html",
]


def audit_posts(zf, components):
    posts = {}
    if components["posts_csv"]:
        for row in csv.DictReader(io.StringIO(read_text(zf, "posts.csv"))):
            pid = (row.get("post_id") or "").split(".")[0].strip()
            if not pid:
                continue
            posts[pid] = {
                "post_id": (row.get("post_id") or "").strip(),
                "title": (row.get("title") or "").strip(),
                "is_published": (row.get("is_published") or "").strip().lower()
                                in TRUEISH,
                "paywalled": (row.get("audience") or "").strip().lower()
                             == "only_paid",
                "cdn_images": 0, "substack_links": 0, "embeds": 0,
                "has_html": False,
            }
    for name in components["post_html"]:
        pid = POST_HTML_RE.match(name).group("post_id")
        html = read_text(zf, name)
        record = posts.setdefault(pid, {
            "post_id": pid, "title": "", "is_published": None, "paywalled": None,
            "cdn_images": 0, "substack_links": 0, "embeds": 0, "has_html": False,
        })
        record["has_html"] = True
        record["cdn_images"] = len(CDN_IMAGE_RE.findall(html))
        record["substack_links"] = len(SUBSTACK_LINK_RE.findall(html))
        record["embeds"] = len(EMBED_RE.findall(html))

    inventory = sorted(posts.values(), key=lambda p: p["post_id"])
    section = {
        "status": "ran",
        "total": len(inventory),
        "published": sum(1 for p in inventory if p["is_published"] is True),
        "drafts": sum(1 for p in inventory if p["is_published"] is False),
        "paywalled": sum(1 for p in inventory if p["paywalled"]),
        "missing_title": sum(1 for p in inventory if not p["title"]),
        "cdn_images_total": sum(p["cdn_images"] for p in inventory),
        "substack_links_total": sum(p["substack_links"] for p in inventory),
        "embeds_total": sum(p["embeds"] for p in inventory),
    }
    return section, inventory
```

Wire into `run()`, after the subscribers block (inside the `with` block):

```python
        if components["posts_csv"] or components["post_html"]:
            post_section, inventory = audit_posts(zf, components)
            result["sections"]["posts"] = post_section
            inventory_path = os.path.join(out, "posts-inventory.csv")
            write_csv(inventory_path, INVENTORY_HEADER, inventory)
            result["artifacts"].append(inventory_path)
        else:
            result["sections"]["posts"] = {
                "status": "skipped", "reason": "no posts.csv or posts/*.html in export"
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 17 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/substack_check.py tests/test_substack_check.py
git commit -m "feat: post audit with dependency inventory artifact"
```

---

### Task 5: Markdown tables, partial exports, end-to-end CLI test

**Files:**
- Modify: `scripts/substack_check.py`
- Modify: `tests/test_substack_check.py` (append test class)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `render_tables(result: dict) -> dict[str, str]` — pre-rendered markdown tables keyed `subscribers`, `posts`; stored in `result["tables_markdown"]`. Claude never transcribes numbers by hand.
  - Verified behavior: subscribers-only export runs with `posts` section `skipped` and exit 0; output-dir collision auto-suffixes `-2`; CLI prints JSON to stdout and returns the right exit codes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_substack_check.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL — `KeyError: 'tables_markdown'` (and the collision test may fail before that)

- [ ] **Step 3: Implement tables and final assembly**

Add to `scripts/substack_check.py`:

```python
def render_tables(result):
    tables = {}
    subs = result["sections"].get("subscribers")
    if subs and subs.get("status") == "ran":
        lines = [
            "| Metric | Count |", "|---|---|",
            "| Total rows in export | %d |" % subs["total_rows"],
            "| Importable (cleaned) | %d |" % subs["importable"],
            "| Excluded | %d |" % subs["excluded_total"],
        ]
        for reason, count in sorted(subs["excluded_by_reason"].items()):
            lines.append("| — excluded: %s | %d |" % (reason, count))
        lines += [
            "| Paid | %d |" % subs["paid"],
            "| Free | %d |" % subs["free"],
            "| Unknown plan values | %d |" % sum(subs["unknown_plan_values"].values()),
            "| Paid missing expiry | %d |" % subs["paid_missing_expiry"],
            "| created_at unparseable | %d |" % subs["created_at_unparseable"],
        ]
        tables["subscribers"] = "\n".join(lines)
    posts = result["sections"].get("posts")
    if posts and posts.get("status") == "ran":
        tables["posts"] = "\n".join([
            "| Metric | Count |", "|---|---|",
            "| Total posts | %d |" % posts["total"],
            "| Published | %d |" % posts["published"],
            "| Drafts | %d |" % posts["drafts"],
            "| Paywalled (only_paid) | %d |" % posts["paywalled"],
            "| Missing title | %d |" % posts["missing_title"],
            "| Images on Substack CDN | %d |" % posts["cdn_images_total"],
            "| Links to substack.com | %d |" % posts["substack_links_total"],
            "| Embeds | %d |" % posts["embeds_total"],
        ])
    return tables
```

In `run()`, add as the last line before `return result, EXIT_OK` (outside the `with` block is fine):

```python
    result["tables_markdown"] = render_tables(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 22 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/substack_check.py tests/test_substack_check.py
git commit -m "feat: markdown tables, partial-export skips, CLI end-to-end tests"
```

---

### Task 6: `references/checklist-map.md`

**Files:**
- Create: `references/checklist-map.md`

**Interfaces:**
- Consumes: the checklist repo (read-only, at authoring time — the shipped file is static).
- Produces: the reference document `SKILL.md` tells Claude to read when composing `report.md`. Contains the pinned upstream commit hash.

- [ ] **Step 1: Pin the upstream checklist commit**

Run: `git ls-remote https://github.com/david-is-back/substack-migration-checklist refs/heads/main`
Expected: one line, `<40-hex-hash>\trefs/heads/main`. Record the hash for Step 2.

- [ ] **Step 2: Write the reference document**

Create `references/checklist-map.md`. Use exactly this structure, replacing `<HASH>` with the value from Step 1:

```markdown
# Checklist map

Generated against [substack-migration-checklist](https://github.com/david-is-back/substack-migration-checklist)
commit `<HASH>`. If upstream has moved, links and the CSV template header may have drifted — verify before trusting them.

## Automated checks → checklist sections

| JSON section | Checklist section | What is covered |
|---|---|---|
| `export_integrity` | [§2 Export your Substack data](https://github.com/david-is-back/substack-migration-checklist/blob/main/checklist.md#2-export-your-substack-data) | Files present and non-empty; posts.csv reconciled against posts/*.html |
| `subscribers` | [§3 Review your subscriber list](https://github.com/david-is-back/substack-migration-checklist/blob/main/checklist.md#3-review-your-subscriber-list) | Malformed emails, duplicates (paid row kept), disabled/bounced excluded, fail-loud paid detection, expiry and created_at validation |
| `posts` | [§5 Migrate your content archive](https://github.com/david-is-back/substack-migration-checklist/blob/main/checklist.md#5-migrate-your-content-archive) | Published/draft/paywalled inventory; Substack CDN images, substack.com links, and embeds per post |

## Known limitations (state these in every report)

- The export has no unsubscribe signal (only `email_disabled`). The user must verify
  their Substack export filter excluded unsubscribed contacts.
- Billing data does not travel in the export. Paid migration requires the
  [paid subscribers guide](https://github.com/david-is-back/substack-migration-checklist/blob/main/guides/migrate-paid-subscribers.md).

## Still manual — condense into the report's final section

- **§1 Before you migrate** — snapshot metrics (subscriber count, open rate) as your baseline; do not cancel Substack yet.
- **§4 Prepare the new platform** — account, sender domain (SPF/DKIM), signup forms, import the cleaned CSV.
- **§6 Paid subscribers** — record renewal dates, plan the switchover so nobody is double billed or loses access; [guide](https://github.com/david-is-back/substack-migration-checklist/blob/main/guides/migrate-paid-subscribers.md).
- **§7 Custom domain** — add domain to the new platform first, lower TTL, verify SSL before switching; [guide](https://github.com/david-is-back/substack-migration-checklist/blob/main/guides/move-your-custom-domain.md).
- **§8 Test before launch** — send test emails, check rendering and spam placement; [deliverability guide](https://github.com/david-is-back/substack-migration-checklist/blob/main/guides/deliverability-checklist.md).
- **§9 Announce** — separate announcements for free and paid subscribers ([templates](https://github.com/david-is-back/substack-migration-checklist/tree/main/templates)).
- **§10 Post-migration audit** — compare counts, monitor rates, 7-day and 30-day reviews; [template](https://github.com/david-is-back/substack-migration-checklist/blob/main/templates/post-migration-audit.md).
```

- [ ] **Step 3: Verify the links**

Spot-check that each anchor (`#2-export-your-substack-data`, etc.) matches the headings in the pinned checklist.md (headings were verified 2026-07-09: "2. Export your Substack data", "3. Review your subscriber list", "5. Migrate your content archive"). Fix any drift.

- [ ] **Step 4: Commit**

```bash
git add references/checklist-map.md
git commit -m "docs: checklist map with pinned upstream commit"
```

---

### Task 7: `SKILL.md` + `README.md`

**Files:**
- Create: `SKILL.md`
- Create: `README.md`

**Interfaces:**
- Consumes: the script CLI (`python scripts/substack_check.py <zip> [--out <dir>]`, exit codes 0/2, JSON on stdout with `tables_markdown`, `sections`, `artifacts`, `warnings`) and `references/checklist-map.md`.
- Produces: the user-facing skill and repo documentation.

- [ ] **Step 1: Write SKILL.md**

Create `SKILL.md` with exactly this content:

````markdown
---
name: substack-migration-check
description: Audit a Substack export ZIP before migrating to another newsletter platform. Use when the user wants to migrate from or leave Substack, or asks to check, validate, audit, or clean a Substack export (subscriber list, posts). Produces a report, a cleaned import-ready subscriber CSV, and a post dependency inventory — fully offline.
---

# Substack Migration Check

Audits a Substack export ZIP against the
[Substack Migration Checklist](https://github.com/david-is-back/substack-migration-checklist):
export integrity, subscriber list cleanup, and post archive dependencies.

## Privacy rule (non-negotiable)

Never read the raw CSV or HTML files from the export into context — subscriber
emails must not reach the model. All data processing happens in
`scripts/substack_check.py`; you only read its JSON output (emails there are
redacted). If Python is unavailable, STOP and tell the user to install
Python 3.9+ — do not analyze the export inline.

## Flow

1. **Locate the ZIP.** If the user did not give a path, ask for it. Do not
   unzip it; the script reads it in place.
2. **Check Python**: run `python --version` (or `python3`). Needs 3.9+.
3. **Run the audit:**
   `python <skill-dir>/scripts/substack_check.py <zip-path>`
   Optional: `--out <dir>` (default: `migration-check/` next to the ZIP,
   auto-suffixed if it exists).
4. **Interpret the JSON** (stdout):
   - Exit 2 → not a Substack export. Relay `expected` to the user.
   - Exit 0 → read `sections` (each `ran` or `skipped`), `warnings`,
     `artifacts`, `tables_markdown`.
5. **Write `report.md`** in the output directory (`out_dir` in the JSON):
   - Executive summary (2-4 sentences: is this export ready to migrate?).
   - One section per check: embed the matching `tables_markdown` table
     **verbatim — never retype numbers** — plus a short interpretation.
   - Every warning from `warnings`, prominently.
   - The known limitations and the "Still manual" section condensed from
     `references/checklist-map.md`, with its links.
6. **Summarize for the user:** key counts, artifacts produced (cleaned CSV,
   exclusions, post inventory, report), and the top manual next steps.

## Notes

- `unknown_plan_values` non-empty means the paid/free split is incomplete.
  Those rows are included in the cleaned CSV with `is_paid=false`, but the
  user must manually verify their paid status before importing — a paid
  subscriber imported as free loses access.
- The original ZIP is never modified.
````

- [ ] **Step 2: Write README.md**

Create `README.md`:

```markdown
# substack-migration-check

A [Claude Code](https://claude.com/claude-code) skill that audits a Substack
export ZIP before you migrate to another newsletter platform. Companion to the
[Substack Migration Checklist](https://github.com/david-is-back/substack-migration-checklist).

## What it does

Point it at the ZIP you downloaded from Substack and it produces, fully offline:

- **`report.md`** — export integrity, subscriber list audit, and post archive
  dependencies, with exact counts, plus the manual steps that remain.
- **`subscribers-cleaned.csv`** — import-ready list (malformed and duplicate
  emails removed, disabled addresses excluded, paid status flagged), matching
  the checklist's platform-agnostic template.
- **`subscribers-excluded.csv`** — every excluded contact and why, for review.
- **`posts-inventory.csv`** — per post: Substack-hosted images, substack.com
  links, embeds, paywall status — everything that needs attention when moving
  your archive.

Your original export is never modified.

## Privacy

Everything runs locally. Subscriber data is processed only by a
dependency-free Python script on your machine; the AI model only sees
aggregate counts and redacted samples (`a***@example.com`). No network access.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.9+ (standard library only — nothing to `pip install`)

## Install

```bash
git clone https://github.com/david-is-back/substack-migration-skill ~/.claude/skills/substack-migration-check
```

The target directory name must be `substack-migration-check` (the skill name).

## Use

In Claude Code:

> Check my Substack export at ~/Downloads/my-export.zip — I'm migrating.

Artifacts land in `migration-check/` next to your ZIP.

## Development

```bash
python -m unittest discover -s tests -v
```

MIT licensed. Issues and PRs welcome.
```

- [ ] **Step 3: Verify**

Run: `python -m unittest discover -s tests -v` (still `Ran 22 tests ... OK` — docs must not break anything).
Check `SKILL.md` frontmatter: `name` matches `substack-migration-check`; description contains the trigger phrases "migrate", "Substack export", "check", "clean".

- [ ] **Step 4: Commit**

```bash
git add SKILL.md README.md
git commit -m "docs: SKILL.md orchestration flow and README"
```

---

### Task 8: Final verification against a real export

**Files:**
- No new files (verification only; fix regressions if found).

**Interfaces:**
- Consumes: the complete skill.
- Produces: verified working software.

- [ ] **Step 1: Full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 22 tests ... OK`

- [ ] **Step 2: Smoke test on a real export (local only — do not commit outputs)**

Run: `python scripts/substack_check.py "C:/Users/david/Downloads/YautxsKAQlqIQtQ8CgFk7Q.zip" --out "C:/Users/david/AppData/Local/Temp/claude-smoke/migration-check"`
Expected: exit 0; JSON reports `subscribers.total_rows` = 4, `posts.total` = 11, `cdn_images_total` = 40 (±0 — these values were measured on this ZIP on 2026-07-09), non-empty `tables_markdown`. Inspect only the JSON, not the CSV artifacts (real subscriber emails).

- [ ] **Step 3: Verify repo completeness**

Run: `git status --short` (expect clean) and `git ls-files`
Expected files: `.gitignore`, `LICENSE`, `README.md`, `SKILL.md`, `references/checklist-map.md`, `scripts/substack_check.py`, `tests/__init__.py`, `tests/make_fixture.py`, `tests/test_substack_check.py`, plus `docs/superpowers/...`.

- [ ] **Step 4: Commit anything outstanding**

```bash
git status --short
# if anything is pending:
git add -A && git commit -m "chore: final verification fixes"
```
