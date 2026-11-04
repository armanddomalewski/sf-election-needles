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
    git pull -q --rebase origin main 2>/dev/null || true     # pick up config/lean tweaks
    python3 fetch_browser.py && python3 project.py && ./publish.sh
    sleep "$INTERVAL"
  fi
done
