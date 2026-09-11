#!/usr/bin/env python3
"""Score a fixture-mode sweep against eval/fixtures/expected.jsonl.

    python3 check_run.py <inbox-dir> [--expected eval/fixtures/expected.jsonl]

For every fixture it checks: a keep got exactly one manifest line with the
right kind, the expected amounts, a vendor containing the expected word, the
right renews_on, and a saved file with the expected extension that exists; a
skip got no line; the duplicate got no line beyond the original's. Exit 1 on
any failure. Stdlib only.
"""
import argparse
import email
import email.policy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def message_id_of(eml_path):
    with open(eml_path, "rb") as fh:
        return (email.message_from_bytes(fh.read(), policy=email.policy.default)["Message-ID"] or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inbox")
    ap.add_argument("--expected", default=os.path.join(HERE, "fixtures", "expected.jsonl"))
    a = ap.parse_args()
    fixtures_dir = os.path.dirname(os.path.abspath(a.expected))

    manifest = os.path.join(a.inbox, ".sweep-manifest.jsonl")
    lines = []
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
    by_id = {}
    for r in lines:
        by_id.setdefault(r.get("message_id"), []).append(r)

    results = []
    with open(a.expected, encoding="utf-8") as fh:
        expected = [json.loads(l) for l in fh if l.strip()]

    for e in expected:
        mid = message_id_of(os.path.join(fixtures_dir, e["file"]))
        got = by_id.get(mid, [])
        name = e["file"]
        if e["kind"] == "skip":
            results.append((name, "no manifest line", len(got) == 0, f"{len(got)} line(s)"))
            continue
        if e["kind"] == "duplicate":
            # the original (same Message-ID) must have exactly one line in total
            results.append((name, "duplicate not written (one line for the Message-ID overall)",
                            len(got) == 1, f"{len(got)} line(s) for {mid}"))
            continue
        if len(got) != 1:
            results.append((name, f"exactly one line, kind {e['kind']}", False, f"{len(got)} line(s)"))
            continue
        r = got[0]
        results.append((name, f"kind == {e['kind']}", r.get("kind") == e["kind"], f"got {r.get('kind')}"))
        amts = [str(x) for x in (r.get("amounts") or [])]
        for want in e.get("amounts_include", []):
            results.append((name, f"amounts include {want}", want in amts, f"got {amts}"))
        if not e.get("amounts_include"):
            results.append((name, "amounts empty", not amts, f"got {amts}"))
        if e.get("vendor_contains"):
            v = (r.get("vendor") or "")
            results.append((name, f"vendor contains '{e['vendor_contains']}'",
                            e["vendor_contains"].lower() in v.lower(), f"got {v!r}"))
        results.append((name, f"renews_on == {e.get('renews_on')}",
                        (r.get("renews_on") or None) == e.get("renews_on"), f"got {r.get('renews_on')!r}"))
        f = r.get("file") or ""
        results.append((name, f"file saved with {e['saved_ext']}",
                        f.endswith(e["saved_ext"]) and os.path.exists(os.path.join(a.inbox, f)),
                        f"got {f!r}, exists={os.path.exists(os.path.join(a.inbox, f))}"))
        results.append((name, "file name starts with YYYY-MM-DD_",
                        len(f) > 11 and f[4] == "-" and f[7] == "-" and f[10] == "_", f"got {f!r}"))

    failed = [r for r in results if not r[2]]
    for name, what, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:40} {what:60} {'' if ok else detail}")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; {len(lines)} manifest line(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
