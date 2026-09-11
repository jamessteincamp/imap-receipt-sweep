#!/usr/bin/env python3
"""Turn .eml files into the JSON shape the IMAP MCP server's `mail_fetch`
returns — so the sweep skill runs the same loop on fixtures as on a mailbox.

    python3 eml_to_json.py <dir-or-file> [...]          # metadata listing (like include=metadata)
    python3 eml_to_json.py --full <dir-or-file> [...]   # full (headers, body_text, body_html, attachments)
    python3 eml_to_json.py --attachment <file.eml> <index> <out-path>
                                                        # write one attachment to disk

A directory is one "account": its name becomes the account name and every
.eml inside it a message with id  eml://<account>/<filename>.
Stdlib only. Reads files; the only write is --attachment's output path.
"""
import base64
import email
import email.policy
import email.utils
import json
import os
import sys


def load(path):
    with open(path, "rb") as fh:
        return email.message_from_bytes(fh.read(), policy=email.policy.default)


def addr_list(value):
    out = []
    for name, addr in email.utils.getaddresses([value or ""]):
        if addr:
            out.append({"name": name, "email": addr} if name else {"email": addr})
    return out


def attachments(msg):
    """Same convention as the server: attachments are the parts with a filename,
    indexed 0-based in walk order."""
    out, i = [], 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        fn = part.get_filename()
        if fn:
            out.append({"index": i, "filename": fn, "content_type": part.get_content_type(),
                        "size": len(part.get_payload(decode=True) or b"")})
            i += 1
    return out


def bodies(msg):
    text = html = None
    for part in msg.walk():
        if part.is_multipart() or part.get_filename():
            continue
        ct = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            payload = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if ct == "text/plain" and text is None:
            text = payload
        elif ct == "text/html" and html is None:
            html = payload
    return text, html


def record(path, account, full):
    msg = load(path)
    try:
        date = email.utils.parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        date = ""
    text, html = bodies(msg)
    att = attachments(msg)
    rec = {
        "id": f"eml://{account}/{os.path.basename(path)}",
        "folder": "INBOX",
        "date": date,
        "from": addr_list(msg["From"]),
        "to": addr_list(msg["To"]),
        "subject": msg["Subject"] or "",
        "snippet": " ".join((text or html or "").split())[:240],
        "has_attachments": bool(att),
        "attachments": att,
    }
    if full:
        rec["headers"] = {k: [str(v)] for k, v in msg.items()
                          if k.lower() in ("from", "to", "date", "subject", "message-id", "reply-to")}
        if text is not None:
            rec["body_text"] = text
        if html is not None:
            rec["body_html"] = html
    return rec


def write_attachment(path, index, out):
    msg = load(path)
    i = 0
    for part in msg.walk():
        if part.is_multipart() or not part.get_filename():
            continue
        if i == int(index):
            with open(out, "wb") as fh:
                fh.write(part.get_payload(decode=True) or b"")
            print(json.dumps({"filename": part.get_filename(), "bytes": os.path.getsize(out), "path": out}))
            return
        i += 1
    sys.exit(f"no attachment with index {index} in {path}")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    if argv[0] == "--attachment":
        return write_attachment(*argv[1:4])
    full = argv[0] == "--full"
    paths = argv[1:] if full else argv
    items = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            account = os.path.basename(p.rstrip("/"))
            for f in sorted(os.listdir(p)):
                if f.lower().endswith(".eml"):
                    items.append(record(os.path.join(p, f), account, full))
        else:
            items.append(record(p, os.path.basename(os.path.dirname(p)) or "local", full))
    print(json.dumps({"items": items}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
