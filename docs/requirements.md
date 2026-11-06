# Requirements

What the Parkrun Position Bingo Predictor is and does. Companion to
[`design.md`](design.md) (the *why*) and [`weather-hypothesis.md`](weather-hypothesis.md)
(the weather research).

## The problem

parkrun's **Position Bingo** challenge is about the finishing **position** you
get, not your time. The card is 00&ndash;99; a finish in position P ticks the
cell `P mod 100` (so 3 / 103 / 203&hellip; all tick **03**; 100 / 200&hellip;
tick **00**). You want to fill all 100 cells.

Your position depends on how fast everyone else runs that day, which you can't
control directly &mdash; but you *can* aim for a finishing **time** that tends to
land you in the positions you still need. This tool learns that time&harr;position
relationship from an event's past results and tells you what to aim for.

## What it does

- **Per-event prediction.** For a chosen event, for each bingo number you still
  need, show the finishing position(s) that would tick it and the **time band**
  to aim for (25th&ndash;75th percentile of historical times at that position),
  with a median "aim" time and a **volatility** rating (how reliably a time
  lands you there).
- **Best bets.** A summary of the three most reliable targets across your
  needed numbers.
- **Opportunity view.** Because a target time spreads you across ~20&ndash;30
  positions, it highlights the target whose spread overlaps the most of your
  still-needed cells (best chance of ticking *something*).
- **Odds estimate.** The estimated weekly chance of ticking a needed number if
  you aim well, vs. just turning up &mdash; from a simulation over the event's
  real history. Helps most near the end of the challenge (last number ~6% aimed
  vs ~1% random; the lift shrinks when many numbers remain).
- **Seasonal weighting.** Field size (hence position&harr;time) shifts through the
  year, so predictions weight toward events within &plusmn;3 weeks of the chosen
  Saturday.
- **Weather adjustment.** For the upcoming Saturday (within ~7 days), fetch the
  forecast and, if rain or strong wind is expected, ease the target times &mdash;
  per-event and self-calibrating (see `design.md` / `weather-hypothesis.md`).
- **Multiple events.** Pick between events; the bingo card is shared across all
  of them (a number is a number wherever you get it).
- **Edge cases.** All 100 numbers needed &rarr; "just run, you're guaranteed a
  tick". Sparse events (&lt; 52 results) &rarr; shown with an "early data" caveat.

## Non-functional requirements

- **Offline-first.** The app is a static bundle that runs with no server (double
  click, or installed as a PWA). It must open and predict instantly with no
  network. Weather is an *optional enhancement* fetched in the background &mdash;
  it must never block or delay a prediction.
- **No scraping of results.** parkrun results are collected by the user's own
  browser/iOS Shortcut (parkrun blocks automated access). The tool itself only
  ever makes two kinds of network request: the weather APIs (Open-Meteo), and a
  single one-off coordinate lookup per new venue.
- **Data stays local.** Nothing is uploaded; saved card/settings live in the
  browser (localStorage).
- **Self-calibrating.** Every event is modelled from its own history; features
  that aren't supported by an event's data (e.g. weather for a weather-proof or
  brand-new event) simply don't apply, rather than being forced.

## Inputs & outputs

- **Input:** saved results pages per event (`.txt` or `.html`), one folder per
  event under `raweventdata/<slug>/`; new weekly downloads dropped in
  `latestresults/`.
- **Generated:** `app/data.js` (the bundle the app loads) and
  `app/index.standalone.html` (a single self-contained file). Raw parsed data in
  `data/raw/`, weather in `data/weather/`, coordinates in `data/locations.json`.

## Current events (at time of writing)

| Event | events | ~field | weather model |
|---|---|---|---|
| Bournemouth | 157 | 532 | yes (moderate) |
| Crane Park | 151 | 182 | wind only |
| Kingston | 154 | 375 | yes |
| Littlehampton Prom | 151 | 322 | yes (strongest) |
| Bushy | 1 | 1700 | not yet (sparse) |
| Downs Link | 1 | 161 | not yet (sparse) |
| North Farm | 3 | 265 | not yet (sparse) |
| Worthing | 1 | 618 | not yet (sparse) |
