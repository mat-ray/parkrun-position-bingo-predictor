# Parkrun Position Bingo Predictor

Work out which **finish times** to aim for in order to land on the finishing
**positions** that tick off numbers on your Parkrun **Position Bingo** card
(00&ndash;99, where position 3 / 103 / 203&hellip; all tick "03").

It learns from past finish data for your event, so a time maps to a realistic
position for *that* event.

## How it fits together

There are two parts, kept separate on purpose:

1. **Collector** (`collector/`, Python, offline) &mdash; turns saved results
   pages into a compact dataset the app reads. You run this occasionally.
2. **Web-app** (`app/`, static HTML/CSS/JS) &mdash; loads that dataset, you pick
   your bingo numbers, it gives you target times. Runs on laptop and phone,
   works offline once loaded.

The app never scrapes Parkrun. You provide the data by browsing normally and
saving pages, which keeps everything within Parkrun's terms.

## Getting data (the weekly habit)

For each results page you want to include:

1. Open the event's results page in Safari
   (e.g. `https://www.parkrun.org.uk/kingston/results/788/`).
2. **File &rarr; Save As &rarr; Format: Page Source** and save the `.html` into
   the event's folder (e.g. `Kingston/`). The filename doesn't matter.

Collect as many weeks as you can. Finish position vs. time shifts with the
seasons (bigger summer fields, thinner fields in bad weather), so:

- **1 year** = covers the seasonal cycle once.
- **2&ndash;3 years** = recommended, so each week has several samples and
  one-off oddities average out.

To add a **new event**, make a new top-level folder (e.g. `Bushy/`) and drop its
saved pages in there.

## Building the dataset

Event folders live under `raweventdata/<slug>/`, where `<slug>` is the parkrun
URL slug (e.g. `crane`, `kingston`). The easiest flow is `./publish.sh` (below),
which ingests, builds, and serves in one go. To build only:

```bash
python3 collector/build.py
```

This parses every event folder, aggregates, and writes:

- `data/raw/<slug>.json` &mdash; raw parsed finishers (audit / reuse)
- `app/data/<slug>.json` &mdash; compact lookup the app loads
- `app/data/manifest.json` &mdash; list of events for the app's dropdown
- `app/data.js` &mdash; the bundle the app loads; `app/index.standalone.html` too

It's idempotent &mdash; re-run it any time you add more saved pages.

### Weekly updates (`./publish.sh`)

Drop this week's downloaded result files into `latestresults/` (filename starting
with the event slug, e.g. `crane-2026-10-31.txt`), then:

```bash
./publish.sh                # ingest + build + serve 10 min on :8777
./publish.sh --no-serve     # ingest + build only (e.g. from an iOS Shortcut)
./publish.sh --serve30      # serve for 30 minutes (1-360)
./publish.sh --serve5 9000  # combine: 5 min on port 9000
```

`publish.sh` first **routes** each file in `latestresults/` to its event folder
under `raweventdata/` (by the slug in the filename), creating a folder for a new
event, skipping duplicates, and quarantining junk. If anything looks off it
prompts before building. Both `crane-2026-10-31.txt` and `crane 31 Oct 2026.txt`
filename styles are accepted.

New events need their start coordinates for the weather feature. Coordinates
live in `data/locations.json` (slug &rarr; lat/lon/placename). The build prints a
reminder for any event missing them.

To add a new event's coordinates (once per venue):

```bash
python3 collector/fetch_location.py <slug>      # e.g. crane
```

It reads the `geo.position` meta tag parkrun embeds on every `/course/` page and
records it in `data/locations.json`. It's a single one-off request per new venue
(sending a normal browser User-Agent, since parkrun 403s obvious bot requests),
and it skips any slug already recorded. Weekly *results* collection still uses
your own browser/Shortcut &mdash; this tool only makes this one small lookup when
you onboard a venue. If you'd rather not have it fetch, save the course page
yourself and run `fetch_location.py --file saved.html --slug <slug>`.

The collector is defensive about bad saves. At the end of a run it reports:

- **Missing events** &mdash; gaps in the event-**number** sequence. Numbers are
  contiguous across cancellations, so a number gap means a page you haven't
  captured yet &mdash; re-fetch these.
- **Inferred cancellations** &mdash; date gaps where the event *numbers* either
  side are contiguous, so the skipped Saturdays genuinely had no event. Nothing
  to fetch; derived purely from the dates in the pages you already have.
- **Date gaps that are missing saves** &mdash; date gaps where some event numbers
  are absent, so it's a data hole, not a cancellation. Fetch those numbers.
- **Weeks with no event** &mdash; any `| CANCELLED` or 404 "page not found" pages
  you saved for cancelled Saturdays (no results; noted, nothing to fix &mdash;
  re-fetching a cancelled/404 week never yields results).
- **Files needing attention** &mdash; empty/tiny saves, bot-check (rate-limit)
  interstitials, or truncated pages. Re-fetch these.

Because `latestresults/` redirects to the most recent event that *ran*, a
cancelled week re-serves the previous event's page; de-dup keys on the date
*inside* the page, so those are discarded rather than duplicated.

Empty and bot-check files are quarantined automatically, so they never pollute
the dataset. Leaving an empty file in place is a fine way to remind yourself to
re-fetch that week.

## Running the app

**Just double-click `app/index.html`.** No server needed. `build.py` bundles the
data into `app/data.js`, which the page loads directly, so it works straight
from `file://` and offline. After running `build.py`, reopen (or refresh) the
page to see new data.

