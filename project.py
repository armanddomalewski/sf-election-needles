#!/usr/bin/env python3
"""Turn results.json (from scrape.py) into site/projections.json: one needle per contest.

Which contests: anything matching config "include" (regex, case-insensitive) that is not
matched by "skip", has at least two real candidates (write-ins don't count), and is not a
multi-seat contest. Ballot measures show Yes share against their pass threshold; candidate
races show the leader's share of the top two. Ranked-choice contests use the department's
"Last Round" column when the page has it, first-choice top two until then.

Model, in one line: SF counts ballots in a fixed order (early mail, then election-day
polls, then late mail and provisionals), and later batches lean a predictable direction:

    final = share_now + late_shift * remaining_fraction

late_shift ~ Normal(late_shift_mean, late_shift_sd) in points (config.json; calibrate with
calibrate.py). For candidate races the sign is unknown, so only the sd widens the interval.
A floor of min_half_width keeps the needle honest in early batches.
"""
import argparse, datetime as dt, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NOT_A_CANDIDATE = re.compile(r"write-?in|^total|blank|under vote|over vote|exhaust|continuing", re.I)
MULTI_SEAT = re.compile(r"board of education|community college board full", re.I)


def titlecase(name):
    """STEPHEN SHERRILL -> Stephen Sherrill, keeping things like 'DJ' and 'III' sensible."""
    def fix(w):
        if re.fullmatch(r"(II|III|IV|JR\.?|SR\.?|DJ|PJ)", w, re.I):
            return w.upper()
        t = re.sub(r"(^|[-'’(\"])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w.lower())
        return re.sub(r"^(Mc|Mac)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    return " ".join(fix(w) for w in name.split())


def display_name(name):
    """Short title + subtitle for the card."""
    n = re.sub(r"\s*\(Ranked-Choice Voting Contest\)", "", name).strip()
    m = re.match(r"(REGIONAL MEASURE|MEASURE|PROPOSITION)\s+([A-Z0-9]+)\s*-\s*(.*)", n, re.I)
    if m:
        kind = "Measure" if "MEASURE" in m.group(1).upper() else "Proposition"
        sub = m.group(3).capitalize()
        if m.group(1).upper().startswith(("REGIONAL", "PROPOSITION")):
            sub = "San Francisco votes only. " + sub      # decided region- or state-wide
        return f"{kind} {m.group(2)}", sub
    m = re.match(r"MEMBER, BOARD OF SUPERVISORS, DISTRICT (\d+)", n, re.I)
    if m:
        return f"Supervisor, District {m.group(1)}", "Ranked choice"
    m = re.match(r"UNITED STATES REPRESENTATIVE, DISTRICT (\d+)", n, re.I)
    if m:
        return f"U.S. House, District {m.group(1)}", "San Francisco votes only"
    m = re.match(r"STATE (SENATOR|ASSEMBLY MEMBER), DISTRICT (\d+)", n, re.I)
    if m:
        return f"State {'Senate' if m.group(1).upper() == 'SENATOR' else 'Assembly'}, District {m.group(2)}", "San Francisco votes only"
    return titlecase(n), ""


def yes_no(contest):
    yes = next((c for c in contest["choices"] if re.search(r"(^|\b)yes\b", c["name"], re.I)), None)
    no = next((c for c in contest["choices"] if re.search(r"(^|\b)no\b", c["name"], re.I)), None)
    return yes, no


def lean_for(cfg, key):
    """Expected lean of the still-uncounted vote, in points, for a contest or candidate.

    config "leans" maps a case-insensitive substring of the contest name (measures) or the
    candidate name (races) to a number: positive means the late vote favors Yes / that
    candidate. "lean_scale" multiplies every entry so one number tunes the whole table."""
    for pat, v in cfg.get("leans", {}).items():
        if pat.lower() in key.lower():
            return v * cfg.get("lean_scale", 1.0)
    return None


def interval(share, n, remaining, cfg, mean_shift):
    sd_shift = cfg["late_shift_sd"] * remaining
    sd_sample = 100.0 * math.sqrt(share / 100 * (1 - share / 100) / max(n, 1)) * remaining
    sd = math.sqrt(sd_shift ** 2 + sd_sample ** 2)
    half = max(1.96 * sd, cfg["min_half_width"]) if remaining > 0 else 0.0
    proj = min(100.0, max(0.0, share + mean_shift * remaining))
    return round(proj, 2), round(max(0.0, proj - half), 2), round(min(100.0, proj + half), 2)


def project_contest(contest, remaining, cfg):
    cid = re.sub(r"[^a-z0-9]+", "-", contest["name"].lower()).strip("-")[:60]
    title, subtitle = display_name(contest["name"])
    base = {"id": cid, "name": title, "subtitle": subtitle, "source_name": contest["name"]}
    yes, no = yes_no(contest)
    if yes and no:
        n = yes["votes"] + no["votes"]
        thr = contest.get("threshold") or 50.0
        base.update({"type": "measure", "left": "No", "right": "Yes", "threshold": thr,
                     "votes": {"Yes": yes["votes"], "No": no["votes"]}})
        if thr != 50.0:
            base["subtitle"] = f"Needs {thr:g}% to pass. " + subtitle
        if n == 0:
            return {**base, "share": None}
        lean = lean_for(cfg, contest["name"])
        shift = cfg["late_shift_mean"] if lean is None else lean
        share, lo, hi = interval(100.0 * yes["votes"] / n, n, remaining, cfg, shift)
        return {**base, "share": share, "lo": lo, "hi": hi, "late_lean": shift,
                "raw_share": round(100.0 * yes["votes"] / n, 2)}
    cands = sorted((c for c in contest["choices"] if not NOT_A_CANDIDATE.search(c["name"])), key=lambda c: -c["votes"])
    if len(cands) < 2 or MULTI_SEAT.search(contest["name"]):
        return None                                   # uncontested or multi-seat
    a, b = cands[0], cands[1]
    n = a["votes"] + b["votes"]
    rcv = "ranked-choice" in contest["name"].lower()
    base.update({"type": "race", "left": titlecase(b["name"]), "right": titlecase(a["name"]), "threshold": 50.0,
                 "rcv": rcv, "last_round": bool(contest.get("last_round")),
                 "votes": {titlecase(c["name"]): c["votes"] for c in cands}})
    if rcv:
        base["subtitle"] = "Ranked choice, final round" if contest.get("last_round") else "Ranked choice, first choices for now"
    if n == 0:
        return {**base, "share": None}
    la, lb = lean_for(cfg, a["name"]), lean_for(cfg, b["name"])
    shift = la if la is not None else (-lb if lb is not None else 0.0)    # for the leader's two-way share
    share, lo, hi = interval(100.0 * a["votes"] / n, n, remaining, cfg, shift)
    return {**base, "share": share, "lo": lo, "hi": hi, "late_lean": shift,
            "raw_share": round(100.0 * a["votes"] / n, 2)}


def project_all(cfg, results, final=False):
    meta = results.get("page_meta", {})
    counted = results.get("ballots_cast") or 0
    reg = meta.get("voter_registration_total")
    expected = cfg.get("expected_total_ballots") or (reg * cfg.get("expected_turnout", 0.6) if reg else 0)
    expected = max(expected, counted, 1)
    remaining = 0.0 if final else max(0.0, 1.0 - counted / expected)
    inc = [re.compile(x, re.I) for x in cfg.get("include", [".*"])]
    skip = [re.compile(x, re.I) for x in cfg.get("skip", [])]
    out = []
    for c in results["contests"]:
        if not any(r.search(c["name"]) for r in inc) or any(r.search(c["name"]) for r in skip):
            continue
        p = project_contest(c, remaining, cfg)
        if p:
            p["final"] = bool(final)
            out.append(p)
    return {"updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "report_title": meta.get("report_title"), "next_update": meta.get("next_update"),
            "pct_reporting": round(100.0 * counted / expected, 1) if counted else 0,
            "ballots_cast": counted, "expected_total_ballots": int(expected),
            "precincts_reported": meta.get("precincts_reported"), "precincts_total": meta.get("precincts_total"),
            "final": bool(final), "contests": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--results", default=os.path.join(HERE, "results.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "docs", "projections.json"))
    ap.add_argument("--final", action="store_true", help="count is certified; hide the ranges")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    results = json.load(open(a.results))
    p = project_all(cfg, results, a.final)
    if not p["contests"]:
        sys.exit("no contests parsed (blocked page or layout change); leaving the published file alone")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(p, f, indent=1)
    print(f"{p['report_title']} | ballots {p['ballots_cast']} of ~{p['expected_total_ballots']} ({p['pct_reporting']}%)", file=sys.stderr)
    for c in p["contests"]:
        print(f"  {c['name']:<32} {c['right'][:22]:<22} {c.get('share')}  [{c.get('lo')}, {c.get('hi')}]", file=sys.stderr)


if __name__ == "__main__":
    main()
