#!/usr/bin/env python3
"""How much do SF results move after the first election-night batch?

Reads the department's per-batch summary.xml reports saved by fetch_history.py and, for every
two-way contest (Yes/No measures, or the top two candidates), prints the first-batch share,
the certified share, the shift in points, and the implied "lean" of the uncounted vote:

    lean = shift / remaining_fraction_at_first_batch

which is the number config.json's leans table takes (positive = toward Yes / the first-batch
leader). The implied lean is what the model would have needed to land on the final result.

Usage:
    calibrate.py history/20241105 history/20221108            # prints a CSV
"""
import csv, glob, os, re, sys
import xml.etree.ElementTree as ET


def parse_summary(path):
    """-> (voters_cast, registration, {contest: [(choice, votes), ...]})"""
    root = ET.parse(path).getroot()
    text = open(path, encoding="utf-8").read()
    m = re.search(r'Voters Cast: (\d+) of (\d+)', text)
    cast, reg = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    contests = {}
    for cg in root.iter():
        if cg.tag.endswith("ContestIdGroup"):
            name = cg.get("contestId", "").strip()
            rows = []
            for ch in cg.iter():
                if ch.tag.endswith("candidateNameTextBox4"):
                    cand = ch.get("candidateNameTextBox4", "").strip()
                    tot = next((t for t in ch.iter() if t.tag.endswith("Textbox13")), None)
                    if cand and tot is not None and tot.get("vot8") is not None:
                        rows.append((cand, int(tot.get("vot8"))))
            if rows:
                contests[name] = rows
    return cast, reg, contests


def two_way(rows):
    """(label_right, label_left, right_votes, left_votes) for Yes/No or top two, else None."""
    d = {k.upper(): v for k, v in rows}
    yes = next((k for k in d if re.search(r"\bYES\b", k)), None)
    no = next((k for k in d if re.search(r"\bNO\b", k)), None)
    if yes and no:
        return "YES", "NO", d[yes], d[no]
    cands = [(k, v) for k, v in rows if not re.search(r"write-?in", k, re.I)]
    if len(cands) < 2:
        return None
    cands.sort(key=lambda kv: -kv[1])
    return cands[0][0], cands[1][0], cands[0][1], cands[1][1]


def batch_key(path):
    base = os.path.basename(path).replace("_summary.xml", "")
    return base


def main(dirs):
    w = csv.writer(sys.stdout)
    w.writerow(["election", "contest", "right", "left", "first_share", "final_share", "shift_pts",
                "first_counted_frac", "implied_lean"])
    for d in dirs:
        files = sorted(glob.glob(os.path.join(d, "*_summary.xml")), key=batch_key)
        # first election-night batch is the folder named <date>_1; final is the last file
        first = next((f for f in files if batch_key(f).endswith("_1")), None)
        if not first:
            print(f"skip {d}: no <date>_1 batch", file=sys.stderr)
            continue
        final = files[-1]
        c0, r0, k0 = parse_summary(first)
        c1, r1, k1 = parse_summary(final)
        frac = c0 / c1 if c0 and c1 else None
        eid = os.path.basename(d.rstrip("/"))
        for name, rows in k0.items():
            if name not in k1:
                continue
            a, b = two_way(rows), two_way(k1[name])
            if not a or not b or a[2] + a[3] == 0 or b[2] + b[3] == 0:
                continue
            # keep the same "right" side as the first batch, even if the lead flipped
            if b[0] != a[0]:
                d1 = {k: v for k, v in k1[name]}
                b = (a[0], a[1], d1.get(a[0], 0), d1.get(a[1], 0))
            s0 = 100 * a[2] / (a[2] + a[3])
            s1 = 100 * b[2] / (b[2] + b[3])
            lean = (s1 - s0) / (1 - frac) if frac and frac < 1 else None
            w.writerow([eid, name, a[0][:28], a[1][:28], f"{s0:.2f}", f"{s1:.2f}", f"{s1 - s0:+.2f}",
                        f"{frac:.3f}" if frac else "", f"{lean:+.2f}" if lean is not None else ""])


if __name__ == "__main__":
    main(sys.argv[1:])
