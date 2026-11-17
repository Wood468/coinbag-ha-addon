"""Reads the public Pokemon GO web store (no sign-in) and writes what is on sale to a JSON file.
Usage: python scripts/store_snapshot.py out.json"""
import json, sys, time

PRODUCER = "store_snapshot.py"
SCHEMA = 1
MAX_PASSES = 20
STABLE_NEEDED = 2

# Per-section rendered-card counts, including cards without a name (placeholders), read from the page itself.
SECTIONS_JS = """() => [...document.querySelectorAll('.catalog__section')].map(sec =>
  ({name: sec.id || '', count: sec.querySelectorAll('.webstore-sku-card__container').length}))"""

JS = """() => [...document.querySelectorAll('.catalog__section')].flatMap(sec =>
  [...sec.querySelectorAll('.webstore-sku-card__container')].map(c => ({
    section: sec.id,
    name: (c.querySelector('[data-testid="sku-card.name"]') || {}).innerText || '',
    price: ((c.querySelector('[data-testid="sku-card.cta.price-with-or-without-discount"]') || {}).innerText || '').trim().split('\\n').pop(),
    tag: ((c.querySelector('[data-testid="sku-card.tag-primary"]') || {}).innerText || '').trim(),
    limit: ((c.querySelector('[data-testid="sku-card.tag-purchase-limit"]') || {}).innerText || '').trim(),
    left: ((/(\\d+)\\s*(day|hour|minute)s?\\s*left/i.exec(c.innerText || '')) || [''])[0],
    imgs: [...c.querySelectorAll('img')].filter(i => !i.closest('.badge')).map(i => i.currentSrc || i.src).filter(Boolean).slice(0, 3),
    href: (c.querySelector('a[href*="/purchase/"]') ? c.querySelector('a[href*="/purchase/"]').getAttribute('href') : ''),
  })))"""

def scroll_until_stable(read_sections, scroll, max_passes=MAX_PASSES, stable_needed=STABLE_NEEDED):
    """Scroll until `stable_needed` consecutive passes leave every section's card count unchanged.
    Returns (passes, consecutive_stable_passes, last_sections). Hitting the cap means the load never settled."""
    last, stable, passes = None, 0, 0
    while passes < max_passes:
        scroll()
        passes += 1
        cur = read_sections()
        stable = stable + 1 if cur == last else 0
        last = cur
        if stable >= stable_needed:
            break
    return passes, stable, last or []


def build_completeness(passes, stable_passes, max_passes, sections):
    """Producer-side evidence. The store page exposes no stated total, so none is claimed; the consumer
    (scripts/store-watch.mjs deriveCompleteness) checks this against the items actually saved."""
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "loadComplete": stable_passes >= STABLE_NEEDED,
        "passes": passes,
        "stablePasses": stable_passes,
        "maxPasses": max_passes,
        "cards": sum(s["count"] for s in sections),
        "sections": sections,
    }


def main(out):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(locale="en-AU", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36", viewport={"width": 1280, "height": 1600}).new_page()
        try:
            pg.goto("https://store.pokemongo.com/", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_selector('[data-testid="sku-card.name"]', timeout=45000)
        except Exception as e:
            body = ""
            try: body = pg.inner_text("body")[:300].replace("\n", " ")
            except Exception: pass
            print("::error title=Store page did not load::%s | title=%s | text=%s" % (str(e).splitlines()[0][:150], pg.title(), body))
            sys.exit(1)
        def scroll():
            pg.mouse.wheel(0, 2500); time.sleep(0.8)
        passes, stable, _ = scroll_until_stable(lambda: pg.evaluate(SECTIONS_JS), scroll)
        sections = pg.evaluate(SECTIONS_JS)  # read in the same moment as the items below
        items = [i for i in pg.evaluate(JS) if i["name"]]
        b.close()
    if len(items) < 3:
        sys.exit("Store page returned too few items (%d); not saving" % len(items))
    json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": items,
               "completeness": build_completeness(passes, stable, MAX_PASSES, sections)}, open(out, "w"), indent=1)
    print("Saved %d items" % len(items))

if __name__ == "__main__":
    main(sys.argv[1])
