# Measuring recall with your own flags

A sweep can report what it kept, but it cannot report what it never looked at.
Tuning its rules against the mail it already captured is tuning against
exactly the set that cannot reveal a miss. This eval closes that gap with
something you already have: **the flags you set in your own mail client.**

## The method

1. **Label.** Over a normal period, flag every message you consider a
   receipt, invoice, or bill *in your mail client* — Apple Mail, Gmail,
   whatever you use. Any flag or keyword that syncs over IMAP works. The
   standard `\Flagged` flag is the default; Apple Mail's flag *colours* are
   custom keywords (`$MailFlagBit0/1/2`) and can be used to reserve one colour
   for "this is a receipt".
2. **Audit.** Run [`recall_audit.py`](recall_audit.py) against the same window.
   It walks the folder headers-only, reads each message's FLAGS, applies the
   rules file, and writes a scorecard CSV.
3. **Read the scorecard.**

   | Bucket | Meaning | Action |
   |---|---|---|
   | flagged & matched | you labelled it, the rules caught it | none |
   | **flagged & not matched** | you labelled it, the rules **missed** it | **add the rule the row names** |
   | matched & not flagged | caught, not labelled | didn't bother, or a false positive — eyeball |
   | neither, but `looks_like_money` | broad vocabulary hit | triage for things you forgot to flag |

4. **Tune and repeat** until the missed bucket is empty across a few windows.
   Then stop flagging — the scaffold has done its job.

**Recall** = flagged & matched ÷ flagged. **Precision** you read off the sweep's
own run summary (how much of what it saved was marketing). The targets this
repo publishes: **≥ 0.95 recall on flagged receipts, ≤ 5 % marketing saved.**

## Running it

```
python3 eval/recall_audit.py \
    --config ~/imap-mcp/personal.yaml --config ~/imap-mcp/work.yaml \
    --rules rules.example.csv \
    --since 2026-08-01
```

It reads the same YAML configs the IMAP MCP server uses (host, port, username,
password — nothing else), so there is no second place to keep a credential.

Read-only throughout: folders are opened readonly, only `FROM SUBJECT DATE
MESSAGE-ID` header fields are fetched with `BODY.PEEK`, FLAGS are read and
never stored back, no bodies, no attachments. The only thing written is the
scorecard CSV in the current directory (git-ignored; it contains your senders
and subjects, so don't commit it).

### Using one Apple Mail colour (recommended)

If you flag things for other reasons too, reserve one colour for "this is a
receipt" and name it:

```
--apple-colour purple
```

The script knows Apple's encoding (the colour is a combination of the
`$MailFlagBit0/1/2` keywords — table in
[`../imap-mcp-kit/providers/icloud.md`](../imap-mcp-kit/providers/icloud.md))
and matches the colour exactly, so an orange flag is not mistaken for a purple
one. To see what your client actually stores — for a colour not in the table,
or for another provider's keywords — run once with `--show-flags`: it prints
the FLAGS of every flagged message. Then pass the keywords you see as the
ground-truth definition:

```
--flag '\Flagged' --flag '$SomeKeyword'
```

A message counts as ground truth only if it carries **all** the flags given.

## Fixtures (coming with the skill)

`fixtures/` will hold synthetic `.eml` files — receipt, renewal notice,
marketing, and the awkward "both a receipt and a notice" case — so contributors
can exercise the skill's classification without a mailbox. They are written,
not exported: no real mail ever enters this repository.
