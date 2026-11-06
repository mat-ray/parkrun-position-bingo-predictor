# Design & decisions

The *why* behind the Position Bingo Predictor. See [`requirements.md`](requirements.md)
for the *what* and [`weather-hypothesis.md`](weather-hypothesis.md) for the
weather research in full.

## Guiding principle: measure, don't assume

Almost every design choice came from testing an assumption against the real
data rather than hard-coding a belief. Weather effects, drop-out skew, the wind
threshold, the odds &mdash; all were measured per event, and features only apply
where an event's own history supports them. This keeps the tool honest: it
never pretends to know something the data doesn't show.

## Architecture: collector (offline) + app (static)

Two deliberately separate halves:

- **Collector** (`collector/`, Python, run occasionally): turns saved results
  pages into a compact dataset. Pipeline: `ingest` (route new files) &rarr;
  `parse_results` &rarr; `weather` (Open-Meteo, cached) &rarr; `aggregate`
  (compute bands, seasonal curves, weather model, odds) &rarr; `build` (bundle).
- **App** (`app/`, static HTML/CSS/JS): loads the bundle and does the UI + light
  maths. No build tooling, no framework, no backend.

`./publish.sh` runs the whole pipeline then optionally serves the app for the
phone to pull.

### Why no server / offline-first

The only reason a server was ever involved is that the app `fetch`es its data,
and browsers block `fetch` from `file://`. So `build.py` also bakes everything
into `app/data.js` (a `window.PBP_DATA` global loaded via `<script>`), letting
the app run with no server at all &mdash; double-clicked, or installed as a PWA
with a service worker caching the shell. The core app never needs the internet.

**Cache-first is a hard rule.** The service worker serves the shell from cache
first (never network-first on navigation &mdash; that caused a blank-screen hang
when the laptop was off). And the weather forecast, being an optional
enhancement, is fetched in the **background**: a prediction renders instantly
from cached data, then re-renders with the weather nudge only if the forecast
arrives. Weather must never block or delay a result.

## The core model: a time&harr;position curve per event

For each event we build, per finishing position, the distribution of times that
historically produced it &mdash; stored as a band (p25/p50/p75) plus a
volatility rating. That *is* the event's "curve": position &rarr; expected time,
with spread. Predictions read straight off it.

Two refinements, both measured:

- **Seasonality.** Field size (and thus the curve) shifts through the year, so
  we pre-compute the band per ISO week over a &plusmn;3-week window. The app uses
  the band for the target Saturday's week, falling back to all-year when a week
  is too sparse.
- **Spread, not a point.** A target time doesn't pin one position; it spreads
  over ~20&ndash;30. This underpins the opportunity view and the odds (both
  reason about the *range* of positions a time produces, not a single place).

## The weather model: per-event, self-calibrating

Hypothesis: bad weather &rarr; fewer runners &rarr; a given time lands a better
position. Tested and **validated for rain and strong wind, but not uniformly**,
and crucially **it differs by event** &mdash; so a single global model would be
wrong. Each event carries its own measured weather sensitivity; weather-proof
events self-calibrate to ~nothing.

Key findings baked into the model:

- **Rain is binary, not dose-dependent.** People decide "is it raining?", not
  "how many mm?". A per-mm slope extrapolated absurdly; we use wet-vs-dry.
- **Wind only bites when strong.** Field size is flat until ~**20 km/h**, then
  drops &mdash; a threshold inferred from the data, not guessed.
- **Drop-outs are skewed to the back.** Fast regulars turn up regardless;
  casual/slower runners stay home. So the time penalty **grows linearly with
  position** (`penalty ≈ slope × position`), fitted through the origin per
  event. The front of the field barely moves; deep positions move a lot. We
  store one **wet slope** and one **windy slope** (seconds per place) per event.
- **Only the deviation from normal counts** &mdash; the seasonal baseline already
  contains typical weather, so we only adjust when the forecast deviates from
  the week's norm.
- **Wet AND windy:** too few such days to fit directly, and the skip-crowds
  overlap, so we take the stronger slope **+ 25% of the weaker** (not the sum).
- Adjustments are damped (&times;0.6) and capped, so they nudge, never overcorrect.

### How each current event fits the hypothesis

Measured wet/windy slopes (seconds of easing per finishing place):

| Event | ~field | wet slope | windy slope | reading |
|---|---|---|---|---|
| Littlehampton Prom | 322 | **0.78** | **0.74** | most weather-sensitive &mdash; flat, exposed seafront |
| Kingston | 375 | 0.43 | 0.43 | clearly sensitive (the reference case) |
| Bournemouth | 532 | 0.26 | 0.25 | moderate |
| Crane Park | 182 | 0.00 (gated) | 0.39 | rain-proof (small committed field); some wind effect |
| Bushy / Downs Link / North Farm / Worthing | &mdash; | &mdash; | &mdash; | too few events yet; no weather model until they build history |

The pattern is physically sensible &mdash; exposed seafront courses
(Littlehampton, and likely Worthing/Bournemouth) are more weather-deterred than
a sheltered riverside park with a committed regular field (Crane) &mdash; which is
a good sign the model measures something real rather than noise.

### Forecast at predict time

