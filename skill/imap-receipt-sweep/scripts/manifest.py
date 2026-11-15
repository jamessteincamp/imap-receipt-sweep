#!/usr/bin/env python3
"""The sweep's manifest: read the state for a run, and save one keep.

    python3 manifest.py status <inbox> [--run R] [--since YYYY-MM-DD]
    python3 manifest.py save   <inbox> --run R --content PATH [--ext EXT] [--meta PATH] < meta.json

status  Read-only. Prints one JSON object: whether the manifest is valid (and
        each problem), the window to search, a fresh run token, and the
        source_ids already swept, by account. With --run R it adds what run R
        saved, per account, for the report. Exit 0 valid, 1 invalid lines.

save    Files one keep. The meta JSON (stdin, or --meta PATH) carries the
        message's facts and your judgement:
            message_id, account, date, from, subject, kind,
            amounts?, vendor?, renews_on?, source_id?, notes?
        --content is the file holding what to save: raw bytes, Base64 text, or
        a JSON tool result with the Base64/HTML inside. The extension is
        detected (PDF, PNG, JPEG, HEIC, HTML, text); --ext overrides.
        save names the file, never overwrites, refuses a Message-ID the
        manifest already has from any account, enforces the per-account cap
        for run R, writes the file, then appends the line.

        Exit 0 saved · 2 invalid · 3 duplicate · 4 cap reached · 5 I/O error.
        On 2–5 nothing was written. Every outcome is one JSON object on stdout.

A host app that rewrites the manifest (to re-point a line whose file it moved)
should hold an exclusive flock on the manifest file while it reads and
rewrites, and swap the new copy in with a rename. save takes the same lock and
re-checks it after a swap, so neither side loses the other's change.

Stdlib only. The schema (../manifest.schema.json) is the single source of the
line format; this module reads it at runtime.
"""
import argparse
import base64
import binascii
import datetime as dt
import email.utils
import json
import os
import re
import sys
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

try:
    import fcntl
except ImportError:                       # Windows: no advisory lock
    fcntl = None

MANIFEST_NAME = ".sweep-manifest.jsonl"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "manifest.schema.json")
CAP = 50                                  # saves per account per run
OVERLAP_DAYS = 2                          # window = latest date − 2 days
FIRST_RUN_DAYS = 30                       # window with no manifest
SEEN_MARGIN_DAYS = 7                      # source_ids reported this far before the window

EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "heic", "html", "txt"}
COMPUTED = {"file", "swept_at"}           # save writes these; meta may not
LINE_ORDER = ["message_id", "account", "date", "from", "subject", "kind", "file",
              "amounts", "vendor", "renews_on", "swept_at", "source_id", "notes"]
# Two-label public suffixes, so billing@shop.co.uk slugs as "shop", not "co".
TWO_LABEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "com.au", "net.au",
                      "org.au", "co.nz", "co.jp", "co.za", "co.in", "com.br", "com.mx",
                      "com.sg", "com.hk", "co.kr"}


class ManifestError(Exception):
    """A save that wrote nothing. code ∈ invalid | duplicate | cap_reached | io."""
    EXIT = {"invalid": 2, "duplicate": 3, "cap_reached": 4, "io": 5}

    def __init__(self, code, message, field=None, existing=None):
        super().__init__(message)
        self.code, self.message, self.field, self.existing = code, message, field, existing

    def as_dict(self):
        return {"ok": False, "error": self.code, "field": self.field,
                "message": self.message, "existing": self.existing}


# ---------------------------------------------------------------- the schema

def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


