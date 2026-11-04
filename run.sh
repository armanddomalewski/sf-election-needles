#!/usr/bin/env bash
# Election-night loop: load the results page in Chrome, rebuild projections.json, publish to
# GitHub Pages, repeat. Default every 3 minutes.
#
#   ./run.sh            # automatic: fetch with the browser (needs: pip install playwright)
#   ./run.sh manual     # instead, watch snapshots/ for pages you save from the browser yourself
set -u
cd "$(dirname "$0")"
MODE="${1:-auto}"
INTERVAL="${2:-180}"
last=""
while true; do
  if [ "$MODE" = "manual" ]; then
    newest=$(ls -t snapshots/*.html 2>/dev/null | head -1)
    if [ -n "$newest" ] && [ "$newest" != "$last" ]; then
      echo "parsing $newest"
      python3 scrape.py --from-file "$newest" && python3 project.py && ./publish.sh && last="$newest"
    fi
    sleep 30
  else
    # Idle until 8:40 PM Pacific on election night; the first batch posts at 8:45.
    if [ "$(TZ=America/Los_Angeles date +%Y%m%d%H%M)" -lt 202611032040 ]; then
      echo "$(date +%H:%M) waiting for polls to close (first batch 8:45 PM)"; sleep 300; continue
    fi
    git pull -q --rebase origin main 2>/dev/null || true     # pick up config/lean tweaks
    python3 fetch_browser.py && python3 project.py && ./publish.sh
    # keep the raw page public too, so the parser can be checked against it from anywhere
    newest=$(ls -t snapshots/*.html 2>/dev/null | head -1)
    [ -n "$newest" ] && cp "$newest" docs/latest_page.html && git add docs/latest_page.html \
      && git -c commit.gpgsign=false commit -q -m "latest page" docs/latest_page.html 2>/dev/null && git push -q origin main 2>/dev/null
    sleep "$INTERVAL"
  fi
done
