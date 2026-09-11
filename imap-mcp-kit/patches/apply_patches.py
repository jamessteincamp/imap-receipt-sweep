#!/usr/bin/env python3
"""Apply the three source patches the reviewed imap-readonly-mcp (v0.4.0) needs.

Usage:
    python3 apply_patches.py /path/to/imap-readonly-mcp-main/.venv

Idempotent: re-running reports "already applied" and changes nothing.
Stdlib only. Edits only files inside the given venv's installed
`imap_readonly_mcp` package; prints exactly what it did.

What it patches (see README.md next to this file):
  1. server.py      — startup banner printed to stdout corrupts the MCP stdio
                      stream ("[imap-reado"... is not valid JSON) → send it to stderr
  2. connectors/imap.py — raise imaplib._MAXLINE so a large mailbox's SEARCH
                      reply doesn't trip Python's 1 MB line cap
  3. connectors/imap.py — guard an empty folder's [None] search result so it
                      returns 0 messages instead of crashing
"""
import os
import subprocess
import sys

PATCHES = [
    {
        "name": "banner → stderr",
        "file": "server.py",
        "old": 'Starting stdio transport", flush=True)',
        "new": 'Starting stdio transport", flush=True, file=__import__("sys").stderr)',
        "done_if": 'Starting stdio transport", flush=True, file=',
    },
    {
        "name": "imaplib._MAXLINE",
        "file": os.path.join("connectors", "imap.py"),
        "old": "\nimport imaplib\n",
        "new": "\nimport imaplib; imaplib._MAXLINE = 100000000\n",
        "done_if": "imaplib._MAXLINE",
    },
    {
        "name": "empty-search guard",
        "file": os.path.join("connectors", "imap.py"),
        "old": 'data[0].decode("ascii", errors="ignore")',
        "new": '(data[0] or b"").decode("ascii", errors="ignore")',
        "done_if": '(data[0] or b"").decode("ascii", errors="ignore")',
    },
]


def package_dir(venv):
    """Ask the venv's own interpreter where imap_readonly_mcp is installed."""
    py = os.path.join(venv, "Scripts" if os.name == "nt" else "bin",
                      "python.exe" if os.name == "nt" else "python")
    if not os.path.exists(py):
        sys.exit(f"no interpreter at {py} — is {venv} a virtual environment?")
    out = subprocess.run(
        [py, "-c", "import imap_readonly_mcp, os; print(os.path.dirname(imap_readonly_mcp.__file__))"],
        capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("imap_readonly_mcp is not installed in that venv:\n" + out.stderr.strip())
    return out.stdout.strip()


def apply(pkg, patch):
    path = os.path.join(pkg, patch["file"])
    if not os.path.exists(path):
        return "file not found", path
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if patch["done_if"] in text:
        return "already applied", path
    if patch["old"] not in text:
        return "pattern not found (different version?)", path
    if text.count(patch["old"]) != 1:
        return "pattern ambiguous — not touching", path
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(patch["old"], patch["new"], 1))
    return "applied", path


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    venv = os.path.abspath(os.path.expanduser(sys.argv[1]))
    pkg = package_dir(venv)
    print(f"package: {pkg}")
    worst = 0
    for p in PATCHES:
        status, path = apply(pkg, p)
        print(f"  {p['name']:22} {status:40} {os.path.relpath(path, pkg)}")
        if status not in ("applied", "already applied"):
            worst = 1
    if worst:
        print("\nOne or more patches did not apply. If this is not v0.4.0, compare "
              "README.md next to this script against the source and patch by hand.")
    else:
        print("\nAll patches in place. Remember: re-run this after any reinstall or upgrade.")
    sys.exit(worst)


if __name__ == "__main__":
    main()