_TYPES = {"string": str, "array": list, "object": dict, "boolean": bool,
          "null": type(None), "integer": int, "number": (int, float)}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check(value, schema, path, errors):
    """The subset of JSON Schema the manifest schema uses."""
    types = schema.get("type")
    if types:
        types = types if isinstance(types, list) else [types]
        if not any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number")
                   and isinstance(value, bool)) for t in types):
            errors.append(f"{path}: expected {' or '.join(types)}, got {value!r}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        fmt = schema.get("format")
        if fmt == "date" and not _is_date(value):
            errors.append(f"{path}: {value!r} is not a YYYY-MM-DD date")
        if fmt == "date-time" and not _is_datetime(value):
            errors.append(f"{path}: {value!r} is not an ISO 8601 date-time")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errors.append(f"{k}: missing")
        for k, v in value.items():
            if k in props:
                _check(v, props[k], k, errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{k}: unknown key")


def _is_date(s):
    try:
        return bool(_DATE.match(s)) and bool(dt.date.fromisoformat(s))
    except ValueError:
        return False


def _is_datetime(s):
    try:
        dt.datetime.fromisoformat(s)
        return "T" in s
    except ValueError:
        return False


def validate_line(line):
    """Problems with one manifest line against the schema; [] when valid."""
    errors = []
    _check(line, _schema(), "line", errors)
    return errors


# ---------------------------------------------------------------- reading

def read_lines(inbox):
    """Every line of the manifest that parses as a JSON object, in order."""
    return [r for _, r, _ in _scan(inbox) if r is not None]


def _scan(inbox):
    """Yield (line_number, row_or_None, parse_error_or_None)."""
    path = os.path.join(inbox, MANIFEST_NAME)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as e:
                yield n, None, f"not JSON ({e.msg})"
                continue
            if not isinstance(row, dict):
                yield n, None, "not a JSON object"
                continue
            yield n, row, None


def _problems(inbox):
    out, seen = [], set()
    for n, row, err in _scan(inbox):
        if err:
            out.append({"line": n, "message": err})
            continue
        for e in validate_line(row):
            out.append({"line": n, "message": e})
        f = row.get("file")
        if isinstance(f, str) and f and not os.path.exists(os.path.join(inbox, f)):
            out.append({"line": n, "message": f"file not found in inbox: {f}"})
        mid = row.get("message_id")
        if mid in seen:
            out.append({"line": n, "message": f"duplicate message_id {mid}"})
        seen.add(mid)
    return out


# ---------------------------------------------------------------- status

def status(inbox, run=None, since=None, *, today=None):
    """The state a run starts from (or, with run=R, what run R saved)."""
    inbox = _abs(inbox)
    today = today or dt.date.today()
    rows = read_lines(inbox)
    problems = _problems(inbox)
    dates = [dt.date.fromisoformat(r["date"]) for r in rows
             if isinstance(r.get("date"), str) and _is_date(r["date"])]
    if since:
        start, basis = dt.date.fromisoformat(since), "override"
    elif dates:
        start, basis = max(dates) - dt.timedelta(days=OVERLAP_DAYS), "latest-date-minus-2"
    else:
        start, basis = today - dt.timedelta(days=FIRST_RUN_DAYS), "today-minus-30"
    cutoff = (start - dt.timedelta(days=SEEN_MARGIN_DAYS)).isoformat()
    source_ids = {}
    for r in rows:
        if r.get("source_id") and str(r.get("date", "")) >= cutoff:
            source_ids.setdefault(r.get("account", ""), []).append(r["source_id"])
    out = {
        "manifest_valid": not problems,
        "errors": problems,
        "lines": len(rows),
        "window": {"start": start.isoformat(), "basis": basis},
        "run": run or _now(),
        "seen": {"source_ids": source_ids},
    }
    if run:
        this_run = {}
        for r in rows:
            if str(r.get("swept_at", "")) >= run:
                a = this_run.setdefault(r.get("account", ""), {"saved": 0, "kinds": {}, "files": [], "notes": []})
                a["saved"] += 1
                a["kinds"][r.get("kind")] = a["kinds"].get(r.get("kind"), 0) + 1
                a["files"].append(r.get("file"))
                if r.get("notes"):
                    a["notes"].append({"file": r.get("file"), "notes": r["notes"]})
        out["this_run"] = this_run
    return out


# ---------------------------------------------------------------- save

def save(inbox, meta, content, *, run, ext=None, now=None):
    """File one keep: the artifact first, then its manifest line.

    Returns {"ok": True, "file", "line", "cap_remaining"}; raises ManifestError
    (having written nothing) on invalid input, a duplicate, the cap, or I/O.
    """
    inbox = _abs(inbox)
    if not (isinstance(run, str) and _is_datetime(run)):
        raise ManifestError("invalid", f"run must be the ISO date-time token status printed, got {run!r}", "run")
    line = _normalise(meta)
    data, ext = _artifact(content, ext)
    line["swept_at"] = now or _now()
    line["file"] = file_stem(line["date"], line["from"], line["subject"]) + "." + ext
    errors = validate_line(_ordered(line))
    if errors:
        raise ManifestError("invalid", "; ".join(errors), errors[0].split(":")[0])
    try:
        os.makedirs(inbox, exist_ok=True)
        lock = _lock(inbox)
        lock.__enter__()
    except OSError as e:
        raise ManifestError("io", f"cannot open the manifest in {inbox}: {e}")
    try:
        rows = read_lines(inbox)
        for r in rows:
            if r.get("message_id") == line["message_id"]:
                raise ManifestError("duplicate", f"{line['message_id']} is already in the manifest",
                                    "message_id", {"account": r.get("account"), "file": r.get("file")})
        saved = sum(1 for r in rows if r.get("account") == line["account"]
                    and str(r.get("swept_at", "")) >= run)
        if saved >= CAP:
            raise ManifestError("cap_reached", f"{CAP} saves for account {line['account']} in run {run}",
                                "account")
        taken = {r.get("file") for r in rows}
        line["file"] = _claim(inbox, line["file"][: -len(ext) - 1], ext, data, taken)
        try:
            _append(inbox, _ordered(line))
        except OSError as e:
            os.unlink(os.path.join(inbox, line["file"]))
            raise ManifestError("io", f"could not append to the manifest ({e}); the file was removed")
    finally:
        lock.__exit__(None, None, None)
    return {"ok": True, "file": line["file"], "line": _ordered(line), "cap_remaining": CAP - saved - 1}


def _normalise(meta):
    """Meta → a line, with mechanical formats fixed and judgement left alone."""
    if not isinstance(meta, dict):
        raise ManifestError("invalid", "meta must be a JSON object")
    bad = set(meta) & COMPUTED
    if bad:
        raise ManifestError("invalid", f"{sorted(bad)} are computed by save; leave them out", sorted(bad)[0])
    allowed = set(LINE_ORDER) - COMPUTED
    unknown = set(meta) - allowed
    if unknown:
        raise ManifestError("invalid", f"unknown key(s) {sorted(unknown)}", sorted(unknown)[0])
    for k in ("message_id", "account", "date", "from", "subject", "kind"):
        if meta.get(k) in (None, "", []):
            raise ManifestError("invalid", f"{k} is required", k)
    line = {
        "message_id": _message_id(meta["message_id"]),
        "account": account_name(str(meta["account"])),
        "date": _date(meta["date"]),
        "from": _address(meta["from"]),
        "subject": str(meta["subject"]),
        "kind": meta["kind"],
        "amounts": [_amount(a) for a in (meta.get("amounts") or [])],
        "vendor": meta.get("vendor") or None,
        "renews_on": meta.get("renews_on") or None,
    }
    line["amounts"].sort(key=lambda a: abs(Decimal(a)), reverse=True)
    for k in ("source_id", "notes"):
        if meta.get(k):
            line[k] = meta[k]
    return line


def account_name(label):
    """The account as the manifest records it: the server config's stem.
    'mcp__mail-personal__mail_fetch', 'mail-personal', 'icloud-personal' → 'personal'."""
    s = label.strip()
    if s.startswith("mcp__"):
        s = s[len("mcp__"):].split("__", 1)[0]
    for prefix in ("mail-", "icloud-"):
        if s.startswith(prefix) and len(s) > len(prefix):
            return s[len(prefix):]
    return s


def _message_id(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    v = str(v).strip()
    if v and not v.startswith("<"):
        v = f"<{v}>"
    return v


def _date(v):
    """YYYY-MM-DD as the message states it: ISO strings keep their own date,
    RFC 2822 dates are read in their own offset."""
    s = str(v).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    try:
        return email.utils.parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        raise ManifestError("invalid", f"date {v!r} is neither ISO nor an RFC 2822 date", "date")


def _address(v):
    """The bare addr-spec from 'Name <a@b>', 'a@b', or mail_fetch's [{name, email}]."""
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("email", "")
    addr = email.utils.parseaddr(str(v))[1]
    if "@" not in addr:
        raise ManifestError("invalid", f"from {v!r} has no address", "from")
    return addr


def _amount(v):
    s = re.sub(r"[^\d.\-]", "", str(v).replace("−", "-"))
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ManifestError("invalid", f"amount {v!r} is not a number", "amounts")
    return f"{d.quantize(Decimal('0.01'))}"


def file_stem(date, sender, subject):
    """YYYY-MM-DD_<sender-slug>_<subject-slug>, without extension or -N suffix."""
    domain = sender.rsplit("@", 1)[-1].lower().strip(".")
    labels = [l for l in domain.split(".") if l]
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_LABEL_SUFFIXES:
        label = labels[-3]
    elif len(labels) >= 2:
        label = labels[-2]
    else:
        label = labels[0] if labels else ""
    sender_slug = _slug(label) or "unknown"
    subject_slug = _slug(subject)[:40].strip("-") or "no-subject"
    return f"{date}_{sender_slug}_{subject_slug}"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------- content

_MAGIC = [(b"%PDF-", "pdf"), (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg")]
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
_B64 = re.compile(rb"^[A-Za-z0-9+/=_\-\s]+$")


def _sniff(data):
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "heic"
    return None


def _artifact(path, ext=None):
    """The bytes to save and their extension, from whatever the file holds."""
    if ext is not None:
        ext = ext.lower().lstrip(".")
        if ext not in EXTENSIONS:
            raise ManifestError("invalid", f"ext {ext!r} not one of {sorted(EXTENSIONS)}", "ext")
    try:
        with open(os.path.expanduser(path), "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise ManifestError("io", f"cannot read content {path}: {e}", "content")
    data, found = _unwrap(data, depth=0)
    if not data.strip():
        raise ManifestError("invalid", f"content {path} is empty", "content")
    return data, ext or found


def _unwrap(data, depth):
    """Peel Base64, data: URIs and JSON wrappers until bytes with a type appear."""
    kind = _sniff(data)
    if kind:
        return data, kind
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, "txt"
    stripped = text.strip()
    if depth < 4 and stripped[:1] in "{[":
        try:
            inner = _longest_string(json.loads(stripped))
        except json.JSONDecodeError:
            inner = None
        if inner:
            return _unwrap(inner.encode("utf-8"), depth + 1)
    m = re.match(r"^data:[\w/+.-]+;base64,", stripped)
    if m:
        stripped = stripped[m.end():]
    if depth < 4 and len(stripped) >= 16 and _B64.match(stripped.encode("ascii", "ignore") or b"!"):
        try:
            raw = base64.b64decode("".join(stripped.split()), altchars=b"-_" if "-" in stripped or "_" in stripped else None, validate=True)
        except (binascii.Error, ValueError):
            raw = None
        if raw and _sniff(raw):
            return raw, _sniff(raw)
    looks_html = stripped.startswith("<") or re.search(r"(?i)<(html|body|table|div|p|br)\b", stripped)
    return data, "html" if looks_html else "txt"


def _longest_string(node):
    best = ""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, str):
            if len(n) > len(best):
                best = n
        elif isinstance(n, dict):
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return best


# ---------------------------------------------------------------- writing

@contextmanager
def _lock(inbox):
    """Hold an exclusive flock on the manifest itself for a read-then-append.

    A host app may rewrite the manifest (to re-point a moved file's line) by writing a
    temp file and renaming it over this one, holding the same flock on the file it
    replaces. A `save` that was waiting then wakes holding a lock on the old,
    unlinked file, which locks out nobody. So after taking the lock, check that the
    name still leads to the locked file; if it doesn't, take the lock again on the
    file that is there now.
    """
    path = os.path.join(inbox, MANIFEST_NAME)
    while True:
        fh = open(path, "a+", encoding="utf-8")
        try:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX)
                held = os.fstat(fh.fileno())
                try:
                    now = os.stat(path)
                except FileNotFoundError:
                    now = None
                if now is None or (now.st_dev, now.st_ino) != (held.st_dev, held.st_ino):
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    continue                  # replaced while we waited: lock the new one
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(fh, fcntl.LOCK_UN)
            return
        finally:
            fh.close()


def _claim(inbox, stem, ext, data, taken):
    """Write data under the first free name stem.ext, stem-2.ext, …; never overwrite."""
    part = os.path.join(inbox, f".{stem}.{os.getpid()}.part")
    with open(part, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        n = 1
        while True:
            name = f"{stem}.{ext}" if n == 1 else f"{stem}-{n}.{ext}"
            n += 1
            if name in taken:
                continue
            target = os.path.join(inbox, name)
            try:
                os.link(part, target)             # fails if target exists
                return name
            except FileExistsError:
                continue
            except OSError:                        # no hard links on this filesystem
                try:
                    with open(target, "xb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    return name
                except FileExistsError:
                    continue
    finally:
        os.unlink(part)


def _append(inbox, line):
    path = os.path.join(inbox, MANIFEST_NAME)
    with open(path, "ab") as fh:
        if fh.tell() > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != b"\n":
                    fh.write(b"\n")
        fh.write((json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def _ordered(line):
    return {k: line[k] for k in LINE_ORDER if k in line}


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _abs(p):
    return os.path.abspath(os.path.expanduser(p))


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="The sweep's manifest: status and save.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="validate, window, run token, seen source_ids")
    st.add_argument("inbox")
    st.add_argument("--run", help="summarise what this run saved")
    st.add_argument("--since", help="YYYY-MM-DD; overrides the window rule")
    st.add_argument("--today", help=argparse.SUPPRESS)
    sv = sub.add_parser("save", help="file one keep: artifact, then manifest line")
    sv.add_argument("inbox")
    sv.add_argument("--run", required=True, help="the run token status printed")
    sv.add_argument("--content", required=True, help="file holding the bytes (raw, Base64, or JSON-wrapped)")
    sv.add_argument("--ext", help="force the extension: " + " ".join(sorted(EXTENSIONS)))
    sv.add_argument("--meta", help="meta JSON file; default stdin")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        today = dt.date.fromisoformat(a.today) if a.today else None
        out = status(a.inbox, run=a.run, since=a.since, today=today)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out["manifest_valid"] else 1

    try:
        try:
            raw = open(a.meta, encoding="utf-8").read() if a.meta else sys.stdin.read()
            meta = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            raise ManifestError("invalid", f"meta is not readable JSON: {e}", "meta")
        out = save(a.inbox, meta, a.content, run=a.run, ext=a.ext)
    except ManifestError as e:
        print(json.dumps(e.as_dict(), ensure_ascii=False))
        return ManifestError.EXIT[e.code]
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
