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
