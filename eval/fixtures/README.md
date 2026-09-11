# Fixtures — a mailbox in nine files, none of them real

Synthetic `.eml` messages for exercising the skill's judgement without a
mailbox. Every sender, vendor, amount, order number and Message-ID is invented
and every domain is a reserved example domain. They are **written, not
exported**; `make_fixtures.py` is the proof and regenerates them byte-for-byte.

Two folders = two accounts, so the cross-account duplicate case is testable:

| File | What a correct sweep does |
|---|---|
| `personal/receipt-html.eml` | `receipt`, $42.17, saves the HTML body |
| `personal/receipt-pdf-attachment.eml` | `receipt`, $19.00, saves the PDF attachment |
| `personal/renewal-notice.eml` | `renewal-notice`, $9.99, `renews_on` 2026-10-01 |
| `personal/statement-available.eml` | `statement-available`, no amount |
| `personal/marketing.eml` | **skip** — prices, but nothing bought |
| `personal/receipt-and-renewal.eml` | `receipt` **with** `renews_on` 2026-10-05 — the both-at-once case |
| `personal/shipping-notice.eml` | **skip** — the receipt is a separate message |
| `work/receipt-html-duplicate.eml` | **duplicate** — same Message-ID as the first; no line, no file |
| `work/refund.eml` | `receipt`, −$19.00 — money moved back is still a receipt |

`expected.jsonl` states the same thing machine-readably; `eval/check_run.py`
compares a sweep's manifest against it.

## Running the skill on them

Point the skill at the folder instead of a mailbox:

> Sweep the fixture mailboxes under `eval/fixtures/` into `/tmp/sweep-test/inbox`.

The skill's `scripts/eml_to_json.py` turns each `.eml` into the same JSON shape
the IMAP MCP server returns, so the skill runs the identical loop in both modes.
