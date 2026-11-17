"""Behavior checks for the Pokemon GO store reader add-on (fake curl and snapshot, no network)."""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pogo-store-reader"))
import reader  # noqa: E402

KEY = "k" * 40
AU = {"items": [{"name": "a", "price": "A$1.99"}, {"name": "b", "price": "A$4.99"}, {"name": "c", "price": "A$0.00"}]}
US = {"items": [{"name": "a", "price": "US$0.99"}, {"name": "b", "price": "US$4.99"}, {"name": "c", "price": "A$1.00"}]}


class CheckAuTests(unittest.TestCase):
    def test_au_snapshot_passes(self):
        self.assertEqual(reader.check_au(json.dumps(AU)), (3, None))

    def test_us_price_rejected(self):
        self.assertIsNotNone(reader.check_au(json.dumps(US))[1])

    def test_unmarked_prices_rejected(self):
        d = {"items": [{"price": "$1.99"}, {"price": "$2.99"}, {"price": "A$1"}]}
        self.assertIsNotNone(reader.check_au(json.dumps(d))[1])

    def test_empty_invalid_and_itemless_rejected(self):
        for raw in ("", "  \n", "{not json", "[]", '{"items": []}', '{"items": 5}'):
            self.assertIsNotNone(reader.check_au(raw)[1], raw)


GOOD_ITEM = {"name": "n", "section": "s", "price": "A$1.00", "href": "/purchase/abc?x=1",
             "imgs": ["https://assets.pgo.webstore.nianticlabs.com/a.png"]}


def snap(**over):
    i = dict(GOOD_ITEM)
    i.update(over)
    return json.dumps({"fetched": "2026-11-17T00:00:00Z", "items": [i]})


