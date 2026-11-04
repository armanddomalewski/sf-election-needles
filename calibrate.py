#!/usr/bin/env python3
"""Estimate how much SF results move from the first election-night batch to the certified
count, per contest, using archived snapshots of past elections.

Give it one directory per past election containing the saved index pages for each batch,
named so they sort chronologically (scrape.py's snapshot names already do). It parses every
page with scrape.parse_page, takes the earliest and latest, and prints for each two-choice
contest: first-batch Yes share, final Yes share, and the shift in points. The mean and
standard deviation of those shifts, grouped however you like (citywide measures, district
races, ...), are what go into config.json as late_shift_mean and late_shift_sd.

Usage:
  calibrate.py snapshots/20241105w snapshots/20240305w ... > shifts.csv
"""
import csv, glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import parse_page  # noqa: E402


def two_way_share(contest):
    yes = no = None
    for ch in contest["choices"]:
        k = ch["name"].lower()
        if k.startswith("yes"):
            yes = ch["votes"]
        elif k.startswith("no"):
            no = ch["votes"]
    if yes is None or no is None or yes + no == 0:
        return None
    return 100.0 * yes / (yes + no)


def main(dirs):
    w = csv.writer(sys.stdout)
    w.writerow(["election", "contest", "first_share", "final_share", "shift_pts"])
    for d in dirs:
        files = sorted(glob.glob(os.path.join(d, "*.html")))
        if len(files) < 2:
            print(f"skip {d}: need at least two snapshots", file=sys.stderr)
            continue
        first = {c["name"]: c for c in parse_page(open(files[0], "rb").read())["contests"]}
        last = {c["name"]: c for c in parse_page(open(files[-1], "rb").read())["contests"]}
        for name, c0 in first.items():
            if name not in last:
                continue
            s0, s1 = two_way_share(c0), two_way_share(last[name])
            if s0 is None or s1 is None:
                continue
            w.writerow([os.path.basename(d.rstrip("/")), name, f"{s0:.2f}", f"{s1:.2f}", f"{s1 - s0:+.2f}"])


if __name__ == "__main__":
    main(sys.argv[1:])
