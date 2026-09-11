#!/usr/bin/env python3
"""Put an app-specific password into an imap-readonly-mcp config — safely.

Usage:
    python3 setpw.py ~/imap-mcp/personal.yaml [--provider icloud|generic]

Why this exists: pasting an app password copied from a provider's web page can
carry invisible rich-text characters, so a password that looks right fails to
log in. This helper prompts with hidden input, strips separators and
whitespace, checks the shape (for providers whose format is known), tests a
real IMAP login, and only then writes username + password into the YAML file.

Stdlib only; no YAML library — it rewrites the two lines in place and leaves
the rest of the file untouched. Reads: host, port, username. Writes: username
(possibly a working alternate form), password. Never prints the password.
"""
import argparse
import getpass
import imaplib
import re
import ssl
import sys

# Per-provider knowledge. Add a provider by adding an entry.
PROVIDERS = {
    "generic": {
        "shape": None,                      # no shape check
        "username_alternates": lambda u: [u],
    },
    "icloud": {
        # Apple app-specific passwords are shown as xxxx-xxxx-xxxx-xxxx:
        # 16 lowercase letters once the dashes are stripped.
        "shape": (lambda pw: len(pw) == 16 and pw.isalpha() and pw.islower(),
                  "16 lowercase letters (dashes are stripped)"),
        # Legacy Apple IDs answer to several domains; try each.
        "username_alternates": lambda u: _icloud_forms(u),
    },
}


def _icloud_forms(user):
    local, _, domain = user.partition("@")
    if domain.lower() not in ("mac.com", "me.com", "icloud.com"):
        return [user]
    forms = [user] + [f"{local}@{d}" for d in ("icloud.com", "me.com", "mac.com")]
    return list(dict.fromkeys(forms))       # de-dupe, keep order


def _value(raw):
    """A YAML scalar as the server's config uses it: quoted, or bare with an
    optional trailing `# comment`."""
    raw = raw.strip()
    m = re.match(r"""^(["'])(.*?)\1""", raw)
    if m:
        return m.group(2)
    return re.split(r"\s+#", raw, 1)[0].strip()


def read_field(text, key, default=None):
    m = re.search(rf"(?m)^\s+{key}:\s*(.+?)\s*$", text)
    return _value(m.group(1)) if m else default


def try_login(host, port, user, pw):
    ctx = ssl.create_default_context()
    M = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    try:
        M.login(user, pw)
        M.logout()
        return True, ""
    except Exception as e:                  # imaplib raises plain IMAP4.error
        return False, str(e)[:80]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("config", help="path to the account's YAML config")
    ap.add_argument("--provider", default="generic", choices=sorted(PROVIDERS))
    args = ap.parse_args()
    prov = PROVIDERS[args.provider]

    with open(args.config, encoding="utf-8") as fh:
        text = fh.read()
    host = read_field(text, "host")
    port = int(read_field(text, "port", 993))
    user = read_field(text, "username")
    if not (host and user):
        sys.exit("config needs account.host and account.username filled in first")

    raw = getpass.getpass(f"App password for {user} (hidden): ")
    pw = re.sub(r"[\s\-]", "", raw)
    print(f"entered: {len(pw)} characters after stripping spaces/dashes")
    if prov["shape"]:
        check, expect = prov["shape"]
        if not check(pw):
            sys.exit(f"That doesn't look like a {args.provider} app password "
                     f"(expected {expect}). Re-run and enter it carefully — "
                     f"or type it rather than pasting.")

    ok_user = None
    for u in prov["username_alternates"](user):
        ok, err = try_login(host, port, u, pw)
        print(f"  login as {u}: {'OK' if ok else 'refused — ' + err}")
        if ok:
            ok_user = u
            break
    if not ok_user:
        sys.exit("Shape OK but the server refused the login. Wrong or expired "
                 "app password for this account? Nothing was written.")

    text = re.sub(r"(?m)^(\s+username:).*$", rf"\1 {ok_user}", text, count=1)
    text = re.sub(r"(?m)^(\s+password:).*$", rf'\1 "{pw}"', text, count=1)
    with open(args.config, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"SUCCESS — verified login as {ok_user}; wrote {args.config}")
    print("Now: chmod 600 on that file if you haven't already.")


if __name__ == "__main__":
    main()
