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
