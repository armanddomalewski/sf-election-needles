#!/usr/bin/env python3
"""Fetch the SF Department of Elections results page for one election, archive the raw
HTML, and write a normalized results.json.

The department serves sfelections.org through CloudFront with a firewall that rejects
cloud/datacenter addresses, so run this from a home connection. Nothing here spoofs a
browser; the User-Agent is honest.

Usage:
  scrape.py --config config.json                  # fetch live page, parse, write results.json
  scrape.py --config config.json --loop 120       # keep fetching every 120 s
  scrape.py --from-file snapshots/xxx.html        # parse a saved page instead of fetching
  scrape.py --from-file page.html --dump-tables   # show every table found, for parser tuning

Only the standard library is used so it runs on any Python 3.9+.
"""
import argparse, datetime as dt, html, json, os, re, sys, time, urllib.request
from html.parser import HTMLParser

UA = "sf-needle-scraper/0.1 (personal election-night project)"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class TableGrabber(HTMLParser):
    """Collect headings, captions and tables in document order."""

    def __init__(self):
        super().__init__()
        self.items = []            # ("h", text), ("n", note text) or ("t", rows)
        self._heading = None       # list of text chunks while inside h1..h6/caption
        self._table = None         # list of rows while inside <table>
        self._row = None
        self._cell = None
        self._note = []            # loose text since the last heading/table
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "caption"):
            self._heading = []
        elif tag == "table":
            self._flush_note()
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "caption") and self._heading is not None:
            text = clean(" ".join(self._heading))
            self._flush_note()
            if text:
                self.items.append(("h", text))
            self._heading = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(clean(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.items.append(("t", self._table))
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._heading is not None:
            self._heading.append(data)
        elif self._table is None:
            self._note.append(data)

    def _flush_note(self):
        text = clean(" ".join(self._note))
        self._note = []
        if text:
            self.items.append(("n", text))


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


INT = re.compile(r"^-?[\d,]+$")
PCT = re.compile(r"^-?\d+(\.\d+)?\s*%$")
# ranked-choice cells once votes exist: "6,601 (82.10%)"; losers show "eliminated in Round 2"
NUM_PCT = re.compile(r"^\s*([\d,]+)\s*\(\s*([\d.]+)\s*%\s*\)\s*$")
TOTAL_WORDS = ("total", "ballots cast", "turnout", "registration", "precincts", "under vote", "over vote",
               "undervote", "overvote", "blank", "write-in total", "continuing ballots", "exhausted")


def cell_value(c):
    """-> (votes, pct) for a cell holding a count, a percent, or "count (pct%)"; else (None, None)."""
    c = c.strip()
    m = NUM_PCT.match(c)
    if m:
        return int(m.group(1).replace(",", "")), float(m.group(2))
    if INT.match(c.replace(" ", "")):
        return int(c.replace(",", "").replace(" ", "")), None
    if PCT.match(c):
        return None, float(c.rstrip("% "))
    return None, None


def parse_table(rows):
    """Turn a table into {"choices": [...], "total": int|None, "meta": {...}} or None.

    Ranked-choice tables carry "Round 1" and "Round N (Last Round)" columns once votes exist
    (or a single "Round 1 (Last Round)" column for two-candidate races). When a Last Round
    header is present that column is the vote count, and a candidate whose last-round cell
    holds no number ("eliminated in Round 2") counts as 0 there."""
    choices, meta = [], {}
    header = rows[0] if rows and not any(cell_value(c)[0] is not None for c in rows[0][1:]) else []
    last_round_col = next((i for i, h in enumerate(header) if "last round" in h.lower()), None)
    for row in rows:
        if len(row) < 2 or row is header:
            continue
        name = row[0]
        vals = [cell_value(c) for c in row[1:]]
        nums = [v for v, _ in vals if v is not None]
        pcts = [p for _, p in vals if p is not None]
        if not nums:
            continue
        if last_round_col is not None and last_round_col < len(row):
            lr_votes, lr_pct = cell_value(row[last_round_col])
            votes = lr_votes if lr_votes is not None else 0          # eliminated before the last round
            pct = lr_pct if lr_pct is not None else 0.0
        else:
            votes = nums[-1]                                          # last count column is cumulative
            pct = pcts[-1] if pcts else None
        key = name.lower()
        if any(w in key for w in TOTAL_WORDS):
            meta[name] = votes
        else:
            choices.append({"name": name, "votes": votes, "pct": pct})
    if not choices and not meta:
        return None
    total = sum(c["votes"] for c in choices)
    for k, v in meta.items():
        if k.lower().startswith("total"):
            total = v
    return {"choices": choices, "total": total, "meta": meta, "last_round": last_round_col is not None}


def parse_page(raw):
    p = TableGrabber()
    p.feed(raw.decode("utf-8", "replace"))
    contests, heading, seen, page_meta, note = [], None, set(), {}, ""
    for kind, val in p.items:
        if kind == "h":
            heading, note = val, ""
            continue
        if kind == "n":
            note += " " + val
            continue
        parsed = parse_table(val)
        if not parsed:
            continue
        page_meta.update(parsed["meta"])
        if not parsed["choices"]:             # turnout / registration tables: keep their numbers only
            continue
        m = re.search(r"require[sd]?\s+(50\s*%?\s*\+\s*1\s*%?|two-thirds|2/3|66\.67%|55%|a majority)", note, re.I)
        key = re.sub(r"\s", "", m.group(1).lower()) if m else ""
        parsed["threshold"] = None if not m else 66.67 if key in ("two-thirds", "2/3", "66.67%") else 55.0 if key == "55%" else 50.0
        name = heading or f"table {len(contests) + 1}"
        if name in seen:                     # a second table under one heading: suffix it
            name = f"{name} ({len(contests) + 1})"
        seen.add(name)
        contests.append({"name": name, **parsed})
    data_links = sorted({l for l in p.links if re.search(r"/data/\d{8}/|\.(txt|csv|xlsx?|xml|json|zip|pdf)$", l)})
    page_meta.update(header_block(raw.decode("utf-8", "replace")))
    return {"contests": contests, "data_links": data_links, "meta": page_meta}


def header_block(text):
    """The lines above the first table: ballots cast, registration, precincts, next update, report name."""
    out = {}
    def grab(label, pattern, cast=lambda x: x):
        m = re.search(label + r":?\s*</strong>\s*" + pattern, text, re.I)
        if m:
            out[label.lower().replace(" ", "_")] = cast(m.group(1))
    grab("Number of Ballots Cast", r"([\d,]+)", lambda x: int(x.replace(",", "")))
    grab("Voter registration total", r"([\d,]+)", lambda x: int(x.replace(",", "")))
    grab("Current voter turnout", r"([\d.]+)%", float)
    grab("Next Update", r"(?:<span[^>]*>)?([^<]+)", lambda x: clean(x))
    m = re.search(r"Precincts that have reported in-person results:?\s*</strong>\s*([\d,]+)\s*of\s*([\d,]+)", text, re.I)
    if m:
        out["precincts_reported"] = int(m.group(1).replace(",", ""))
        out["precincts_total"] = int(m.group(2).replace(",", ""))
    m = re.search(r"<h1[^>]*>([^<]+)</h1>", text)
    if m:
        out["report_title"] = clean(m.group(1))
    return out


def ballots_cast(meta):
    """Ballots counted so far: the header's "Number of Ballots Cast", else the largest ballots-cast-style number."""
    if meta.get("number_of_ballots_cast") is not None:
        return meta["number_of_ballots_cast"]
    best = 0
    for k, v in meta.items():
        if isinstance(v, int) and ("ballots cast" in k.lower() or "total ballots" in k.lower()):
            best = max(best, v)
    return best or None


def run_once(cfg, from_file=None, dump=False):
    now = dt.datetime.now(dt.timezone.utc)
    if from_file:
        raw = open(from_file, "rb").read()
        source = from_file
    else:
        url = cfg["index_url"]
        raw = fetch(url)
        source = url
        os.makedirs(SNAP, exist_ok=True)
        snap = os.path.join(SNAP, now.strftime("%Y%m%dT%H%M%SZ") + "_index.html")
        with open(snap, "wb") as f:
            f.write(raw)
        print(f"saved {snap} ({len(raw)} bytes)", file=sys.stderr)
    parsed = parse_page(raw)
    if dump:
        for c in parsed["contests"]:
            print(f"== {c['name']}  total={c['total']}  meta={c['meta']}")
            for ch in c["choices"]:
                print(f"   {ch['name']:<40} {ch['votes']:>9}  {ch['pct']}")
        print("data links:", *parsed["data_links"], sep="\n  ")
    out = {
        "fetched_utc": now.isoformat(timespec="seconds"),
        "source": source,
        "ballots_cast": ballots_cast(parsed["meta"]),
        "page_meta": parsed["meta"],
        "contests": parsed["contests"],
        "data_links": parsed["data_links"],
    }
    path = os.path.join(HERE, "results.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {path}: {len(out['contests'])} contests, ballots_cast={out['ballots_cast']}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--from-file")
    ap.add_argument("--dump-tables", action="store_true")
    ap.add_argument("--loop", type=int, metavar="SECONDS")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    while True:
        try:
            run_once(cfg, a.from_file, a.dump_tables)
        except Exception as e:                       # keep the loop alive on election night
            print(f"error: {e!r}", file=sys.stderr)
            if not a.loop:
                raise
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
