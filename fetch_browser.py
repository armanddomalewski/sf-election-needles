#!/usr/bin/env python3
"""Load the results page in the Chrome installed on this machine (via Playwright), save the
HTML to snapshots/, and parse it with scrape.py. The department's site answers plain HTTP
clients with a 403, so the page is read the way a person would, in a real browser, once every
few minutes.

One-time setup:
    pip install playwright

Usage:
    fetch_browser.py --dump-tables   # one fetch + parse, print what was found
    fetch_browser.py --loop 180      # every 3 minutes
"""
import argparse, datetime as dt, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrape  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def fetch_html(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # A visible window of the installed Chrome: the department's firewall also rejects
        # headless browsers. The window opens, loads the page, and closes within seconds.
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = p.chromium.launch(headless=False)                    # after: playwright install chromium
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    if "<h1>403 ERROR</h1>" in html or "Request blocked" in html:
        raise RuntimeError("the department's site returned 403 to the browser fetch")
    return html


def once(cfg, dump):
    now = dt.datetime.now(dt.timezone.utc)
    html = fetch_html(cfg["index_url"])
    os.makedirs(scrape.SNAP, exist_ok=True)
    path = os.path.join(scrape.SNAP, now.strftime("%Y%m%dT%H%M%SZ") + "_index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"saved {path} ({len(html)} chars)", file=sys.stderr)
    return scrape.run_once(cfg, from_file=path, dump=dump)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--dump-tables", action="store_true")
    ap.add_argument("--loop", type=int, metavar="SECONDS")
    ap.add_argument("--url", help="just save this page's HTML (for pulling past elections), no parsing")
    ap.add_argument("--out", help="where to save it (with --url)")
    a = ap.parse_args()
    if a.url:
        html = fetch_html(a.url)
        out = a.out or os.path.basename(a.url.rstrip("/")) or "page.html"
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"saved {out} ({len(html)} chars)", file=sys.stderr)
        return
    cfg = json.load(open(a.config))
    while True:
        try:
            once(cfg, a.dump_tables)
        except Exception as e:
            print(f"error: {e!r}", file=sys.stderr)
            if not a.loop:
                raise
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
