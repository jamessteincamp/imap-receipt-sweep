#!/usr/bin/env python3
"""imap-receipt-sweep recall audit — read-only, headers only, saves no mail.

A sweep tells you what its rules CAUGHT (precision). This tells you what they
MISSED (recall). You flag, in your own mail client, the messages you consider
receipts/invoices/bills — any flag or keyword your provider syncs over IMAP.
This script walks the same window headers-only, applies the same rules file,
reads each message's FLAGS, and crosses the two:

    flagged & matched      — labelled by you, caught by the rules   (good)
    flagged & NOT matched  — labelled by you, MISSED by the rules   (the point:
                             each row names the sender/subject rule to add)
    matched & not flagged  — caught but not labelled: didn't bother, or a
                             possible false positive to eyeball

Recall = flagged&matched / flagged.  Precision is read off the sweep itself.

Read-only throughout: every folder is opened readonly, only header fields are
fetched (BODY.PEEK), FLAGS are read never written, no bodies, no attachments.
The only write is the local CSV scorecard. Stdlib only.

Usage:
    python3 recall_audit.py --config ~/imap-mcp/personal.yaml [--config ...]
                            [--rules ../rules.example.csv]
                            [--since 2026-08-01]          default: 30 days ago
                            [--folder INBOX]
                            [--flag '\\Flagged']           default; or a keyword such as $MailFlagBit1
                            [--flag ...]                  repeat: message must carry ALL of them
                            [--apple-colour purple]       Apple Mail flag colour (exact match on the colour bits)
                            [--show-flags]                print the FLAGS of every flagged message
                                                          (use once, to find your colour's keywords)
                            [--out recall-audit-YYYY-MM-DD.csv]

Config files are the same YAML the IMAP MCP server uses (imap-mcp-kit/); this
script reads host/port/username/password from them and nothing else.
"""
import argparse
import csv
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import os
import re
import ssl
import sys

imaplib._MAXLINE = 100_000_000          # a long-lived INBOX's SEARCH reply exceeds the 1 MB default

# Deliberately WIDER than any rules file — used only to triage unflagged,
# unmatched mail that still smells like money. Never used to save anything.
MONEY_HINTS = [
    "receipt", "invoice", "order", "purchase", "payment", "paid", "charged",
    "charge", "billing", "bill", "statement", "refund", "return", "confirm",
    "confirmation", "booking", "reservation", "reserved", "itinerary", "ticket",
    "subscription", "renew", "membership", "transaction", "checkout", "sold",
    "shipped", "delivery", "e-receipt", "thank you for your", "total", "$",
]

HEADER_SPEC = "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
CHUNK = 200

# Apple Mail stores a flag's colour as a combination of three custom keywords
# on top of the standard \\Flagged flag. Exact match on the three bits.
APPLE_BITS = {"$MailFlagBit0", "$MailFlagBit1", "$MailFlagBit2"}
APPLE_COLOURS = {
    "red":    set(),
    "orange": {"$MailFlagBit0"},
    "yellow": {"$MailFlagBit1"},
    "green":  {"$MailFlagBit0", "$MailFlagBit1"},
    "blue":   {"$MailFlagBit2"},
    "purple": {"$MailFlagBit0", "$MailFlagBit2"},
    "gray":   {"$MailFlagBit1", "$MailFlagBit2"},
}


# ---------------------------------------------------------------- inputs

def _value(raw):
    """A YAML scalar as the server's config uses it: quoted, or bare with an
    optional trailing `# comment`."""
    raw = raw.strip()
    m = re.match(r"""^(["'])(.*?)\1""", raw)
    if m:
        return m.group(2)
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def read_config(path):
    """Minimal reader for the server's YAML shape — the four keys under
    `account:` — with no YAML dependency."""
    acct = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^\s+(host|port|username|password):\s*(.+?)\s*$", line)
            if m:
                acct[m.group(1)] = _value(m.group(2))
    missing = {"host", "username", "password"} - acct.keys()
    if missing:
        sys.exit(f"{path}: missing {sorted(missing)}")
    acct["port"] = int(acct.get("port", 993))
    acct["name"] = os.path.splitext(os.path.basename(path))[0]
    return acct


def read_rules(path):
    """rules.csv → [(field, needle, mode)]; field ∈ {from, subject},
    mode ∈ {include, exclude} (blank → include)."""
    if not path:
        return []
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            needle = (r.get("contains") or "").strip().lower()
            if not needle:
                continue
            out.append(((r.get("field") or "subject").strip().lower(), needle,
                        (r.get("mode") or "include").strip().lower()))
    return out


def matches(rules, sender, subject):
    """True iff an include rule hits and no exclude rule does. Exclusions veto,
    so a marketing blast with a receipt-ish subject is dropped while a real
    order confirmation from the same vendor is kept."""
    sender, subject = (sender or "").lower(), (subject or "").lower()

    def hit(field, needle):
        return needle in (sender if field == "from" else subject)

    if any(hit(f, n) for f, n, m in rules if m == "exclude"):
        return False
    return any(hit(f, n) for f, n, m in rules if m != "exclude")


def looks_like_money(subject):
    s = (subject or "").lower()
    return int(any(h in s for h in MONEY_HINTS))


# ---------------------------------------------------------------- IMAP

def decode(h):
    try:
        return "".join(s.decode(enc or "utf-8", "replace") if isinstance(s, bytes) else s
                       for s, enc in email.header.decode_header(h or ""))
    except Exception:
        return h or ""


_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")


