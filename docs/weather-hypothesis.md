# Weather hypothesis — findings & notes

Research note for a possible **v2** weather-aware predictor. Captures what we
tested, the numbers, and what a v2 should (and shouldn't) do. The live app was
**not** changed by this work.

## The hypothesis

Weather on the day shifts how a finishing *time* maps to a finishing *position*:

> bad weather → fewer runners turn up → a smaller field → a given time lands you
> in a better (lower) position than usual.

Weather is already *baked into* the historical results, and the app's
&plusmn;3-week seasonal window already captures the **typical** weather for a
time of year. So the only thing a weather feature can add is the effect of the
forecast **deviating** from that seasonal norm (e.g. "this Saturday is unusually
wet for early November"). Adjusting for typical weather would double-count.

## What we did

- Added `collector/weather.py` (Kingston only for now). It fetches 9am weather
  for every Kingston event date from the Open-Meteo Historical Weather API
  (free, no key), in a **single batched request** for the whole span, cached to
  `data/weather/` so re-runs make no further calls. Location: Kingston parkrun
  start by the Hawker Centre / Canbury Gardens (~51.4236, -0.3125).
- Joined 9am temperature, precipitation and wind onto all 154 Kingston events.
- Ran correlation / effect-size analysis. **No app or bundle changes.**

## Results (154 Kingston events, Oct 2023 – Oct 2026)

### Raw correlation with field size
| Variable | r vs field size |
|---|---|
| Temperature | +0.23 |
| Precipitation | **-0.36** |
| Wind | **-0.34** |

All in the hypothesised direction (warm = bigger, wet/windy = smaller).

### De-seasonalised (the honest test)
Comparing each event's **deviation** from its &plusmn;3-week seasonal norm
(weather deviation vs field deviation), which removes the baseline the app
already models:

| Variable | r (deviation) | Verdict |
|---|---|---|
| Temperature | +0.12 | **Mostly a seasonal mirage** — raw signal was the time-of-year pattern, not independent weather. |
| Precipitation | **-0.36** | **Robust.** Real effect beyond seasonality. |
| Wind | -0.28 | Real secondary effect. |

Practical magnitude of rain:
- On the 12 events **wetter than normal** for their week, the field was on
  average **~80 runners smaller** than the seasonal norm.
- On dry/normal days: +7 (essentially on the norm).
- ~80 fewer on a ~375 field ≈ a **~20% shrink**.

### Does a smaller field actually move times? (final link)
Finishing time at **100th place**, smallest-field third vs largest-field third:
- Large field (avg 454): 100th ≈ **24:08**
- Small field (avg 304): 100th ≈ **25:49**
- → you can run **~1:41 slower** and still place 100th in a small field.

## Conclusion

**Hypothesis validated — but driven by rain, not temperature.**

1. **Precipitation is the primary signal** (r = -0.36 after de-seasonalising).
2. **Wind is a genuine secondary signal** (r = -0.28).
3. **Temperature is largely redundant** with the seasonal window (+0.12) — a v2
   should not lean on it, to avoid double-counting seasonality.
4. The field → position → time chain is real and sizeable (~1:41 at 100th).

## Crane contrast — why the model must be per-event

Tested the same thing on Crane (now 125 events, back to Mar 2024). The weather
effect is **absent**:

| Event | n | precip r vs field | field change per mm rain |
|---|---|---|---|
| Kingston | 154 | **-0.35** | ~-90 runners |
| Crane | 125 | -0.01 | ~-1 runner |

Crane's turnout simply isn't weather-sensitive the way Kingston's is (likely a
smaller, more committed regular field, ~186 vs ~375). This held after Crane's
dataset grew from 87 to 125 events, so it's not a small-sample fluke.

**Conclusion: a single global weather model would be wrong.** The v2 model is
**per-event and self-calibrating** — each event carries its own measured
weather→field sensitivity (correlation + slope), and the adjustment is scaled to
it. Kingston gets a real adjustment; Crane gets ~none. This is baked into the
aggregated data as a `weather` block per event (sensitivity + per-ISO-week
weather norms), produced by `collector/weather.py` + `aggregate.py` and rolled
into the bundle by `build.py` (weather fetch is cached + fault-tolerant, so a
build never depends on the network).

## Final model (v2, as built): binary conditions

A per-mm "runners per millimetre" slope was tried first but rejected — it
extrapolated absurdly (a few mm of forecast rain wiped out most of the field).
That doesn't match behaviour either: people look out of the window and decide
"is it raining?", not "how many mm?". So the shipped model is **binary**:

- **Wet** = any measurable rain at 9am (precip > 0).
- **Very windy** = 9am wind ≥ **20 km/h**. This threshold was *inferred from the
  data*: binning dry-day field deviation by wind band showed field size is
  normal (even slightly up) below ~20 km/h and drops sharply above it:

  | 9am wind (dry days) | n | field vs seasonal norm |
  |---|---|---|
  | 0–10 | 62 | +16 |
  | 10–15 | 34 | +26 |
  | 15–20 | 15 | +1 |
  | 20–25 | 9 | **-59** |
  | 25+ | 2 | **-81** |

Per event we measure the **mean field difference** on wet-vs-dry and windy-vs-calm
days. Applied only when (a) the forecast condition deviates from what's normal
for that week, and (b) the measured deficit is ≥ 15 runners (noise floor).
Measured deltas:

| Event | rain-day field Δ | windy-day field Δ |
|---|---|---|
| Kingston | **-52** (32 wet days) | **-68** (22 windy days) |
| Crane | +2 (ignored) | -13 (ignored) |

Field delta → time via a measured seconds-per-runner, damped 0.6, capped at
±2:30. Kingston light rain ≈ +0:51 slower; rain + strong wind ≈ +1:59. Crane: no
adjustment (both deltas below the noise floor) — the per-event design keeps it
honest automatically.

## Drop-outs are skewed, not uniform (important correction)

The field-size model above implicitly assumed bad-weather no-shows are spread
evenly across the field. They are not. De-seasonalised wet-day time delta by
position (Kingston):

| position | wet-day time penalty |
|---|---|
| 10 | +0:13 |
| 50 | +0:28 |
| 100 | +0:33 |
| 150 | +1:00 |
| 200 | +2:18 |

The front barely moves; the back moves a lot. Interpretation: fast regulars turn
up regardless; casual/slower runners stay home. Wind shows the same shape.

**This fits a straight line through the origin** (`delta ≈ 0.44 × position`,
R² ≈ 0.55; quadratic adds nothing). Beyond ~70% of a typical field the data gets
noisy (thin wet days have few deep finishers), so we fit only up to that cap.

## Final shipped model: per-position time-penalty slopes

Replaces the field-size apparatus entirely. Per event we bake two slopes
(seconds added per finishing place), de-seasonalised, fitted through the origin,
and gated to **positive slopes with ≥8 condition-days** (a negative/weak slope =
no evidence => 0):

| Event | wet slope | windy slope |
|---|---|---|
| Kingston | +0.433 s/place | +0.428 s/place |
| Crane | 0 (gated) | +0.115 s/place |

At predict time: `penalty = slope × target_position × 0.6 (damp)`, capped at
3:00. So the deeper you aim, the larger the easing — matching the measured skew.

**Wet AND windy:** only 11 such days at Kingston (too few to fit a combined
slope directly), and the skip-crowds for rain and wind overlap heavily, so
adding the slopes would double-count. Instead: **stronger slope + 25% of the
weaker**. Example (Kingston, pos 100): rain ≈ +0:26, wind ≈ +0:26, wet+windy ≈
+0:32 — worse than either, well short of the naive +0:52 sum.

Triggers are binary (forecast wet = precip>0; very windy = ≥20 km/h) and only
when the forecast deviates from the week's seasonal norm. Crane self-calibrates
to ~nothing. UI: a toggle + a banner explaining the position-dependent easing.

## Implications for a v2

- Model the **precipitation (and wind) deviation** of the upcoming Saturday's
  forecast from the &plusmn;3-week seasonal norm → estimate a field-size shift →
  adjust predicted times/positions accordingly.
- Keep temperature out (or as a minor term only).
- Be transparent in the UI: show the deviation, the estimated field change, and
  the resulting adjustment (e.g. "forecast wetter than typical; field likely
  ~15% smaller; targets eased ~1:30"). No black box.
- Forecast source would be the Open-Meteo **forecast** API at predict time. The
  app is offline-first, so design carefully: either bake the upcoming forecast
  in at publish time, or fetch when online with a graceful offline fallback to
  the seasonal (no-adjustment) prediction.

## Caveats / open questions

- Single venue (Kingston). Crane (and other events) not yet tested; the effect
  size likely differs by venue and field size.
- 12 "wet" events is a smallish sample for the headline magnitude — directionally
  clear, but the exact -80 figure will firm up with more data.
- 9am point weather only; didn't test overnight rain, "felt" conditions, or
  forecast-vs-actual (people decide based on the *forecast*, which may differ
  from what actually fell at 9am — arguably the forecast is the better predictor
  of turnout and worth exploring).
- Correlation, not a fitted model. v2 should fit and cross-validate a simple
  field-size model before trusting any numeric adjustment.

## How to reproduce

```bash
python3 collector/weather.py      # fetch + join (cached after first run)
# then the analysis snippets used to produce the numbers above
```
