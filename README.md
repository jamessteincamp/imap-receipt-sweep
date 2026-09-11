# imap-receipt-sweep

Pull the receipts, invoices, and renewal notices out of your own mailbox into a
local folder — by asking Claude to, through a **read-only** IMAP connection,
with nothing ever leaving your machine.

Works with **any IMAP mailbox**. It was built against iCloud, so iCloud is the
worked example throughout; Gmail and Fastmail have provider notes waiting for
someone to confirm them.

Two parts:

- **[`imap-mcp-kit/`](imap-mcp-kit/)** — a vetted, pinned, patched install of a
  read-only IMAP MCP server for the Claude desktop app, with the password
  helper and the four fixes it needs to survive a real mailbox. **Shipped.**
  Useful on its own for anything you want Claude to *read* in your mail.
- **[`skill/imap-receipt-sweep/`](skill/imap-receipt-sweep/)** — the sweep
  itself: a Claude skill that reads recent mail through that server, decides
  by *reading* (not regex) what is a receipt, what is a renewal or statement
  notice, and what is marketing, and drops each keep into a local inbox folder
  with a one-line manifest entry. **Shipped**, with synthetic fixtures and a
  checker so you can see it judge before pointing it at your mail.

## The promise

These hold for the kit today and are the contract the skill is written to.

- **Read-only.** The server has no tool to send, delete, move, or flag mail —
  it opens every folder read-only and uses `BODY.PEEK`. Nothing can change
  your mailbox through it, whatever a prompt or a message's contents says.
- **Only when you ask.** The sweep runs on an explicit request. It is never
  scheduled, never runs in the background, and the skill says so in its own
  text.
- **Nothing leaves.** Mail flows one way: server → local files. Nothing is
  uploaded anywhere. The skill never holds a credential; the MCP server is
  yours, configured by you.
- **Honest about the cache.** The server caches fetched mail in a local SQLite
  file. The install guide says where, locks the folder down, and tells you how
  to clear it. We don't pretend otherwise.

## Quick start

1. Install the server for one mailbox: [`imap-mcp-kit/INSTALL.md`](imap-mcp-kit/INSTALL.md)
   (Python 3.11+, ~15 minutes, iCloud notes in [`providers/icloud.md`](imap-mcp-kit/providers/icloud.md)).
2. Ask Claude something that proves it works: *"Search my personal mailbox
   INBOX for receipts from the last 30 days."* Always name the folder.
3. Install the skill. Claude Code: `cp -r skill/imap-receipt-sweep ~/.claude/skills/`.
   Claude desktop app: zip that folder and add it as a custom skill in
   Settings. Then: *"Sweep my personal mailbox for receipts since the 1st into
   `~/receipts/inbox`."*
4. Optional: measure how well a rules file finds your receipts with
   [`eval/`](eval/) — flag some receipts in your mail client (one Apple Mail
   colour, say), run the audit, read the misses.

## The skill contract

- **Trigger:** an explicit ask ("sweep my mail for receipts"). Never scheduled.
- **Inputs:** an inbox folder path; optionally a rules file
  ([`rules.example.csv`](rules.example.csv)) to narrow the search; a window
  (default: since the last manifest entry, minus two days of overlap); which
  mail MCP servers to use.
- **Loop:** per account, search `INBOX` with the rules' terms plus a generic
  receipt vocabulary → read each candidate → classify as
  `receipt | renewal-notice | statement-available | skip` → for a keep, save
  the PDF/image attachment or the HTML body as
  `YYYY-MM-DD_<sender-slug>_<subject-slug>.<ext>` → append one manifest line.
- **Guarantees, in the skill's own words:** reads only; never marks read,
  moves, or deletes; never uploads; de-dupes on `Message-ID` across accounts;
  saves at most N per account per run; stops and reports on any auth error
  rather than retrying.
- **Output:** the folder plus a run summary — searched / matched / saved /
  skipped-as-duplicate / notices, per account.

Why a skill and not code: the hard part of a sweep is judgement — *is this
marketing or a receipt? is it a receipt **and** a renewal notice?* — which
substring rules do badly and untestably. The easy parts (de-dupe, don't
re-save, never upload) are a few lines the skill states and the manifest
enforces.

How it has been tested: against the nine synthetic fixtures in
[`eval/fixtures/`](eval/fixtures/) (all nine judged correctly, manifest valid
— `eval/check_run.py` scores a run), and one live read-only pass over a real
iCloud INBOX (ten days, ten saves, folder always named, cap honoured, no
shipping notices, attachment saved as a PDF). The same model *without* the
skill made the same keep/skip decisions but wrote a manifest a consumer
couldn't use — amounts as objects, dates as timestamps, stray `.eml` copies —
which is what the skill is for.

## The manifest

One JSON object per line in `<inbox>/.sweep-manifest.jsonl`, schema in
[`manifest.schema.json`](manifest.schema.json):

```json
{"message_id": "<abc@example.com>", "account": "personal", "date": "2026-09-05",
 "from": "billing@example.com", "subject": "Your receipt", "kind": "receipt",
 "file": "2026-09-05_example_your-receipt.pdf", "amounts": ["12.34"],
 "vendor": "Example", "renews_on": null, "swept_at": "2026-09-06T10:00:00"}
```

Consumers key on `message_id` for de-dupe and on `kind` for routing. What
happens to the folder afterwards is the consuming application's business —
this repo stops at the folder.

## Layout

```
README.md                  this file
LICENSE                    MIT
rules.example.csv          field,contains,mode — optional narrowing rules, generic entries only
manifest.schema.json       the per-file record the skill writes
skill/imap-receipt-sweep/
  SKILL.md                 the skill: contract, search, classification guide, saving, manifest, fixture mode
  scripts/eml_to_json.py   fixture mode — .eml files in the shape mail_fetch returns
  scripts/manifest_check.py  validates a manifest; prints the last date / the ids
eval/
  README.md                the flagged-mail recall method
  recall_audit.py          stdlib; headers-only; writes a scorecard CSV
  check_run.py             scores a fixture-mode sweep against expected.jsonl
  fixtures/                nine synthetic .eml files across two "accounts", the generator, and the answer key
imap-mcp-kit/
  INSTALL.md               the vetted read-only server: install, patch, configure, register
  setpw.py                 app-password prompt-verify-write helper
  config.example.yaml      per-account config with placeholders
  claude_desktop_config.example.json
  patches/                 the three source patches + the cache_path note, with a script to apply them
  providers/               icloud.md (worked example) · gmail.md, fastmail.md (stubs)
```

## Contributing

Provider notes are the easiest contribution: confirm a stub, or add a
provider. Fixture `.eml` files must be **written, not exported** — no real
sender, subject, amount, or account may enter this repository, in fixtures,
docs, or tests. Scorecard CSVs and config YAMLs are git-ignored for the same
reason; check before you commit.

## License

MIT — see [LICENSE](LICENSE). The IMAP server this kit installs is a separate
project under its own license; the kit contains only instructions, patches,
and helpers, not its code.