class DryCheckTests(unittest.TestCase):
    def test_good_passes(self):
        self.assertIsNone(reader.dry_check(snap()))

    def test_rules_named(self):
        cases = {
            "img_not_https": snap(imgs=["http://assets.pgo.webstore.nianticlabs.com/a.png"]),
            "img_host": snap(imgs=["https://example.com/a.png"]),
            "imgs_bad_or_over_6": snap(imgs=["https://assets.pgo.webstore.nianticlabs.com/a"] * 7),
            "href_not_purchase_path": snap(href="//evil.com/purchase/x"),
            "name_bad": snap(name="x" * 201),
            "section_bad": snap(section=""),
            "tag_too_long": snap(tag="x" * 301),
            "too_many_items": json.dumps({"fetched": "x", "items": [GOOD_ITEM] * 401}),
            "size_over_256kb": snap(name="x" * 200, tag="y" * 300) + " " * (256 * 1024),
            "not_json": "{nope",
        }
        for rule, raw in cases.items():
            self.assertEqual(reader.dry_check(raw), rule, rule)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.calls = t / "calls"
        self.stdin_log = t / "stdin"
        self.args_log = t / "args"
        self.body = t / "body.json"
        self.body.write_text(json.dumps(AU))
        curl = t / "curl"
        curl.write_text('#!/bin/sh\necho x >> "%s"\necho "$@" > "%s"\ncat > "%s"\n'
                        'while [ $# -gt 0 ]; do if [ "$1" = -o ]; then printf "%%s" "$FAKE_BODY" > "$2"; fi; shift; done\n'
                        'printf "%%s" "$FAKE_STATUS"\n'
                        % (self.calls, self.args_log, self.stdin_log))
        curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
        snap = t / "snap.py"
        snap.write_text("import os,sys\nif os.environ.get('SNAP_FAIL'):\n    print('noise'); [print('line%d' % i, file=sys.stderr) for i in range(8)]\n    print('boom ' + os.environ['SNAP_KEY'] + ' x-ingest-key: abc ' + 'z'*500, file=sys.stderr); sys.exit(3)\n"
                        "open(sys.argv[1],'w').write(open(os.environ['SNAP_BODY']).read())\n")
        opts = t / "options.json"
        opts.write_text(json.dumps({"ingest_key": KEY, "interval_minutes": 30, "jitter_minutes": 0, "run_on_start": True}))
        self.opts = str(opts)
        reader.CURL, reader.SNAPSHOT_SCRIPT = str(curl), str(snap)
        os.environ.update(SNAP_KEY=KEY, SNAP_BODY=str(self.body), FAKE_STATUS="200", FAKE_BODY="")
        os.environ.pop("SNAP_FAIL", None)
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, cycles=1):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reader.main(self.opts, sleep=self.sleeps.append, rand=lambda a, b: 0, max_cycles=cycles)
        return rc, buf.getvalue()

    def n_posts(self):
        return len(self.calls.read_text().split()) if self.calls.exists() else 0

    def test_success_statuses(self):
        for status in ("200", "409", "429"):
            self.calls.unlink(missing_ok=True)
            os.environ["FAKE_STATUS"] = status
            self.sleeps.clear()
            rc, out = self.run_main()
            self.assertEqual(rc, 0)
            self.assertEqual(self.n_posts(), 1, status)
            self.assertNotIn(300, self.sleeps)  # no retry
            self.assertIn("http=" + status, out)

    def test_key_sent_by_header_not_argv_and_not_logged(self):
        for status in ("200", "401", "403", "404", "500"):
            os.environ["FAKE_STATUS"] = status
            rc, out = self.run_main()
            self.assertNotIn(KEY, out)
            self.assertNotIn(KEY, self.args_log.read_text())
        self.assertIn("x-ingest-key: " + KEY, self.stdin_log.read_text())
        self.assertIn("content-type: application/json", self.stdin_log.read_text())
        self.assertIn("--max-time 60", self.args_log.read_text())

    def test_401_stops_uploading(self):
        os.environ["FAKE_STATUS"] = "401"
        rc, out = self.run_main(cycles=3)
        self.assertEqual(rc, 2)
        self.assertEqual(self.n_posts(), 1)
        self.assertIn("key rejected", out)

    def test_404_and_403_wait_without_retry(self):
        for status, msg in (("404", "endpoint not switched on"), ("403", "key rejected")):
            self.calls.unlink(missing_ok=True)
            os.environ["FAKE_STATUS"] = status
            rc, out = self.run_main(cycles=2)
            self.assertEqual(self.n_posts(), 2, status)  # one per interval, no extra retry
            self.assertIn(msg, out)

    def test_other_error_retries_once_after_five_minutes(self):
        os.environ["FAKE_STATUS"] = "500"
        self.run_main()
        self.assertEqual(self.n_posts(), 2)
        self.assertEqual(self.sleeps, [300])

    def test_400_logs_only_a_valid_reason(self):
        os.environ["FAKE_STATUS"] = "400"
        for body, want in (('{"error":"Bad request.","reason":"img_host"}', "reason=img_host"),
                           ('{"reason":"Has Spaces & secrets %s"}' % KEY, None),
                           ('{"reason":"%s"}' % ("a" * 33), None),
                           ("<html>nope", None), ('{"error":"leak-me"}', None)):
            os.environ["FAKE_BODY"] = body
            rc, out = self.run_main()
            self.assertIn("upload failed: http=400", out)
            self.assertNotIn(KEY, out)
            self.assertNotIn("leak-me", out)
            if want:
                self.assertIn(want, out)
            else:
                self.assertNotIn("reason=", out.split("upload failed")[1])

    def test_dry_check_failure_is_logged_but_still_uploads(self):
        self.body.write_text(snap(imgs=["https://example.com/a.png"]))
        d = json.loads(self.body.read_text())
        d["items"] = d["items"] * 3
        self.body.write_text(json.dumps(d))
        rc, out = self.run_main()
        self.assertIn("rule=img_host", out)
        self.assertNotIn("example.com", out)
        self.assertEqual(self.n_posts(), 1)

    def test_section_mismatch_diag_logged(self):
        d = {"fetched": "x", "items": [
            {"name": "SECRETNAME", "section": "daily", "price": "A$1.00", "href": "/purchase/SECRETHREF"},
            {"name": "b", "section": "daily", "price": "A$2.00"}, {"name": "c", "section": "extra\u00e9", "price": "A$3.00"}],
            "completeness": {"schema": 1, "cards": 3, "sections": [
                {"name": "daily", "count": 2}, {"name": "empty", "count": 0}, {"name": "x" * 60, "count": 1}]}}
        self.body.write_text(json.dumps(d))
        os.environ.update(FAKE_STATUS="400", FAKE_BODY='{"reason":"section_mismatch"}')
        rc, out = self.run_main()
        self.assertIn("diag: cards_stated=3 section_counts_sum=3 items=3 nameless_cards=0 sections=3 item_sections=2", out)
        self.assertIn("section=empty cards=0 items=0 EMPTY_SECTION", out)
        self.assertIn("section=extra? cards=- items=1 NOT_IN_EVIDENCE", out)
        self.assertIn("section=%s cards=1 items=0 MISMATCH" % ("x" * 40), out)
        self.assertNotIn("x" * 41, out)
        for secret in ("SECRETNAME", "SECRETHREF", "A$", KEY):
            self.assertNotIn(secret, out)

    def test_no_diag_for_other_reasons(self):
        os.environ.update(FAKE_STATUS="400", FAKE_BODY='{"reason":"img_host"}')
        rc, out = self.run_main()
        self.assertNotIn("diag:", out)

    def test_diag_line_cap(self):
        secs = [{"name": "s%d" % i, "count": 1} for i in range(50)]
        raw = json.dumps({"items": [], "completeness": {"cards": 50, "sections": secs}})
        self.assertLessEqual(len(reader.section_diag(raw)), 20)

    def test_us_snapshot_not_uploaded(self):
        self.body.write_text(json.dumps(US))
        rc, out = self.run_main()
        self.assertEqual(self.n_posts(), 0)
        self.assertIn("not uploading", out)

    def test_snapshot_failure_not_uploaded(self):
        os.environ["SNAP_FAIL"] = "1"
        rc, out = self.run_main()
        self.assertEqual(self.n_posts(), 0)
        self.assertIn("snapshot failed (exit 3)", out)
        self.assertIn("snapshot output: line7", out)
        self.assertNotIn("line2", out)  # only the last 5 lines
        self.assertNotIn(KEY, out)
        self.assertNotIn("abc", out)
        self.assertTrue(all(len(l) < 240 for l in out.splitlines()))

    def test_preflight_logged_without_key(self):
        rc, out = self.run_main()
        self.assertIn("preflight: python=", out)
        self.assertRegex(out, r"playwright import (ok|FAILED)")
        self.assertNotIn(KEY, out)

    def test_run_on_start_false_waits_first(self):
        Path(self.opts).write_text(json.dumps({"ingest_key": KEY, "interval_minutes": 45, "jitter_minutes": 0, "run_on_start": False}))
        self.run_main()
        self.assertEqual(self.sleeps, [45 * 60])

    def test_short_key_refuses_to_start(self):
        Path(self.opts).write_text(json.dumps({"ingest_key": "short"}))
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(self.n_posts(), 0)


class StaticTests(unittest.TestCase):
    def test_config_and_provenance(self):
        d = ROOT / "pogo-store-reader"
        cfg = (d / "config.yaml").read_text()
        self.assertIn("ingest_key: password(32,)", cfg)
        self.assertIn("interval_minutes: int(30,)", cfg)
        self.assertNotIn("ingest_key:", cfg.split("schema:")[0])  # no default key
        self.assertIn("playwright/python:v1.49.0", (d / "Dockerfile").read_text())
        df = (d / "Dockerfile").read_text()
        self.assertIn("playwright==1.49.0", df)
        self.assertIn("playwright install --with-deps chromium", df)
        self.assertIn("chromium.launch()", df)
        self.assertIn("1ff10302cc327a5fe65721924806a8b9e919cf3b", (d / "store_snapshot.py.source").read_text())


if __name__ == "__main__":
    unittest.main()
