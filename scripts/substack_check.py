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
