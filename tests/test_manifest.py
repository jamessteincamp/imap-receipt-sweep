"""Tests for skill/imap-receipt-sweep/scripts/manifest.py, through its interface.

    python3 -m unittest discover tests
"""
import base64
import datetime as dt
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skill", "imap-receipt-sweep", "scripts")
FIXTURES = os.path.join(ROOT, "eval", "fixtures")
sys.path.insert(0, SCRIPTS)

import eml_to_json                     # noqa: E402  the fixture adapter
import manifest                        # noqa: E402
from manifest import ManifestError     # noqa: E402

RUN = "2026-11-14T10:00:00"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def meta(**over):
    m = {"message_id": "<a1@northwind.example>", "account": "personal",
         "date": "2026-09-05", "from": "receipts@northwind.example",
         "subject": "Your Northwind Stationery receipt — order #NW-2231",
         "kind": "receipt", "amounts": ["42.17"], "vendor": "Northwind Stationery",
         "source_id": "mail://SU5CT1g/1042"}
    m.update(over)
    return m


class InboxCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.inbox = os.path.join(self._tmp.name, "inbox")
        self.work = self._tmp.name

    def tearDown(self):
        for root, dirs, files in os.walk(self._tmp.name):
            for f in files + dirs:
                os.chmod(os.path.join(root, f), 0o755)
        self._tmp.cleanup()

    def content(self, data, name="content"):
        path = os.path.join(self.work, name)
        with open(path, "wb" if isinstance(data, bytes) else "w") as fh:
            fh.write(data)
        return path

    def html(self):
        return self.content("<html><body><p>Total $42.17</p></body></html>", "body.html")

    def files(self):
        return sorted(f for f in os.listdir(self.inbox) if not f.startswith(".")) if os.path.isdir(self.inbox) else []

    def lines(self):
        return manifest.read_lines(self.inbox)


class FileNames(unittest.TestCase):
    def test_slug_rule(self):
        cases = [
            # cut at 40 lands on a dash, which is trimmed again
            (("2026-09-05", "receipts@northwind.example", "Your Northwind Stationery receipt — order #NW-2231"),
             "2026-09-05_northwind_your-northwind-stationery-receipt-order"),
            (("2026-09-05", "billing@contoso-cloud.example", "Invoice #1001 for September"),
             "2026-09-05_contoso-cloud_invoice-1001-for-september"),
            (("2026-09-05", "orders@email.shop.example", "Hi"), "2026-09-05_shop_hi"),
            (("2026-09-05", "billing@shop.co.uk", "Receipt"), "2026-09-05_shop_receipt"),
            (("2026-09-05", "x@example.com", "!!!"), "2026-09-05_example_no-subject"),
        ]
        for args, want in cases:
            self.assertEqual(manifest.file_stem(*args), want, args)

    def test_account_name(self):
        for label in ("personal", "mail-personal", "icloud-personal", "mcp__mail-personal__mail_fetch"):
            self.assertEqual(manifest.account_name(label), "personal", label)