**On your phone:** copy the `app/` folder to the phone (AirDrop, iCloud Drive,
etc.) and open `index.html`. Since the data is bundled in, there's nothing to
fetch &mdash; it runs offline.

### On an iPhone (recommended: single self-contained file)

This is the right way to get a reliable, offline home-screen app. `build.py`
writes a **single self-contained file**, `app/index.standalone.html`, with the
CSS, JS **and the whole data bundle inlined** &mdash; so it has no external
dependencies and nothing to fetch. It cannot hang or time out, with or without
the Mac, on any network.

Because the project folder syncs via iCloud, that file is already on your phone.
To launch it with one tap:

1. Open the **Shortcuts** app and make a new shortcut.
2. Add **Get Contents of File** and point it at
   `.../app/index.standalone.html` in iCloud Drive (browse to it; don't type a
   path &mdash; the phone's path differs from the Mac's).
3. Add **Show Web Page** and pass it the file contents.
4. Add the shortcut to your Home Screen.

It runs fully offline. Re-run `build.py` after adding data, let iCloud sync, and
the shortcut picks up the new version. You can also AirDrop or email the single
file anywhere and open it the same way.

> **Don't install the PWA from the Mac's IP address.** Tapping *Add to Home
> Screen* on `http://<mac-ip>:8777/` pins the app to that origin, so every cold
> launch tries to reach the Mac &mdash; and stalls/times out when the Mac is
> asleep, the 10-minute serve window has expired, the IP has changed, or you're
> on a different network. It looks installed but it isn't really offline. Use the
> single-file approach above instead.

### Optional: run it as a local server (dev preview, Mac must stay up)

Handy for quickly previewing a rebuild on another device over Wi-Fi **while the
Mac is on** &mdash; not for day-to-day phone use (see the warning above):

```bash
./serve.sh            # http://localhost:8777
./serve.sh 9000       # different port
```

The app uses the bundled `data.js` when present and falls back to `fetch()` of
`data/*.json` when served, so either way works.

## Using it

1. Pick your event.
2. Pick the **Saturday you're aiming for** (defaults to the next upcoming
   Saturday). With "weight by time of year" on, the predictor leans on events
   within &plusmn;3 weeks of that calendar week (pooled across years), so the
   time&rarr;position mapping reflects the turnout you'll actually face &mdash;
   quieter winter fields let you run a bit slower for the same position, busier
   summer fields need you faster. If a window doesn't have enough nearby weeks
   yet (&lt; 5 samples) it falls back to the whole-year picture and tells you.
3. Tap the bingo numbers you still need.
4. Optionally set your realistic pace range to hide positions you can't reach.
5. **Show target times** &mdash; for each number you get every finish position
   that would tick it, and for each position:
   - an **aim band** (25th&ndash;75th percentile of the times that historically
     produced that position) plus a median "aim" time,
   - the **full range** ever seen at that position,
   - a **volatility** rating (Low / Medium / High, with the typical &plusmn;
     swing) showing how reliably a given time lands you there,
   - a **best bet** flag on the position you can most dependably hit.

At the top you get a summary with two complementary strategies:

- **Your best bets** &mdash; the three most *reliable* single targets (lowest
  volatility, tightest band), best first. Use these when you want to nail a
  specific number.
- **Best chance of ticking something** &mdash; a target chosen for *coverage*. A
  finish time doesn't land you on one position; across events it spreads over a
  range of positions. If your needed numbers sit close together (common early in
  the challenge), aiming at the middle of a cluster means even a few places of
  drift still ticks *something*. This callout picks the time whose likely finish
  spread overlaps the most of your needed cells, names them, and gives the rough
  hit chance. Position adjacency wraps the card (finishing near 100 can tick 99,
  00, 01&hellip;), so century boundaries count too. It only shows when a single
  run could plausibly catch two or more of your numbers.

Your selection is **saved automatically** in the browser (per event), along with
your target date, seasonal toggle, and pace range. Come back later &mdash; even
after closing the tab or the browser &mdash; and your card is right where you
left it. **Reset saved** clears it and starts a fresh card. Saving is local to
the browser/device, so it works offline and nothing leaves your machine.

Volatility needs a few events to mean anything: with one event a position shows
"one event only", with two it's "not enough data", and from three it becomes a
real Low/Medium/High rating. As a rule the deeper into the field a position is,
the more its time swings with weekly turnout &mdash; the ratings make that
visible so you can pick a target you can actually rely on.

## Roadmap

- **Weather / turnout (phase 2):** join historical weather by date, model how
  field size responds to conditions, and shift the time&rarr;position mapping
  for a given forecast. The data model already records field size per week to
  support this.
- **Seasonal targeting:** aim for a specific future Saturday and weight the
  prediction toward the weeks around that date.
- **More events:** already supported &mdash; just add folders and rebuild.

## Project layout

```
.
├── Kingston/                 # saved .html results pages for Kingston
├── collector/
│   ├── parse_results.py      # saved HTML  -> data/raw/<slug>.json
│   ├── aggregate.py          # raw         -> app/data/<slug>.json
│   └── build.py              # run everything + write manifest
├── data/raw/                 # raw parsed data (generated)
├── app/
│   ├── index.html            # the web-app
│   ├── style.css
│   ├── app.js
│   └── data/                 # compact data the app loads (generated)
├── serve.sh                  # local web server (laptop + phone)
└── README.md
```
