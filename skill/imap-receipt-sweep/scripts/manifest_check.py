#!/usr/bin/env python3
"""Validate an inbox's .sweep-manifest.jsonl and report its state.

    python3 manifest_check.py <inbox-dir>            # validate + summary
    python3 manifest_check.py <inbox-dir> --last     # print the latest `date` (for the window)
    python3 manifest_check.py <inbox-dir> --ids      # print every message_id (for de-dupe)

Mirrors manifest.schema.json at the repo root: required keys, the `kind`
enum, the Message-ID and amount patterns, and that every `file` exists.
Exit 1 on any invalid line. Stdlib only; reads only.
"""
import json
import os
import re
import sys

REQUIRED = ["message_id", "account", "date", "from", "subject", "kind", "file", "swept_at"]
OPTIONAL = ["amounts", "vendor", "renews_on", "source_id", "notes"]
KINDS = {"receipt", "renewal-notice", "statement-available"}
MSGID = re.compile(r"^<.+>$")
AMOUNT = re.compile(r"^-?[0-9]+\.[0-9]{2}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check(inbox):
    path = os.path.join(inbox, ".sweep-manifest.jsonl")
    if not os.path.exists(path):
        return [], []
    rows, errors, seen = [], [], set()
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {n}: not JSON ({e})")
                continue
            for k in REQUIRED:
                if k not in r:
                    errors.append(f"line {n}: missing {k}")
            for k in r:
                if k not in REQUIRED + OPTIONAL:
                    errors.append(f"line {n}: unknown key {k}")
            if not MSGID.match(str(r.get("message_id", ""))):
                errors.append(f"line {n}: message_id must look like <…>")
            if r.get("kind") not in KINDS:
                errors.append(f"line {n}: kind {r.get('kind')!r} not in {sorted(KINDS)}")
            if not DATE.match(str(r.get("date", ""))):
                errors.append(f"line {n}: date must be YYYY-MM-DD")
            if r.get("renews_on") not in (None, "") and not DATE.match(str(r["renews_on"])):
                errors.append(f"line {n}: renews_on must be YYYY-MM-DD or null")
            for a in r.get("amounts", []) or []:
                if not AMOUNT.match(str(a)):
                    errors.append(f"line {n}: amount {a!r} must be a decimal string like 12.34")
            f = r.get("file", "")
            if f and not os.path.exists(os.path.join(inbox, f)):
                errors.append(f"line {n}: file not found in inbox: {f}")
            if r.get("message_id") in seen:
                errors.append(f"line {n}: duplicate message_id {r['message_id']}")
            seen.add(r.get("message_id"))
            rows.append(r)
    return rows, errors


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    inbox = os.path.abspath(os.path.expanduser(sys.argv[1]))
    rows, errors = check(inbox)
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    if mode == "--last":
        print(max((r["date"] for r in rows if DATE.match(str(r.get("date", "")))), default=""))
        return
    if mode == "--ids":
        for r in rows:
            print(r.get("message_id", ""))
        return
    by_kind = {}
    for r in rows:
        by_kind[r.get("kind")] = by_kind.get(r.get("kind"), 0) + 1
    print(f"{len(rows)} manifest line(s) in {inbox}: " +
          ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    for e in errors:
        print("  !", e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
