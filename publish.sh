#!/usr/bin/env bash
# Commit docs/projections.json and push, which republishes the GitHub Pages site.
set -eu
cd "$(dirname "$0")"
# Skip the commit when only the timestamp changed (same report, same numbers)
if [ -f docs/projections.json ] && git show HEAD:docs/projections.json 2>/dev/null \
   | grep -v '"updated_utc"' | diff -q - <(grep -v '"updated_utc"' docs/projections.json) >/dev/null; then
  echo "no change in results; not publishing"; git checkout -q docs/projections.json; exit 0
fi
git add docs/projections.json
if git diff --cached --quiet; then echo "nothing new to publish"; exit 0; fi
git commit -q -m "Update projections $(date -u +%Y-%m-%dT%H:%MZ)"
# other commits may have landed (config tweaks from the other side); keep ours on top
git pull -q --rebase -X theirs origin main || { git rebase --abort; git reset -q --hard origin/main; exit 1; }
git push -q origin main
echo "published $(date)"
