# Checklist map

Generated against [substack-migration-checklist](https://github.com/david-is-back/substack-migration-checklist)
commit `42f5d200d092357120f174f57353d7e6f46f9e74`. If upstream has moved, links and the CSV template header may have drifted — verify before trusting them.

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
