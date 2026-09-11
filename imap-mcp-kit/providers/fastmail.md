# Fastmail — stub, untested

Not yet verified with this kit. What is known; contributions welcome.

| | |
|---|---|
| Host | `imap.fastmail.com` |
| Port | `993` (SSL/TLS) |
| Username | the full Fastmail address |
| Password | an **app password** (Settings → Privacy & Security → Integrations → New app password) scoped to **Mail (IMAP/POP/SMTP)** or narrower |

Notes to confirm:

- Fastmail app passwords can be scoped; a read-only-IMAP scope, if offered for
  your plan, is the right one for this kit.
- Folders are plain IMAP folders; `INBOX` is the inbox.
- `setpw.py --provider generic` works (no shape check).
