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
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
CDN_IMAGE_RE = re.compile(
    r"https?://[^\"'\s>]*(?:substackcdn\.com|substack-post-media)[^\"'\s>]*"
)
SUBSTACK_LINK_RE = re.compile(r"href=[\"']https?://[^\"']*substack\.com[^\"']*[\"']")
EMBED_RE = re.compile(r"class=[\"'][^\"']*(?:embed|tweet|youtube)[^\"']*[\"']")
TRUEISH = {"true", "t", "yes", "1", "active"}
FALSISH = {"false", "f", "no", "0", "", "none", "inactive"}
PAID_PLANS = {"monthly", "month", "annually", "annual", "yearly", "year", "founding"}
FREE_PLANS = {"", "free", "none", "null"}

CLEANED_HEADER = [
    "email", "name", "status", "is_paid", "subscription_status",
    "subscription_expires_at", "created_at", "source", "tags",
]
EXCLUDED_HEADER = ["email", "reason", "file"]
INVENTORY_HEADER = [
    "post_id", "title", "is_published", "paywalled",
    "cdn_images", "substack_links", "embeds", "has_html",
]

UNSUBSCRIBE_NOTE = (
    "Substack's export has no unsubscribe column (only email_disabled). "
    "Verify your Substack export filter excluded unsubscribed contacts "
    "before importing anywhere."
)

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

    result["tables_markdown"] = render_tables(result)
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