For a target within ~7 days, the app fetches the 9am forecast from Open-Meteo
(the historical API feeds the model at build time; the forecast API feeds the
live adjustment). Beyond a week, or offline, it simply shows the normal seasonal
prediction and says so.

## The odds estimate

"How much does aiming actually help?" is answered by a build-time Monte-Carlo
over each event's real history: for a random card of *k* needed numbers, aim at
the best target and replay it against real past events to see how often it ticks
something. This captures genuine week-to-week scatter (an earlier
percentile-band approximation was too optimistic and was discarded). Result: the
tool helps most near the end (last number ~6% aimed vs ~1% random), less when
many numbers remain.

## Data collection & the scraping stance

parkrun blocks automated access (plain requests get a 403; it's a User-Agent
check). We respect that for the bulk data: **results are collected by the user's
own browser / iOS Shortcut**, saved as files the collector parses locally. The
tool never scrapes results.

The one exception is a **single one-off coordinate lookup per new venue**: the
`/course/` page carries a `geo.position` meta tag, fetched once with a browser
User-Agent when onboarding an event. This is a deliberate, bounded crossing of
the line (one request, one public datum, per venue &mdash; never weekly, never
results), recorded in `data/locations.json`.

### How cancellations show up in the data (and how we handle them)

parkrun is inconsistent about cancelled events, and it matters for collection:

- **Event numbers are only assigned to events that actually ran.** The sequence
  `#1..#latest` is **contiguous** &mdash; a cancelled week consumes **no** number.
  So a gap in event *numbers* means a results page we haven't captured yet, not a
  week that didn't happen.
- **A cancelled week has no reliable date URL.** Depending on whether anyone
  scanned a barcode that morning, the date URL either:
  - serves a **`| CANCELLED`** shell (someone &mdash; usually a volunteer &mdash;
    scanned, so parkrun created a results record with zero finishers), or
  - **404s** ("page not found": nobody scanned, so no record was ever made).
  Both mean the same thing: no timed event that week. Which one you get is a
  volunteer-behaviour accident, not a parkrun policy.
- **`latestresults/` redirects to the newest event that *ran*.** It never 404s
  for a cancelled Saturday &mdash; it just lands on the previous real event. A
  recurring "grab latest" collector therefore re-serves the previous week's page
  on a cancelled week; the de-dup in `ingest.py` (keyed on the **date inside the
  page**, not the fetch date) discards it, so cancellations never duplicate and
  never pollute the dataset.

**Consequence: you can *infer* every cancellation without fetching anything.**
Each held event's page carries both its event number and its date, so given a run
of events we know both. The rule:

| | Numbers contiguous | Number gap |
|---|---|---|
| **Dates weekly** | complete, no cancellations | (shouldn't occur) |
| **Date gap** | **inferred cancellation** &mdash; the skipped Saturdays genuinely had no event | **missing save** &mdash; go fetch the absent numbers |

Number-contiguity is the precondition: only when no event numbers are missing
across a span does a date gap unambiguously mean "cancelled". `parse_results.py`
does exactly this &mdash; after writing the dataset it reports (a) event-number
gaps (missing saves), and (b) date gaps classified as either *inferred
cancellations* (numbers contiguous) or *missing saves* (numbers absent). It also
recognises saved `| CANCELLED` and 404 pages as no-event weeks rather than
treating them as broken saves to re-fetch. None of this changes the predictor's
maths &mdash; cancellations are simply weeks with no data &mdash; but it makes
coverage legible so you can tell "I'm missing a page" from "the event didn't run".

## Decisions considered and rejected

- **Global weather model** &rarr; rejected; events differ too much (Crane vs
  Littlehampton). Per-event self-calibration instead.
- **Per-mm rain slope** &rarr; rejected; extrapolated nonsensically. Binary
  wet/dry.
- **Uniform drop-outs across the field** &rarr; rejected; measured skew is
  position-linear.
- **Adding wet+windy slopes** &rarr; rejected (double-counts overlapping
  crowds); stronger + 25% of weaker.
- **Forecast blocking the prediction** &rarr; rejected; it caused offline hangs.
  Background fetch + re-render.
- **Odds from percentile bands** &rarr; rejected as too optimistic; Monte-Carlo
  over real history instead.
- **Scraping results with a script** &rarr; rejected; against parkrun's wishes
  and fragile. User's browser/Shortcut does it.
- **Temperature as a weather input** &rarr; rejected; its apparent effect was
  just seasonality the &plusmn;3-week window already captures.

## Key files

```
collector/
  ingest.py          route latestresults/ into event folders; coords; cleanup
  parse_results.py   saved pages -> data/raw/<slug>.json (cancelled/404/bot-check handling; number- & date-gap report)
  weather.py         Open-Meteo historical 9am weather, cached
  aggregate.py       bands, seasonal curves, weather slopes, odds -> app/data/<slug>.json
  fetch_location.py  one-off course-page coordinate lookup
  build.py           discover events, run pipeline, write bundle + standalone
app/
  index.html app.js style.css sw.js   the PWA
  data.js            generated bundle (window.PBP_DATA)
  index.standalone.html               generated single-file build
data/
  raw/ weather/ locations.json        intermediate + config data
publish.sh           ingest + build + optional serve (--no-serve, --serveN)
```
