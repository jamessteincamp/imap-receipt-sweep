# Patches for imap-readonly-mcp v0.4.0

Four fixes were needed to run the reviewed version against a real, large,
long-lived mailbox. Three are one-line source edits applied by
[`apply_patches.py`](apply_patches.py); the fourth is a config setting.
All were found the hard way and are reproduced here so nobody has to find
them again.

Run the script against the venv the server is installed in:

```
python3 apply_patches.py ~/imap-mcp/imap-readonly-mcp-main/.venv
```

It edits the **installed** copy (inside `.venv/lib/python3.x/site-packages/imap_readonly_mcp/`),
not the unzipped source, because that is what actually runs. It is idempotent.
**Re-run it after any reinstall or upgrade.**

## 1. Startup banner → stderr — `server.py`

`main()` prints `[imap-readonly-mcp] Starting stdio transport` to **stdout**.
In stdio transport, stdout *is* the protocol channel, so the first thing
Claude receives is not JSON and the server is marked failed:
`"[imap-reado"... is not valid JSON`.

```python
# before
print("[imap-readonly-mcp] Starting stdio transport", flush=True)
# after
print("[imap-readonly-mcp] Starting stdio transport", flush=True, file=__import__("sys").stderr)
```

## 2. Raise the IMAP line cap — `connectors/imap.py`

Python's `imaplib` refuses any single response line over 1 MB. A mailbox with
twenty years of mail returns a `SEARCH ALL` result longer than that, and the
server's unbounded "latest messages" path triggers it:
`imaplib.IMAP4.error: got more than 1000000 bytes`. Filtered searches (sender,
keyword, date) return short lists and never hit this — only the unbounded one
does — but it is the one the server runs when no filter is given.

```python
# before
import imaplib
# after
import imaplib; imaplib._MAXLINE = 100000000
```

## 3. Guard an empty folder — `connectors/imap.py`, `_search_uids`

An IMAP `SEARCH` on an empty folder returns `[None]`, not `[b""]`, and the
server crashes with `'NoneType' object has no attribute 'decode'`. A newly
created folder with nothing in it yet is the obvious case.

```python
# before
raw_uids = data[0].decode("ascii", errors="ignore")
# after
raw_uids = (data[0] or b"").decode("ascii", errors="ignore")
```

## 4. `cache_path` must be a real file — config, not code

The project README suggests `cache_path: /dev/null` to disable the body
cache. This version always opens a SQLite database at that path and crashes at
startup: `sqlite3.OperationalError: unable to open database file`. Point
`cache_path` at a real, writable file, one per account, inside the
`chmod 700` config folder — and know that fetched mail is therefore cached on
disk. See [`../INSTALL.md`](../INSTALL.md) Part D and "Keeping it safe".

## Other versions

The patterns above are exact for v0.4.0. On another version the script reports
`pattern not found` rather than guessing; check whether upstream has fixed the
issue, and if not, apply the equivalent edit by hand.
