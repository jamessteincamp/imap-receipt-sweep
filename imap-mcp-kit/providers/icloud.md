# iCloud Mail — the worked example

Everything in [`../INSTALL.md`](../INSTALL.md) was first done against iCloud,
across several Apple IDs. What follows is what is specific to Apple.

## Connection

| | |
|---|---|
| Host | `imap.mail.me.com` |
| Port | `993` (SSL/TLS) |
| Username | the Apple ID email address — see "Which address" below |
| Password | an **app-specific password**, never the Apple ID password |

## App-specific passwords

Generated at <https://account.apple.com> → **Sign-In and Security → App-Specific
Passwords**. Two-factor authentication must be on (it is, for any modern Apple
ID). Give each mailbox/machine its own password so you can revoke one without
touching the others.

Apple shows the password as four groups of four lowercase letters
(`abcd-efgh-ijkl-mnop`); stripped of dashes it is exactly **16 lowercase
letters**. `setpw.py --provider icloud` checks that shape before trying it.

**The paste trap.** Copying the password from Apple's page can pick up hidden
rich-text characters — a clipboard that reads 16 letters may be hundreds of
bytes — and the login fails with no useful error. Either type it, paste it
through a plain-text editor first, or use `setpw.py`, which strips everything
but the letters and confirms the login before writing anything.

## Which address is the username

Older Apple IDs answer to several domains. An ID created as `name@mac.com` may
also be `name@me.com` and `name@icloud.com`, and IMAP is sometimes picky about
which one it accepts. `setpw.py --provider icloud` tries the given form and
then the alternates, and writes back whichever one logged in. Once the
password is clean, the original `@mac.com` form generally works.

Several Apple IDs = several mailboxes: one config file, one cache file, and one
`mcpServers` entry each, all sharing the single installed server.

## What is and isn't visible over IMAP

- **Real folders** (mailboxes you created in Mail or at icloud.com) sync over
  IMAP and can be searched by name. Always pass the folder name explicitly.
- **Smart Mailboxes** in Apple Mail are client-side saved searches — they do
  not exist on the server and are invisible over IMAP. If you want Claude to
  read a curated set of mail, use a real folder.
- **Server-side rules** (icloud.com → Mail → Settings → Rules) run 24/7 and
  can copy or move matching mail into a real folder. They are sender-based and
  take **exact addresses only — no wildcards, no domain matching** — and they
  are forward-only (nothing is applied to existing mail). Useful for building
  a folder Claude can read without giving it the whole account.
- **Flags and colours.** Apple Mail's "flagged" state syncs as the standard
  IMAP `\Flagged` flag. The *colour* of a flag is stored as custom keywords
  `$MailFlagBit0`, `$MailFlagBit1`, `$MailFlagBit2` on the same message:

  | Colour | Keywords alongside `\Flagged` |
  |---|---|
  | Red | *(none)* |
  | Orange | `$MailFlagBit0` |
  | Yellow | `$MailFlagBit1` |
  | Green | `$MailFlagBit0 $MailFlagBit1` |
  | Blue | `$MailFlagBit2` |
  | Purple | `$MailFlagBit0 $MailFlagBit2` |
  | Gray | `$MailFlagBit1 $MailFlagBit2` |

  Purple, red, orange and blue were confirmed against a live iCloud mailbox;
  the rest follow the same three-bit encoding. This is what makes hand-flagged
  mail usable as a ground-truth set for the recall eval (`--apple-colour purple`);
  see [`../../eval/README.md`](../../eval/README.md).

## Server quirks the patches cover

- A long-lived iCloud INBOX (decades of mail) returns a `SEARCH ALL` reply
  larger than Python's default 1 MB line limit — patch 2.
- An empty folder returns `[None]` from `SEARCH`, not an empty string —
  patch 3.
- iCloud's FETCH responses sometimes interleave bare integers and flag atoms
  with the `(envelope, bytes)` tuples; anything parsing them directly should
  tolerate that (the eval script does).

## Legacy `@mac.com` IDs and macOS system Python

Not iCloud-specific, but encountered together: macOS ships Python 3.9, too old
for the server. Install a current Python from python.org and run its
**Install Certificates.command**, or the SSL handshake to `imap.mail.me.com`
fails. Use the versioned interpreter name (`python3.13`) when creating the venv.