def iter_headers(M, ids):
    """Yield (flags:set[str], headers:Message) per message. Tolerates the odd
    shapes some servers return (bare ints / flag atoms interleaved with the
    (envelope, bytes) tuples)."""
    for i in range(0, len(ids), CHUNK):
        chunk = b",".join(ids[i:i + CHUNK])
        typ, data = M.fetch(chunk, HEADER_SPEC)
        if typ != "OK" or not data:
            continue
        for item in data:
            if not (isinstance(item, tuple) and len(item) >= 2
                    and isinstance(item[1], (bytes, bytearray))):
                continue
            m = _FLAGS.search(item[0])
            flags = set(m.group(1).decode("ascii", "replace").split()) if m else set()
            yield flags, email.message_from_bytes(bytes(item[1]))


def is_ground_truth(flags, want_flags, colour):
    if colour is not None:
        return int("\\Flagged" in flags and (flags & APPLE_BITS) == APPLE_COLOURS[colour])
    return int(want_flags <= flags)


def audit_account(acct, since, folder, rules, want_flags, colour, show_flags):
    rows = []
    M = imaplib.IMAP4_SSL(acct["host"], acct["port"], ssl_context=ssl.create_default_context())
    try:
        M.login(acct["username"], acct["password"])
        typ, _ = M.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open folder {folder!r}")
        typ, data = M.search(None, f'SINCE {since.strftime("%d-%b-%Y")}')
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        for flags, h in iter_headers(M, ids):
            sender, subject = decode(h.get("From")), decode(h.get("Subject"))
            try:
                d = email.utils.parsedate_to_datetime(h.get("Date")).date().isoformat()
            except Exception:
                d = ""
            flagged = is_ground_truth(flags, want_flags, colour)
            if show_flags and "\\Flagged" in flags:
                print(f"    {d}  {' '.join(sorted(flags)):40}  {subject[:50]}")
            rows.append(dict(
                account=acct["name"], date=d, sender=sender, subject=subject,
                message_id=(h.get("Message-ID") or "").strip(),
                flagged=flagged, matched=int(matches(rules, sender, subject)),
                looks_like_money=looks_like_money(subject),
            ))
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return rows


# ---------------------------------------------------------------- main

def summarize(rows):
    n = len(rows)
    flagged = [r for r in rows if r["flagged"]]
    caught = [r for r in flagged if r["matched"]]
    missed = [r for r in flagged if not r["matched"]]
    extra = [r for r in rows if r["matched"] and not r["flagged"]]
    smell = [r for r in rows if not r["matched"] and not r["flagged"] and r["looks_like_money"]]
    recall = (len(caught) / len(flagged)) if flagged else float("nan")
    return n, flagged, caught, missed, extra, smell, recall


def main():
    ap = argparse.ArgumentParser(description="imap-receipt-sweep recall audit (read-only, headers only)")
    ap.add_argument("--config", action="append", required=True, help="account YAML; repeatable")
    ap.add_argument("--rules", help="rules CSV (field,contains,mode); omit to measure with no rules")
    ap.add_argument("--since", help="YYYY-MM-DD; default 30 days ago")
    ap.add_argument("--folder", default="INBOX")
    ap.add_argument("--flag", action="append",
                    help=r"flag/keyword marking ground truth; default \Flagged; repeat = ALL required")
    ap.add_argument("--apple-colour", "--apple-color", choices=sorted(APPLE_COLOURS),
                    help="Apple Mail flag colour that marks ground truth (exact match); overrides --flag")
    ap.add_argument("--show-flags", action="store_true",
                    help="print the FLAGS of every \\Flagged message (to find a colour's keywords)")
    ap.add_argument("--out", help="scorecard CSV path")
    a = ap.parse_args()

    since = dt.date.fromisoformat(a.since) if a.since else dt.date.today() - dt.timedelta(days=30)
    want = set(a.flag or ["\\Flagged"])
    rules = read_rules(a.rules)
    out = a.out or f"recall-audit-{dt.date.today().isoformat()}.csv"

    truth = f"Apple {a.apple_colour} flag" if a.apple_colour else " + ".join(sorted(want))
    print(f"auditing {a.folder} headers since {since}, ground truth = {truth}, "
          f"{len(rules)} rule(s) (read-only)…")
    rows = []
    for path in a.config:
        acct = read_config(os.path.expanduser(path))
        try:
            got = audit_account(acct, since, a.folder, rules, want, a.apple_colour, a.show_flags)
        except Exception as e:
            print(f"  {acct['name']:14} ERROR {type(e).__name__}: {e}")
            continue
        rows.extend(got)
        n, fl, ca, mi, ex, sm, rc = summarize(got)
        print(f"  {acct['name']:14} scanned {n:5}  flagged {len(fl):4}  caught {len(ca):4}  "
              f"missed {len(mi):4}  unflagged-matched {len(ex):4}  "
              f"recall {rc:.2f}" if fl else
              f"  {acct['name']:14} scanned {n:5}  flagged    0  (no ground truth in window)")

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["account", "date", "sender", "subject", "message_id",
                                           "flagged", "matched", "looks_like_money"])
        w.writeheader()
        w.writerows(rows)

    n, fl, ca, mi, ex, sm, rc = summarize(rows)
    print(f"\n{n} header(s) audited → {out}")
    if fl:
        print(f"RECALL {rc:.3f}  ({len(ca)} of {len(fl)} flagged messages would have been kept)")
    if mi:
        print(f"\nMISSED — flagged by you, not matched by the rules ({len(mi)}):")
        for r in mi:
            print(f"  {r['date']}  {r['sender'][:40]:40}  {r['subject'][:60]}")
    if ex:
        print(f"\nmatched but not flagged: {len(ex)} — eyeball for false positives")
    if sm:
        print(f"unflagged, unmatched, smells like money: {len(sm)} — triage column looks_like_money")
    print("\nNo mail was saved, read-marked, or changed.")


if __name__ == "__main__":
    main()