class Save(InboxCase):
    def test_html_keep_writes_file_then_line(self):
        out = manifest.save(self.inbox, meta(), self.html(), run=RUN)
        self.assertEqual(out["file"], "2026-09-05_northwind_your-northwind-stationery-receipt-order.html")
        self.assertEqual(self.files(), [out["file"]])
        [line] = self.lines()
        self.assertEqual(line, out["line"])
        self.assertEqual(line["kind"], "receipt")
        self.assertEqual(out["cap_remaining"], manifest.CAP - 1)
        self.assertTrue(manifest.status(self.inbox)["manifest_valid"])

    def test_mechanical_formats_are_normalised(self):
        m = meta(message_id=["a1@northwind.example"], account="mcp__mail-personal__mail_fetch",
                 date="Sat, 05 Sep 2026 23:30:00 -0700", amounts=["$1,234.5", "−19", "3.00"])
        m["from"] = [{"name": "Northwind", "email": "receipts@northwind.example"}]
        out = manifest.save(self.inbox, m, self.html(), run=RUN)
        line = out["line"]
        self.assertEqual(line["message_id"], "<a1@northwind.example>")
        self.assertEqual(line["account"], "personal")
        self.assertEqual(line["date"], "2026-09-05")            # the message's own offset, not UTC
        self.assertEqual(line["from"], "receipts@northwind.example")
        self.assertEqual(line["amounts"], ["1234.50", "-19.00", "3.00"])

    def test_pdf_from_raw_base64_json_and_data_uri(self):
        b64 = base64.b64encode(PDF).decode()
        sources = [
            PDF,
            b64,
            json.dumps([{"type": "text", "text": json.dumps({"filename": "inv.pdf", "data": b64})}]),
            "data:application/pdf;base64," + b64,
        ]
        for i, src in enumerate(sources):
            out = manifest.save(self.inbox, meta(message_id=f"<p{i}@x.example>"), self.content(src, f"c{i}"), run=RUN)
            self.assertTrue(out["file"].endswith(".pdf"), out["file"])
            with open(os.path.join(self.inbox, out["file"]), "rb") as fh:
                self.assertEqual(fh.read(), PDF)

    def test_html_under_body_text_is_saved_as_html_plain_text_as_txt(self):
        a = manifest.save(self.inbox, meta(message_id="<h@x>"), self.content("<p>Paid $5.00</p>"), run=RUN)
        b = manifest.save(self.inbox, meta(message_id="<t@x>"), self.content("Paid $5.00", "t"), run=RUN)
        self.assertTrue(a["file"].endswith(".html"))
        self.assertTrue(b["file"].endswith(".txt"))

    def test_collision_never_overwrites(self):
        os.makedirs(self.inbox)
        mine = os.path.join(self.inbox, "2026-09-05_northwind_your-northwind-stationery-receipt-order.html")
        with open(mine, "w") as fh:
            fh.write("the user's own file")
        out = manifest.save(self.inbox, meta(), self.html(), run=RUN)
        self.assertTrue(out["file"].endswith("-order-2.html"))
        with open(mine) as fh:
            self.assertEqual(fh.read(), "the user's own file")

    def test_name_held_by_a_manifest_line_is_not_reused_after_the_file_moves(self):
        first = manifest.save(self.inbox, meta(), self.html(), run=RUN)["file"]
        os.unlink(os.path.join(self.inbox, first))
        second = manifest.save(self.inbox, meta(message_id="<a2@x>"), self.html(), run=RUN)["file"]
        self.assertNotEqual(first, second)

    def test_duplicate_message_id_from_another_account_writes_nothing(self):
        manifest.save(self.inbox, meta(), self.html(), run=RUN)
        with self.assertRaises(ManifestError) as cm:
            manifest.save(self.inbox, meta(account="work", source_id="mail://W/1"), self.html(), run=RUN)
        self.assertEqual(cm.exception.code, "duplicate")
        self.assertEqual(cm.exception.existing["account"], "personal")
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(len(self.lines()), 1)

    def test_invalid_input_writes_nothing(self):
        bad = [meta(kind="skip"), meta(amounts=["twelve"]), meta(renews_on="1 October"),
               meta(file="x.html"), meta(colour="blue"), meta(subject=""), meta(**{"from": "nobody"})]
        for m in bad:
            with self.assertRaises(ManifestError, msg=m) as cm:
                manifest.save(self.inbox, m, self.html(), run=RUN)
            self.assertEqual(cm.exception.code, "invalid", m)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.lines(), [])

    def test_run_token_is_required(self):
        with self.assertRaises(ManifestError) as cm:
            manifest.save(self.inbox, meta(), self.html(), run="")
        self.assertEqual(cm.exception.code, "invalid")

    def test_cap_per_account_per_run(self):
        body = self.html()
        for i in range(manifest.CAP):
            manifest.save(self.inbox, meta(message_id=f"<m{i}@x>"), body, run=RUN)
        with self.assertRaises(ManifestError) as cm:
            manifest.save(self.inbox, meta(message_id="<over@x>"), body, run=RUN)
        self.assertEqual(cm.exception.code, "cap_reached")
        # another account, and a later run, are not capped
        manifest.save(self.inbox, meta(message_id="<w@x>", account="work"), body, run=RUN)
        manifest.save(self.inbox, meta(message_id="<next@x>"), body, run="2099-01-01T00:00:00",
                      now="2099-01-01T00:00:01")
        self.assertEqual(len(self.files()), manifest.CAP + 2)

    def test_unwritable_manifest_leaves_no_orphan_file(self):
        manifest.save(self.inbox, meta(), self.html(), run=RUN)
        path = os.path.join(self.inbox, manifest.MANIFEST_NAME)
        os.chmod(path, stat.S_IRUSR)
        with self.assertRaises(ManifestError) as cm:
            manifest.save(self.inbox, meta(message_id="<a2@x>"), self.html(), run=RUN)
        self.assertEqual(cm.exception.code, "io")
        self.assertEqual(len(self.files()), 1)

    def test_failed_append_removes_the_file_it_wrote(self):
        # fault injection at the internal seam: the file is written, the append fails
        from unittest import mock
        with mock.patch.object(manifest, "_append", side_effect=OSError("disk full")):
            with self.assertRaises(ManifestError) as cm:
                manifest.save(self.inbox, meta(), self.html(), run=RUN)
        self.assertEqual(cm.exception.code, "io")
        self.assertEqual(os.listdir(self.inbox), [manifest.MANIFEST_NAME])   # no artifact, no .part

    def test_missing_content_is_io(self):
        with self.assertRaises(ManifestError) as cm:
            manifest.save(self.inbox, meta(), os.path.join(self.work, "nope"), run=RUN)
        self.assertEqual(cm.exception.code, "io")


