#!/usr/bin/env python3
"""Download every batch report of past elections for calibration.

For each election id (e.g. 20241105), opens results/<id>w/detail.html in the installed Chrome,
finds the report folders under results/<id>/data/, and saves each one's summary.xml under
history/<id>/<folder>_summary.xml. The downloads run as fetch() calls inside the open page, so
they pass the department's firewall the same way the page itself does.

Usage:
    fetch_history.py 20241105 20240305 20221108
"""
import os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.sfelections.org/results"


def main(ids):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        for eid in ids:
            page.goto(f"{BASE}/{eid}w/detail.html", wait_until="networkidle", timeout=60000)
            html = page.content()
            folders = sorted(set(re.findall(rf"results/{eid}/data/([^/\"']+)/", html)))
            print(f"{eid}: {len(folders)} report folders", file=sys.stderr)
            out_dir = os.path.join(HERE, "history", eid)
            os.makedirs(out_dir, exist_ok=True)
            for f in folders:
                out = os.path.join(out_dir, f"{f}_summary.xml")
                if os.path.exists(out):
                    continue
                url = f"{BASE}/{eid}/data/{f}/summary.xml"
                text = page.evaluate("u => fetch(u, {cache: 'no-store'}).then(r => r.ok ? r.text() : 'HTTP ' + r.status)", url)
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(text)
                print(f"  {f}: {len(text)} chars", file=sys.stderr)
                time.sleep(1)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["20241105"])
