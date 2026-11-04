# SF election needle

NYT-style needles for every contested San Francisco race (judges and uncontested races are skipped), modeled on [i86live.com](https://i86live.com/):
a static gauge page that polls a small `projections.json`, plus the scripts that produce that file
from the Department of Elections' batch releases.

## Pieces

| File | Job |
|---|---|
| `fetch_browser.py` | Load the results page in real Chrome, save the HTML under `snapshots/`, parse it. |
| `scrape.py` | The parser, plus a plain-HTTP fetcher the department blocks. `--from-file` parses a saved page into `results.json`. Stdlib only. |
| `project.py` | Apply the late-ballot-shift model to every contest in `results.json`, write `docs/projections.json`. Measures show Yes share; candidate races show the leader's share of the top two. |
| `docs/index.html` | A grid of gauges, one per contest, served by GitHub Pages. Polls `projections.json` every 30 s. Open with `?demo` to see it with sample numbers. |
| `calibrate.py` | Compute first-batch-to-final shifts from archived snapshots of past elections, to set the model's parameters. |
| `run.sh` | The election-night loop: fetch, project, publish. `manual` mode watches `snapshots/` instead. |
| `publish.sh` | Commit `docs/projections.json` and push, which updates the live site. |
| `config.json` | Election URL, contest-name patterns to skip, expected total ballots, shift parameters. |
| `fixtures/sample_index.html` | A made-up page in the shape the parser expects, used for self-testing. |

## Fetching: the department blocks scripted clients

`sfelections.org` sits behind CloudFront with a firewall that returns `403` to non-browser
clients, from cloud and home addresses alike. So `fetch_browser.py` loads the page in the Chrome
installed on your laptop, through Playwright, and saves the HTML into `snapshots/`. The page it
reads is https://www.sfelections.org/results/20261103/index.html, the inner results page (the
public URL with `20261103w` is just a shell that iframes it).

```bash
pip install playwright
./run.sh            # fetch, project, publish every 3 minutes
```

If the browser route fails, `./run.sh manual` instead watches `snapshots/` for pages you save
from the browser yourself (Cmd+S, "Webpage, HTML Only"). Either way the loop rebuilds
`docs/projections.json` and pushes it. The site is served by GitHub Pages from the `docs/`
folder of this branch (repo Settings → Pages → Deploy from a branch → this branch, `/docs`).

The page exposes, and the parser reads: the report name ("Zero Report", "Election Night
Report 1", ...), Number of Ballots Cast, registration, precincts reported, next-update time,
each measure's pass threshold, and for ranked-choice contests a "Last Round" column once votes
exist. `fixtures/zero_report_20261103.html` is the real pre-results page; `fixtures/fake_batch1.html`
is the same page with random vote counts for testing.

## Which contests

`config.json` has `include` and `skip` regex lists. The default includes local measures, the
regional transit measure, Board of Supervisors, U.S. House, and the citywide offices; judicial
retention is skipped, and `project.py` drops uncontested races (one candidate plus write-in) and
multi-seat contests (Board of Education, Community College Board full term) on its own. Statewide
propositions are not included by default; add `"^PROPOSITION"` to `include` if you want SF's vote
on them.

To check a saved page by hand:

```bash
python3 scrape.py --from-file snapshots/<saved page>.html --dump-tables
python3 project.py
```

Then start the loop:

```bash
./run.sh
```

## The model

SF counts in a fixed order: mail ballots received before election day first (the 8:45 PM batch),
then election-day poll votes, then late-arriving mail and provisionals in daily 4 PM updates.
Later batches skew younger and more progressive, so the final share moves in a predictable
direction from the first batch. The projection is

```
final_yes_share = share_now + late_shift * remaining_fraction
remaining_fraction = 1 - ballots_counted / expected_total_ballots
late_shift ~ Normal(late_shift_mean, late_shift_sd)   # percentage points, per config.json
```

The "possible range" is the 95% interval of that, plus a sampling term that only matters in tiny
batches, with a floor of `min_half_width` so the needle never claims false precision.

`late_shift_mean` and `late_shift_sd` are placeholders (0 and 3) until calibrated. To calibrate,
save the index page for each batch of a few past elections (the dated `data/YYYYMMDD/` folders on
the department's site hold each release) into one directory per election and run:

```bash
python3 calibrate.py snapshots/20241105w snapshots/20240305w > shifts.csv
```

Group the shifts by contest type (citywide measures vs. district races) and take the mean and
standard deviation of each group. Set the sign per contest: a positive shift means late ballots
favor Yes.

The "% counted" figure divides ballots cast by `expected_total_ballots`, or if that is null by
registration (read from the page) times `expected_turnout`. Replace it with the department's
ballots-remaining estimate once they publish it on election night.

## Ranked-choice races

The summary page's ranked-choice tables gain "Round 1" and "Last Round" columns once votes exist.
The parser uses the Last Round column when present, so the needle shows the final-round top-two
margin; before that it shows first choices and the card says so. The scraper already records the links to the data files it sees
(`data_links` in `results.json`), which is where the RCV report will be.