class Status(InboxCase):
    TODAY = dt.date(2026, 11, 14)

    def test_first_run_window(self):
        s = manifest.status(self.inbox, today=self.TODAY)
        self.assertTrue(s["manifest_valid"])
        self.assertEqual(s["window"], {"start": "2026-10-15", "basis": "today-minus-30"})
        self.assertEqual(s["lines"], 0)
        self.assertTrue(manifest._is_datetime(s["run"]))

    def test_window_from_latest_date_and_override(self):
        manifest.save(self.inbox, meta(date="2026-11-10"), self.html(), run=RUN)
        manifest.save(self.inbox, meta(message_id="<b@x>", date="2026-11-01"), self.html(), run=RUN)
        self.assertEqual(manifest.status(self.inbox, today=self.TODAY)["window"],
                         {"start": "2026-11-08", "basis": "latest-date-minus-2"})
        self.assertEqual(manifest.status(self.inbox, since="2026-08-01")["window"],
                         {"start": "2026-08-01", "basis": "override"})

    def test_seen_source_ids_by_account_within_the_window(self):
        manifest.save(self.inbox, meta(date="2026-11-10", source_id="mail://P/9"), self.html(), run=RUN)
        manifest.save(self.inbox, meta(message_id="<w@x>", account="work", date="2026-11-09",
                                       source_id="mail://W/3"), self.html(), run=RUN)
        manifest.save(self.inbox, meta(message_id="<old@x>", date="2026-01-01",
                                       source_id="mail://P/1"), self.html(), run=RUN)
        seen = manifest.status(self.inbox)["seen"]["source_ids"]
        self.assertEqual(seen, {"personal": ["mail://P/9"], "work": ["mail://W/3"]})

    def test_run_summary(self):
        manifest.save(self.inbox, meta(message_id="<old@x>"), self.html(), run=RUN, now="2026-11-01T09:00:00")
        manifest.save(self.inbox, meta(notes="amount unclear"), self.html(), run=RUN, now="2026-11-14T10:00:05")
        s = manifest.status(self.inbox, run=RUN)
        self.assertEqual(s["run"], RUN)
        self.assertEqual(s["this_run"]["personal"]["saved"], 1)
        self.assertEqual(s["this_run"]["personal"]["kinds"], {"receipt": 1})
        self.assertEqual(len(s["this_run"]["personal"]["notes"]), 1)

    def test_problems_are_reported_not_fatal(self):
        manifest.save(self.inbox, meta(), self.html(), run=RUN)
        with open(os.path.join(self.inbox, manifest.MANIFEST_NAME), "a") as fh:
            fh.write("not json\n")
            fh.write(json.dumps(manifest.read_lines(self.inbox)[0]) + "\n")      # duplicate line
            fh.write(json.dumps({**manifest.read_lines(self.inbox)[0], "message_id": "<z@x>",
                                 "file": "gone.html", "amounts": ["1.5"]}) + "\n")
        s = manifest.status(self.inbox)
        self.assertFalse(s["manifest_valid"])
        msgs = " | ".join(e["message"] for e in s["errors"])
        for want in ("not JSON", "duplicate message_id", "file not found", "does not match"):
            self.assertIn(want, msgs)
        # and saving still works past a broken line
        manifest.save(self.inbox, meta(message_id="<after@x>"), self.html(), run=RUN)


