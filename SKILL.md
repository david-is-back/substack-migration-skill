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
2. **Check Python**: run `python --version` (or `python3`). Needs 3.9+;
   if `python` reports Python 2, use `python3`.
3. **Run the audit:**
   `python <skill-dir>/scripts/substack_check.py <zip-path>`
   Optional: `--out <dir>` (default: `migration-check/` next to the ZIP,
   auto-suffixed if it exists).
4. **Interpret the JSON** (stdout):
   - Exit 2 → not a Substack export. Relay `expected` to the user.
   - Exit 0 → read `sections` (each `ran` or `skipped`), `warnings`,
     `artifacts`, `tables_markdown`.
   - Any other exit code or missing JSON -> relay the error to the user and
     stop; never open or inspect the export files yourself.
5. **Write `report.md`** in the output directory (`out_dir` in the JSON):
   - Executive summary (2-4 sentences: is this export ready to migrate?).
   - One section per check: embed the matching `tables_markdown` table
     **verbatim — never retype numbers** — plus a short interpretation.
     (`tables_markdown` has entries only for `subscribers` and `posts`;
     summarize `export_integrity` from its section keys instead.)
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
