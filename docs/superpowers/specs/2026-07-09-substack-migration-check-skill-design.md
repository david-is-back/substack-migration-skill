# Design: `substack-migration-check` skill

**Date:** 2026-07-09
**Status:** Approved pending user review
**Repo:** standalone repository (`substack-migration-skill`), independent from the checklist repo

## Overview

A public Claude Code skill that automates the automatable parts of the
[Substack Migration Checklist](https://github.com/david-is-back/substack-migration-checklist).
A user who has exported their Substack publication as a ZIP points the skill at that file;
the skill audits the export, produces a human-readable report, a cleaned subscriber CSV
ready for import, and a per-post dependency inventory — entirely offline.

The skill does not replace the checklist: sections that require live infrastructure
(domain/DNS, deliverability, paid billing transitions, announcements, post-migration audit)
are surfaced in the report as a condensed manual checklist with links back to the checklist repo.

## Goals

- Exact, reproducible numbers for subscriber-list and post-archive audits, at any export size.
- Zero network access and zero third-party dependencies: subscriber data never leaves the machine.
- Artifacts ready to use: cleaned import CSV (checklist template format), exclusions list, post inventory.
- Written in English, distributable as its own public repository.

## Non-goals

- No live checks (URL fetching, DNS, deliverability testing) — candidate for a future version.
- No platform-specific import automation (LetterBucket, Ghost, etc.); the cleaned CSV targets the
  checklist's platform-agnostic template.
- Never modifies the original export.

## Substack export format (ground truth)

Verified against a real export (2026-07):

- `email_list.<publication>.csv` — columns:
  `email, active_subscription, expiry, plan, email_disabled, created_at, first_payment_at`
- `posts.csv` — columns:
  `post_id, post_date, is_published, email_sent_at, inbox_sent_at, type, audience, title, subtitle, podcast_url`
  Includes drafts (`is_published=false`) and paid posts (`audience=only_paid`).
- `posts/<post_id>.<slug-or-hash>.html` — post bodies. Observed dependency patterns:
  images on `substackcdn.com` / `substack-post-media`, `href` links to `substack.com`,
  embed markup (tweets, videos).

Exports may contain multiple `email_list.*.csv` files (e.g. segmented free/paid exports).

## Repository layout

The repo root **is** the installable skill (copy or clone into `~/.claude/skills/substack-migration-check/`):

```
substack-migration-skill/
├── SKILL.md                    # frontmatter + orchestration flow for Claude
├── scripts/
│   └── substack_check.py       # single script, Python stdlib only
├── references/
│   └── checklist-map.md        # check → checklist-section map + manual-steps summary
├── README.md                   # what it does, install, usage, privacy statement
├── LICENSE                     # MIT
├── tests/
│   ├── test_substack_check.py  # unittest (stdlib), runs the script against fixtures
│   └── make_fixture.py         # builds anonymized fixture ZIPs at test time (no binary in git)
└── .gitignore
```

## Components

### 1. `scripts/substack_check.py`

Single stdlib-only script (`zipfile`, `csv`, `html.parser`, `re`, `json`, `argparse`, `io`).

- Input: path to the export ZIP; optional `--out <dir>` (default: `migration-check/` next to the ZIP).
- One streaming pass; no size limit in practice.
- Writes the deterministic artifacts (cleaned CSV, exclusions CSV, post inventory CSV).
- Emits a structured JSON summary to stdout — counts, per-check results, small samples
  (max 5 example rows per issue, emails redacted to `a***@domain.com` in samples).
  **Claude only ever reads this JSON, never the raw CSVs** — protects both privacy and context.
- Exit codes: `0` checks ran (issues or not, reported in JSON), `2` not a Substack export /
  unreadable ZIP (JSON error object with what was expected and a link to the export guide).

### 2. `SKILL.md`

- Frontmatter: name `substack-migration-check`; description triggers on migrating from Substack,
  checking/auditing/validating a Substack export ZIP, cleaning a Substack subscriber list.
- Flow: locate ZIP (ask if ambiguous) → run script → interpret JSON → write `report.md`
  (Claude-authored, from the JSON + `references/checklist-map.md`) → present summary with
  next manual steps.
- Fallback: if Python is unavailable, Claude may analyze inline only for small exports
  (< ~500 subscribers), stating that larger lists need Python for exact numbers.

### 3. `references/checklist-map.md`

Maps every automated check to its checklist section (§2 export integrity, §3 subscriber list,
§5 content archive) and condenses the non-automatable sections (§1, 4, 6, 7, 8, 9, 10) into the
manual-steps block the report embeds, with deep links to the checklist repo's guides.

## Checks

**Export integrity (checklist §2)**
- ZIP opens; `email_list*.csv`, `posts.csv`, `posts/*.html` present; none empty.
- `posts.csv` row count reconciles with HTML file count (report any orphans either way).
- If paid subscribers detected but no paid-specific export data available, flag it.

**Subscriber audit (checklist §3 + clean-your-subscriber-list guide)**
- Empty/malformed emails (no `@`, embedded spaces/commas, leading/trailing whitespace).
- Case-insensitive duplicates; when duplicates differ, keep the paid row.
- `email_disabled=true` → excluded as bounced/disabled.
- Paid detection via `active_subscription` / `plan`; paid rows missing `expiry` flagged.
- `created_at` present and parseable.
- Multiple `email_list.*.csv` files merged with cross-file duplicate detection.
- Output counts: total, importable, excluded per reason.

**Post audit (checklist §5)**
- Per post: published vs draft, `audience` (`only_paid` → re-apply paywall reminder),
  missing title/subtitle.
- Images hosted on `substackcdn.com` / `substack-post-media` (need re-hosting).
- `href` links to `substack.com` (internal links to rewrite).
- Embed markup (tweets, videos, Substack embeds — commonly break on transfer).

## Artifacts

Written to `migration-check/` (original export untouched):

1. `report.md` — Claude-authored: executive summary, per-check results with exact counts,
   artifact index, and the "still manual" condensed checklist with repo links.
2. `subscribers-cleaned.csv` — script-generated, mapped to the checklist template header
   `email,name,status,is_paid,subscription_status,subscription_expires_at,created_at,source,tags`,
   UTF-8 with header row.
3. `subscribers-excluded.csv` — every excluded row with its reason, for human review.
4. `posts-inventory.csv` — one row per post: id, title, published, paywalled,
   substack-CDN image count, substack.com link count, embed count.

## Error handling

- Not-an-export ZIP → clear message listing expected files + link to the export guide.
- Encoding: handle UTF-8 BOM; always write artifacts as UTF-8.
- Malformed CSV rows → counted and reported, never crash the run.
- Output dir exists → refuse to overwrite silently; suffix (`migration-check-2/`) and say so.

## Testing

- `tests/make_fixture.py` builds fixture ZIPs in a temp dir with planted cases: duplicate email
  (free+paid pair), malformed email, `email_disabled` row, paid row missing expiry, draft post,
  paid post, post with CDN images/substack links/embeds, and a "not an export" ZIP.
- `tests/test_substack_check.py` (stdlib `unittest`) asserts JSON counts, artifact contents,
  exit codes, and that the original ZIP is untouched.
- After implementation: skill-trigger evaluation via skill-creator.

## Distribution

- Standalone public GitHub repo. README covers: what it checks, install
  (clone/copy into `~/.claude/skills/`), usage, privacy statement (offline, no data leaves the machine).
- The checklist repo can later add a one-line link to this repo (out of scope here).

## Future (explicitly deferred)

- Optional online checks (old URL liveness, redirect verification).
- Packaged CLI (`npx`/`pipx`) with the skill as a thin wrapper.