class Cli(InboxCase):
    def run_cli(self, *args, stdin=None):
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "manifest.py"), *args],
                           input=stdin, capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    def test_status_then_save_then_duplicate(self):
        code, s = self.run_cli("status", self.inbox)
        self.assertEqual(code, 0)
        code, out = self.run_cli("save", self.inbox, "--run", s["run"], "--content", self.html(),
                                 stdin=json.dumps(meta()))
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        code, out = self.run_cli("save", self.inbox, "--run", s["run"], "--content", self.html(),
                                 stdin=json.dumps(meta(account="work")))
        self.assertEqual((code, out["error"]), (3, "duplicate"))
        code, out = self.run_cli("save", self.inbox, "--run", s["run"], "--content", self.html(),
                                 stdin="{not json")
        self.assertEqual((code, out["error"]), (2, "invalid"))


class Fixtures(InboxCase):
    """The whole fixture path minus the model: judgement from expected.jsonl,
    facts from the fixture adapter, saved through manifest.py, scored by
    eval/check_run.py."""

    def test_check_run_passes(self):
        with open(os.path.join(FIXTURES, "expected.jsonl")) as fh:
            expected = [json.loads(l) for l in fh if l.strip()]
        run = manifest.status(self.inbox)["run"]
        for e in expected:
            if e["kind"] == "skip":
                continue
            path = os.path.join(FIXTURES, e["file"])
            account = os.path.basename(os.path.dirname(path))
            rec = eml_to_json.record(path, account, full=True)
            m = {"message_id": rec["headers"]["Message-ID"], "account": account, "date": rec["date"],
                 "from": rec["from"], "subject": rec["subject"],
                 "kind": "receipt" if e["kind"] == "duplicate" else e["kind"],
                 "amounts": e.get("amounts_include", []), "vendor": e.get("vendor_contains"),
                 "renews_on": e.get("renews_on"), "source_id": rec["id"]}
            if e.get("saved_ext") == ".pdf":
                content = os.path.join(self.work, "att.pdf")
                eml_to_json.write_attachment(path, 0, content)
            else:
                content = self.content(rec.get("body_html") or rec.get("body_text"), "body")
            try:
                manifest.save(self.inbox, m, content, run=run)
            except ManifestError as err:
                self.assertEqual((e["kind"], err.code), ("duplicate", "duplicate"))
        p = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "check_run.py"), self.inbox],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)


if __name__ == "__main__":
    unittest.main()
