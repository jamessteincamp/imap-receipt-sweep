#!/usr/bin/env python3
"""Validate an inbox's manifest — a thin wrapper over manifest.py, kept so
existing instructions keep working.

    python3 manifest_check.py <inbox-dir>            # validate + summary
    python3 manifest_check.py <inbox-dir> --last     # print the latest `date`
    python3 manifest_check.py <inbox-dir> --ids      # print every message_id

New callers: `manifest.py status <inbox>` gives all of this, and the window,
in one JSON object. Exit 1 on any invalid line. Stdlib only; reads only.
"""
import os
import sys

import manifest


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    inbox = os.path.abspath(os.path.expanduser(sys.argv[1]))
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    rows = manifest.read_lines(inbox)
    if mode == "--last":
        print(max((r["date"] for r in rows if manifest._is_date(str(r.get("date", "")))), default=""))
        return
    if mode == "--ids":
        for r in rows:
            print(r.get("message_id", ""))
        return
    s = manifest.status(inbox)
    by_kind = {}
    for r in rows:
        by_kind[r.get("kind")] = by_kind.get(r.get("kind"), 0) + 1
    print(f"{len(rows)} manifest line(s) in {inbox}: " +
          ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items(), key=str)))
    for e in s["errors"]:
        print(f"  ! line {e['line']}: {e['message']}")
    sys.exit(0 if s["manifest_valid"] else 1)


if __name__ == "__main__":
    main()
