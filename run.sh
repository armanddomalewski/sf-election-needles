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
    # Election night (Nov 3) ran every 3 minutes from 8:40 PM. After that the department posts
    # once a day at 4 PM, so only fetch between 3:55 and 4:45 PM Pacific and sleep otherwise.
    # The first pass after starting always fetches, so a late restart still catches up.
    now=$(TZ=America/Los_Angeles date +%Y%m%d%H%M); hm=${now:8:4}
    if [ -n "$last" ] && [ "$now" -lt 202611032040 ]; then
      echo "$(date +%H:%M) waiting for polls to close (first batch 8:45 PM)"; sleep 300; continue
    elif [ -n "$last" ] && [ "$now" -gt 202611040400 ] && { [ "$hm" -lt 1555 ] || [ "$hm" -gt 1645 ]; }; then
      echo "$(date +%H:%M) idle; next department update is 4:00 PM"; sleep 600; continue
    fi
    last=started
    git pull -q --rebase origin main 2>/dev/null || true     # pick up config/lean tweaks
    python3 fetch_browser.py && python3 project.py && ./publish.sh
    sleep "$INTERVAL"
  fi
done
