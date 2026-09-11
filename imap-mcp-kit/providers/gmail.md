# Gmail — stub, untested

Not yet verified with this kit. What is known; contributions welcome.

| | |
|---|---|
| Host | `imap.gmail.com` |
| Port | `993` (SSL/TLS) |
| Username | the full Gmail address |
| Password | an **App Password** (Google Account → Security → 2-Step Verification → App passwords); requires 2-Step Verification to be on |

Notes to confirm:

- IMAP must be enabled in Gmail settings (Settings → See all settings →
  Forwarding and POP/IMAP) on older accounts; newer accounts have it on.
- Gmail labels appear as IMAP folders. `INBOX` is the inbox; the complete
  archive is `[Gmail]/All Mail`. Searching `INBOX` alone misses archived mail.
- Google's IMAP `SEARCH` supports the `X-GM-RAW` extension for Gmail-syntax
  queries; the server in this kit does not use it.
- `setpw.py --provider generic` works (no shape check); add an entry to
  `PROVIDERS` in `setpw.py` if Google's app-password format (16 letters shown
  in groups of four) turns out to be stable enough to check.
