# Pokemon GO Store Reader

Reads the public Pokemon GO web store from your Melbourne home connection (so prices are A$) and uploads the snapshot to your app's `/api/store-ingest` endpoint. The hourly GitHub reader runs from a US address and sees US$ prices, which is why this exists. Upload contract: `docs/store-home-reader.md` in Wood468/crispy-barnacle.

Fails closed: if the snapshot fails, is empty or invalid, or does not look Australian (any `US$` price, or fewer than half of prices in `A$`), nothing is uploaded.

## Install

1. The repository is already added (Settings, Add-ons, Add-on store, three dots, Repositories). Install **Pokemon GO Store Reader**.
2. In Configuration, set `ingest_key` to the app's `STORE_INGEST_KEY` (at least 32 characters). Do not put it anywhere else.
3. Start the add-on and watch the Log tab.

## Options

| Option | Default | Notes |
| --- | --- | --- |
| `ingest_url` | `https://pogo.michaelpuff.com/api/store-ingest` | https only |
| `ingest_key` | none, required | password field, min 32 chars, never logged |
| `interval_minutes` | 60 | min 30 |
| `jitter_minutes` | 10 | random 0 to N minutes added to each wait |
| `run_on_start` | true | upload once at start, then every interval |

## Test once by hand BEFORE enabling the schedule

The add-on starts with `boot: manual`, so it will not run on its own. Test first:

1. Set `interval_minutes` to 30 (the minimum), keep `run_on_start: true`, start the add-on.
2. Within a minute or two the log should show `uploaded: items=N http=200`. 409 or 429 also count as success ("already have it").
3. Stop the add-on. Only then consider turning on Start on boot.

A wrong key counts against the shared per-address failure bucket, the same one the sync PIN uses: repeated wrong-key uploads from home can make a mistyped PIN return 429 for 10 minutes. So after one `401` the add-on stops uploading until it is restarted; fix the key, then restart. A `404` means the endpoint is not switched on yet (the `STORE_INGEST_KEY` secret does not exist); it waits for the next interval.

## Behaviour

- Each cycle: run `store_snapshot.py` (headless Chromium, en-AU), check, then `curl` POST with `x-ingest-key` and `content-type: application/json`, `--max-time 60`. The key is passed to curl on stdin, not on the command line.
- 200, 409, 429: done, wait for the next interval. 401: stop until restart. 403 and 404: log and wait. Other errors or a failed snapshot: one retry after 5 minutes, then wait.
- Logs contain only timestamps, item count, HTTP status and short reasons; never the key or response bodies.

## Provenance

`store_snapshot.py` is copied verbatim from Wood468/crispy-barnacle; the source commit and blob SHA are in `store_snapshot.py.source`. The image is based on `mcr.microsoft.com/playwright/python:v1.49.0-jammy` (Chromium and Playwright 1.49.0 pinned together; a large image, roughly 1.5 GB). amd64 only.
