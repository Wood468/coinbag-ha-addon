"""Pokemon GO store reader: snapshot the AU web store, check it, upload it. Fails closed.

Never logs the key or response bodies: only a redacted 5-line tail of a failed snapshot run, plus timestamps, item count, HTTP status, short reasons.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time

OPTIONS_PATH = os.environ.get("OPTIONS_PATH", "/data/options.json")
SNAPSHOT_SCRIPT = os.environ.get("SNAPSHOT_SCRIPT", "/app/store_snapshot.py")
CURL = os.environ.get("CURL_BIN", "curl")
RETRY_SECONDS = 300
SNAPSHOT_TIMEOUT = 300
MIN_KEY = 32


def log(msg):
    print("%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg), flush=True)


def preflight():
    """One log line: can the interpreter running the snapshot import Playwright? No secrets."""
    try:
        r = subprocess.run([sys.executable, "-c", "import playwright.sync_api"], capture_output=True, timeout=60)
        ok = r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    log("preflight: python=%s playwright import %s" % (sys.executable, "ok" if ok else "FAILED"))
    return ok


def load_options(path=OPTIONS_PATH):
    with open(path) as f:
        o = json.load(f)
    cfg = {
        "url": str(o.get("ingest_url") or "https://pogo.michaelpuff.com/api/store-ingest"),
        "key": str(o.get("ingest_key") or ""),
        "interval": max(30, int(o.get("interval_minutes", 60))),
        "jitter": max(0, int(o.get("jitter_minutes", 10))),
        "run_on_start": bool(o.get("run_on_start", True)),
    }
    if len(cfg["key"]) < MIN_KEY:
        raise ValueError("ingest_key must be at least %d characters" % MIN_KEY)
    if not cfg["url"].startswith("https://"):
        raise ValueError("ingest_url must be https")
    return cfg


def check_au(raw):
    """Returns (item_count, None) if the snapshot looks like the AU store, else (0, reason)."""
    if not raw.strip():
        return 0, "snapshot is empty"
    try:
        data = json.loads(raw)
    except ValueError:
        return 0, "snapshot is not valid JSON"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return 0, "snapshot has no items"
    prices = [str(i.get("price", "")) if isinstance(i, dict) else "" for i in items]
    if any("US$" in p for p in prices):
        return len(items), "prices contain US$ (not the AU store)"
    if sum("A$" in p for p in prices) * 2 < len(prices):
        return len(items), "fewer than half of the prices use A$"
    return len(items), None


def safe_tail(out, err, key="", lines=5, width=200):
    """Last few non-empty lines of the snapshot's stderr then stdout, redacted and truncated for the log."""
    text = (out or b"").decode("utf-8", "replace") + "\n" + (err or b"").decode("utf-8", "replace")
    tail = []
    for line in [l for l in text.splitlines() if l.strip()][-lines:]:
        line = "".join(c if c.isprintable() else " " for c in line)
        if key:
            line = line.replace(key, "[redacted]")
        line = re.sub(r"(?i)x-ingest-key[\s:=\"']*\S*", "[redacted]", line)
        tail.append(line.strip()[:width])
    return tail


def take_snapshot(path, key=""):
    """Returns (raw_text, None) or (None, reason). Only a redacted, truncated tail of a failed run's output is logged."""
    try:
        r = subprocess.run([sys.executable, SNAPSHOT_SCRIPT, path], capture_output=True, timeout=SNAPSHOT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "snapshot timed out"
    except OSError:
        return None, "snapshot could not start"
    if r.returncode != 0:
        for line in safe_tail(r.stdout, r.stderr, key):
            log("snapshot output: " + line)
        return None, "snapshot failed (exit %d)" % r.returncode
    try:
        with open(path) as f:
            return f.read(), None
    except OSError:
        return None, "snapshot file missing"


def post(cfg, path):
    """POST the file with curl; the key goes via stdin config so it is not in argv. Returns the HTTP status (0 = no response)."""
    conf = 'header = "x-ingest-key: %s"\nheader = "content-type: application/json"\n' % cfg["key"]
    try:
        r = subprocess.run(
            [CURL, "-sS", "--max-time", "60", "-o", os.devnull, "-w", "%{http_code}", "-K", "-",
             "--data-binary", "@" + path, cfg["url"]],
            input=conf.encode(), capture_output=True, timeout=90)
        return int(r.stdout.decode().strip() or 0)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return 0


def run_cycle(cfg):
    """One snapshot+upload. Returns 'ok', 'wait' (normal interval), 'retry', or 'stop' (key rejected)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.json")
        raw, why = take_snapshot(path, cfg["key"])
        if why:
            log("not uploading: " + why)
            return "retry"
        count, why = check_au(raw)
        if why:
            log("not uploading: %s (items=%d)" % (why, count))
            return "wait"
        status = post(cfg, path)
    if status in (200, 409, 429):
        log("uploaded: items=%d http=%d%s" % (count, status, "" if status == 200 else " (already have it)"))
        return "ok"
    if status == 401:
        log("http=401 key rejected; uploads stopped until the add-on restarts (a wrong key burns the shared failure bucket)")
        return "stop"
    if status in (403, 404):
        log("http=%d %s; waiting for the next interval" % (
            status, "key rejected" if status == 403 else "endpoint not switched on"))
        return "wait"
    log("upload failed: http=%d" % status)
    return "retry"


def main(options_path=OPTIONS_PATH, sleep=time.sleep, rand=random.uniform, max_cycles=None):
    try:
        cfg = load_options(options_path)
    except (OSError, ValueError) as e:
        log("bad options: %s" % e)
        return 1
    log("started: interval=%dm jitter=%dm run_on_start=%s" % (cfg["interval"], cfg["jitter"], cfg["run_on_start"]))
    preflight()
    cycles = 0
    first = True
    while max_cycles is None or cycles < max_cycles:
        if not (first and cfg["run_on_start"]):
            sleep(cfg["interval"] * 60 + rand(0, cfg["jitter"] * 60))
        first = False
        cycles += 1
        outcome = run_cycle(cfg)
        if outcome == "retry":
            sleep(RETRY_SECONDS)
            outcome = run_cycle(cfg)
        if outcome == "stop":
            while max_cycles is None:  # idle forever so HA does not restart-loop us
                sleep(3600)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
