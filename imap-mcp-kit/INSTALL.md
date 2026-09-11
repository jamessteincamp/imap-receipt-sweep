# Installing a read-only IMAP MCP server for Claude

This is the vetted, pinned, patched install of
[AzizMarashly/imap-readonly-mcp](https://github.com/AzizMarashly/imap-readonly-mcp)
(**v0.4.0**, reviewed June 2026) — one MCP server per mailbox, each running
locally over stdio and registered with the Claude desktop app.

It is **strictly read-only**: it can search and read mail and download
attachments, but it cannot send, delete, move, or even mark a message as read.
That is the whole reason this server was chosen. Read
[`../README.md`](../README.md) for the promise the sweep makes on top of it.

Any IMAP mailbox works. iCloud is the worked example throughout; see
[`providers/`](providers/) for provider-specific notes (app passwords, host
names, quirks).

> **What you are trusting.** This is an alpha, single-maintainer project whose
> author describes it as AI-generated. The review found it safe for read-only
> use: every mailbox is opened read-only (`SELECT … readonly` + `BODY.PEEK`),
> it connects only to the IMAP host you configure, via Python's standard
> library, and the base install pulls in no HTTP client or telemetry. Two
> caveats are handled below, not hidden: the **app password sits in a plain-text
> YAML file**, and the server **caches fetched mail in a SQLite file on disk**.

---

## Part A — Python 3.11 or newer (one time)

The server needs Python 3.11+. Check what you have:

```
python3 --version
```

macOS ships an older system Python. If you see 3.9 or 3.10, install the
current 3.x from [python.org](https://www.python.org/downloads/) (macOS
universal installer), then run the **Install Certificates.command** that
ships with it — without it, SSL connections fail. The system `python3` still
points at the old one afterwards; use the versioned name (`python3.13`,
`python3.12`, …) in Part C.

## Part B — Download and pin the reviewed code (one time)

Install from a saved snapshot, not the live repository, so an upstream change
or deletion can never alter your setup.

1. Open <https://github.com/AzizMarashly/imap-readonly-mcp>, click **Code →
   Download ZIP**, and unzip it. You get a folder named `imap-readonly-mcp-main`.
2. Give it a permanent home:

   ```
   mkdir -p ~/imap-mcp
   mv ~/Downloads/imap-readonly-mcp-main ~/imap-mcp/
   ```

   Keep this folder — it is your pinned, reviewed copy. (Any directory name is
   fine; the rest of this guide uses `~/imap-mcp`.)

## Part C — Build, install, patch (one time)

Install into an isolated virtual environment so nothing touches your system
Python. Use the versioned Python name from Part A:

```
cd ~/imap-mcp/imap-readonly-mcp-main
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
.venv/bin/imap-readonly-mcp --help      # prints usage, no errors
```

Then apply the **four fixes** the reviewed version needs. Three are code
patches — run the script from this kit against the venv you just created:

```
python3 /path/to/imap-receipt-sweep/imap-mcp-kit/patches/apply_patches.py ~/imap-mcp/imap-readonly-mcp-main/.venv
```

It is idempotent (safe to re-run) and prints `applied` / `already applied` /
`pattern not found` for each. What they fix:

| Patch | Symptom without it |
|---|---|
| Startup banner → stderr | Claude shows `"[imap-reado"… is not valid JSON` — the banner corrupts the stdio protocol |
| Raise `imaplib._MAXLINE` | A large, old mailbox's `SEARCH` reply exceeds Python's 1 MB line cap: `got more than 1000000 bytes` |
| Guard empty search results | An empty folder crashes the server: `'NoneType' object has no attribute 'decode'` |

The fourth fix is a config setting (`cache_path`), covered in Part D.
See [`patches/README.md`](patches/README.md) for the exact edits.

**Re-apply the patches after any reinstall or upgrade.** The script is safe to
run again.

## Part D — One config file per mailbox (holds the app password)

Copy [`config.example.yaml`](config.example.yaml) to `~/imap-mcp/<account>.yaml`
— one file per mailbox, named for the account (`work.yaml`, `personal.yaml`, …):

```yaml
account:
  protocol: imap
  description: "iCloud - personal"
  host: imap.mail.me.com          # your provider's IMAP host — see providers/
  port: 993                       # SSL is on by default
  username: you@example.com
  password: "APP-SPECIFIC-PASSWORD"
cache_path: /Users/YOU/imap-mcp/personal-cache.sqlite
```

Two things about this file:

- **The password goes in as plain text.** Use an app-specific password, never
  your real account password — it is revocable at the provider without
  touching anything else. The safest way to enter it is the helper in this kit,
  which prompts with hidden input, checks the shape, tests the login, and
  writes the file for you:

  ```
  python3 /path/to/imap-receipt-sweep/imap-mcp-kit/setpw.py ~/imap-mcp/personal.yaml --provider icloud
  ```

  Pasting from a web page can carry invisible rich-text characters that make a
  correct-looking password fail; the helper strips them.

- **`cache_path` must be a real, writable file — one per account.** The
  server's own README suggests `/dev/null` to disable caching, but this
  version crashes at startup with `sqlite3.OperationalError: unable to open
  database file` because it always builds a SQLite database there. So fetched
  mail **is** cached on disk. Keep the cache next to the config, inside the
  locked-down folder, and see "Keeping it safe" below for cleanup.

Then lock the folder down so only your user can read the config and cache:

```
chmod 600 ~/imap-mcp/*.yaml
chmod 700 ~/imap-mcp
```

## Part E — Register with the Claude desktop app (one time)

1. **Settings → Developer → Edit Config** opens `claude_desktop_config.json`.
2. Add one entry per mailbox inside `mcpServers` (absolute paths, no `~`).
   See [`claude_desktop_config.example.json`](claude_desktop_config.example.json):

   ```json
   {
     "mcpServers": {
       "mail-personal": {
         "command": "/Users/YOU/imap-mcp/imap-readonly-mcp-main/.venv/bin/imap-readonly-mcp",
         "args": ["--config", "/Users/YOU/imap-mcp/personal.yaml"]
       }
     }
   }
   ```

3. Save, **quit Claude completely** (⌘Q) and reopen it.
4. The server's tools appear with the entry's name as a prefix:
   `mail_fetch`, `mail_download_attachment`, `mail_debug_list_parts`.
   Try: *"List the folders in my personal mailbox"* or *"Search my personal
   mailbox INBOX for receipts from the last 30 days."*

Run the server over **stdio only** (as above). Never use the Docker/HTTP mode
that binds to `0.0.0.0` — that would expose your mailbox on the network.

## Part F — Add further mailboxes

No second install. For each additional account: another `<account>.yaml` with
its own app password and **its own `cache_path`** (never share a cache between
accounts), `chmod 600` it, add another `mcpServers` entry pointing `--config`
at it (same `command`), quit and reopen Claude.

## Using it

- **Always pass `folder` explicitly** (`INBOX`, or a real folder name). Left
  empty, the server's all-folders heuristic tends to return nothing.
- Keyword search matches anywhere in the message, so narrow receipt queries
  by sender, phrase, or date.
- Only real server-side folders are visible over IMAP. Client-side saved
  searches (Apple Mail's Smart Mailboxes, for instance) are not.

## Keeping it safe over time

- **Don't auto-update.** You are running the snapshot from Part B. To move to
  a newer version, review the diff first, then reinstall deliberately and
  re-apply the patches.
- **The cache holds copies of your mail.** It lives at each `cache_path`,
  inside the `chmod 700` folder. Delete the `*-cache.sqlite` files whenever you
  like — the server rebuilds them — and consider a periodic cleanup if the
  mailbox is sensitive.
- **Revoke, don't rotate.** If a config file is ever exposed, revoke that
  app-specific password at the provider; it stops working instantly. Then
  generate a new one and run `setpw.py` again.
- **Read-only is enforced by the server, not by the prompt.** No tool exists
  to send, delete, move, or flag mail, so no instruction — from you or from a
  message's contents — can do those things through it.
