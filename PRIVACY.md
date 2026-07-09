# Privacy Policy

**substack-migration-check** is designed so that your subscriber data never
has to leave your machine. This page describes exactly what the plugin does
and does not do with your data.

## What the plugin processes

When you point the plugin at a Substack export ZIP, a dependency-free Python
script on **your machine** reads it and processes:

- your subscriber list (`email_list*.csv`) — email addresses, subscription
  status, plan, dates
- your post index (`posts.csv`) and post HTML files

## What stays on your machine

- **All raw data.** The script has no network access and makes no network
  calls. Nothing in the export is uploaded anywhere by this plugin.
- **All artifacts.** The cleaned subscriber CSV, the exclusions list, the
  post inventory, and the report are written to a local folder next to your
  ZIP. Your original export is never modified.

## What the AI model sees

Claude orchestrates the audit by reading the script's JSON summary, which
contains **only**:

- aggregate counts (totals, per-reason exclusion counts, per-post dependency
  counts)
- up to five example rows per issue with **redacted** email addresses
  (`a***@example.com`)
- pre-rendered numeric tables and warnings

That JSON summary becomes part of your Claude Code conversation and is
therefore handled under the privacy terms of your Claude / Anthropic
agreement, like everything else you type or show to Claude. Raw subscriber
emails, names, and file contents are never placed in the conversation — the
skill's instructions explicitly forbid the model from opening the export
files, and if the script cannot run, the skill stops rather than reading
your data inline.

## What we collect

Nothing. The plugin has no telemetry, no analytics, no accounts, and no
servers. The authors receive no data of any kind from your use of it.

## Questions

Open an issue at
[github.com/david-is-back/substack-migration-skill](https://github.com/david-is-back/substack-migration-skill/issues).
