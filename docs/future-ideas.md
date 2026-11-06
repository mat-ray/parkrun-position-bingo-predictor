# Future ideas — a backlog, not a plan

A place to bank ideas worth doing later, with enough reasoning (and caveats)
that picking one up doesn't start from a blank page. Nothing here is built or
committed to; see [`design.md`](design.md) for what the live app actually does
and [`requirements.md`](requirements.md) for the current scope.

---

## Outcome tracking — close the prediction loop

Today the app predicts but never learns whether a prediction was any good. It
tells you "aim for ~25:50 to finish around 111 and tick 11" and then never hears
what happened. Recording the outcome turns a one-way predictor into something
that can show how well aiming actually works **for you**, on your real results.

Two levels, deliberately separated — very different effort/value profiles.

### Level 1 — lightweight outcome log (high value, low effort, fully local)

After a run, log: the numbers you were aiming at, the target time/position, and
what actually happened (your finish position; which needed numbers ticked).
Stored in `localStorage` alongside the existing card — no backend, stays within
the offline-first design.

What it unlocks:

- **Personal hit-rate** — "you ticked an aimed-for number X% of the time",
  grounded in your own history rather than only the build-time Monte-Carlo
  estimate. An honest, concrete answer to "does aiming help *me*?".
- **Calibration check** — compare target position vs. actual position. If you
  consistently finish ~10 places ahead of the aim, that's a systematic bias the
  app could surface (and later correct).
- **History / streaks** — mildly fun, and makes the card feel alive.

### Level 2 — feed outcomes back into predictions (high value, higher risk)

Use logged outcomes to adjust predictions — e.g. a personal pace/position
offset, or weighting. Treat as research, not a quick add:

- One person's handful of runs is **tiny data** — easy to overfit.
- The model is deliberately *per-event* and *measured, not assumed*
  (see `design.md`). A personal-adjustment layer must respect that and
  self-calibrate to ~nothing when the data doesn't support it, like the weather
  model does.

### Caveats to remember (why this is subtler than it looks)

- **Position isn't fully in your control.** You aim at a *time*; the *position*
  depends on who turns up. So "did I hit my number?" blends prediction accuracy
  with the day's field. Track BOTH target-time-vs-actual-time AND
  target-position-vs-actual-position to separate "I ran the wrong time" from
  "the field was unusual".
- **Data-entry friction kills it.** Only worth building if logging a result is
  nearly effortless — pre-filled from the card you already had selected, ideally
  one tap ("ticked / didn't"). A form nobody fills in is worse than nothing.
- **Privacy / sync.** Local-only keeps it simple and on-architecture. Cross-
  device history would need a backend the project has so far avoided — probably
  not worth it just for this.

### Auto-reconcile from the next results refresh (removes most data-entry friction)

**The core outcome needs nothing but the runner's position — which they always
have.** Bingo ticks are a function of *position* alone (108 -> ticks 08), and
the runner knows their position the moment they see their result. So "did I tick
the number I was aiming for?" is answered instantly, offline, with no results
refresh, no lookup, no identity: the user says "I finished 108th", the app
already knows what they were aiming at, and it reconciles on the spot.

Important: the user enters their **actual position (e.g. 108)**, not the mod-100
bingo cell — the app does `pos % 100` itself. Don't make them pre-mod it:

- The mod is **lossy** — "I got 8" can't distinguish 8th / 108th / 208th, and
  that difference is exactly the signal the calibration add-on needs (8th and
  108th are very different times). Keep the full position.
- For the tick itself, mod is all that matters (108 and 8 both tick 08), but the
  runner has the full number anyway, so there's no reason to make them compute
  the mod.
- Edge case to preserve: `pos % 100 == 0` maps to bingo cell **00** (100, 200…
  all tick 00), matching the existing `candidatePositions` convention in the
  app. Use the same `% 100` mapping on reconciliation so 100 never mis-ticks.

Entering a *time* (an earlier draft of this note) is unnecessary for the bingo
outcome — time doesn't determine the tick, position does, and position is the
thing the runner has in hand. Time only matters for the *secondary* calibration
question below.

Where a post-refresh lookup actually earns its keep is **calibration** — a
different question: "was the app's *time* advice any good?" e.g. "we told you to
aim 25:50 for ~111th; you ran 25:58 and finished 108th." Answering that needs
the week's actual position<->time curve, which comes from the next
`latestresults` refresh. It's a nice-to-have on top of the core, not a
prerequisite for it.

Identity (matching *which finisher was you* automatically by parkrun athlete ID)
is a further, optional step — and the one with a real cost; see below.

**Hard constraint / privacy fork (don't cross this by accident):** the collector
*deliberately strips names and athlete IDs*. A raw finisher record is only
`{position, time_seconds, gender, age_group}`, and the shipped bundle is purely
statistical (per-position bands — individual finishers aren't even in it). So:

- The **core bingo outcome** needs no data beyond the user's position — fully
  PII-free and needs no refresh at all.
- The **calibration add-on** needs that specific event+date's actual
  position->time results available to the app (the raw data has this; the
  *shipped bundle* currently doesn't — it ships aggregated bands only). Modest,
  PII-free data change.
- **Auto-matching by athlete ID requires the pipeline to START keeping
  names/IDs** — a reversal of the privacy-preserving design, and on the *public*
  GitHub Pages host it would mean
  **publishing identifiable per-runner results.** That's a policy decision, not
  a feature toggle. Prefer A or B unless there's a strong reason.

### Rough first step, when picked up

Ship the **core bingo outcome first: "enter your finishing position"**, local
and identity-free — no refresh, no new data needed. The app already knows what
you aimed at, so it can say immediately "you ticked 08, which you were aiming
for" and keep a running "aimed hit-rate". This is the whole value with none of
the cost.

Only then consider the **calibration add-on** (did the *time* advice land you
where predicted?), which needs the week's position->time results shipped to the
app after a refresh — still PII-free, just a small bundle extension. Leave
auto-matching by athlete ID (with its privacy cost) and Level 2 (feeding
outcomes back into predictions) for last, if ever.

---

## PWA update experience

Observed in practice: iOS PWAs serve the cached shell aggressively and only pick
up a new service worker on a full app restart (sometimes the *second* launch —
new SW installs on one launch, activates on the next). The cache-version bump in
`publish.sh` + the version line in the About popup make this *visible*, but the
update still isn't automatic.

Possible improvement: on launch, call `registration.update()`, and when a new
worker is waiting, `skipWaiting()` + reload so updates apply on next launch
without a manual quit-and-reopen. It's a behaviour change to the update flow, so
weigh it against the risk of reloading mid-use.
---

## Garmin / Connect IQ — live predicted finishing position

Garmin watches run **Connect IQ** apps in **Monkey C** (free SDK). Of the app
types (watch face / data field / widget-glance / device app), the compelling one
here is a **data field**: it drops into an existing activity screen — e.g. a
custom "parkrun" Run profile — and shows a live value as you run. The idea:

> As you run, map your projected finish time to a **predicted finishing
> position** from the event's own history, updating each second. "At this pace
> you're on for ~92nd."

### Why this is a good fit (and cheaper than it first looks)

- **The hard half is already built.** `aggregate.py` produces a per-position
  time curve per event, and we made it **monotonic**, so inverting it
  (projected *time* -> *position*) is clean and unambiguous. The watch doesn't
  model the field; it just reads a curve the other way.
- **The watch already provides the live inputs for free.** A data field gets
  `Activity.Info` each second (elapsed time, distance, current pace). Project
  the finish honestly as `projected = elapsed + (5000 - dist) * current_pace`
  (converges as you progress; avg-pace alone is noisy early). Then look up
  `projected` in the curve -> position.
- Note the data we have is finish *time* per position (= avg pace over 5 km for
  that position), **not splits** — so the watch must project *your* finish from
  *your* run so far; the curve only does the time->position step.

### Event auto-detect from GPS (removes the only friction)

Picking the event by hand on a watch is miserable. Instead: we already store
each event's start coordinates in `data/locations.json` (for weather). A data
field can read `Position.getInfo()`, so on activity start it picks the **nearest
known start** within a few hundred metres. parkrun starts are geographically
distinct, so this identifies the event with zero input. No fix / not near any
known start -> show nothing. (parkrun gives you a GPS fix before the off anyway.)

### Optional weather — use if present, never assume

Connect IQ exposes `Toybox.Weather` (e.g. `getCurrentConditions()`), populated
from the **last phone sync** — so it can be null (never synced, stale, or
unsupported device/firmware). Design: *attempt it; on null / missing field /
stale timestamp, silently fall back to the no-weather curve.* If present and
fresh, feed it into the **per-event wet/windy slopes the pipeline already
emits** — same model as the phone app, just a different forecast source. Rain
maps to the binary wet flag (the model treats rain as binary anyway), wind to
the threshold. A couple of multiplications; negligible cost.

> **Assumptions to verify before building** (stated, not confirmed): the exact
> `Toybox.Weather` fields available (precip amount vs. condition code; wind
> units) and which devices/firmware support the API at all. Treat as unknown
> until checked.

### Architecture (keep the watch dumb)

1. **Pipeline emits a tiny watch bundle** per event: start lat/lon (already
   have) + a downsampled ~40-point `time -> position` curve (from the existing
   monotonic medians) + the event's weather slopes (already computed).
2. **On activity start:** GPS -> nearest event -> select that event's curve.
3. **Each second:** project finish time -> look up position -> display, with the
   optional weather nudge if `Toybox.Weather` is available and fresh.

### Constraints / gotchas

- **Memory is the binding limit** on a data field (can be very tight on older
  devices), not CPU. Hence a *downsampled breakpoint curve* for a handful of
  events, never raw finisher data or the whole bundle.
- **Early-run noise:** the projection swings for the first ~1 km — hide or smooth
  it until distance is meaningful.
- **One data field ~ one value.** "Predicted position" is the natural headline;
  showing position *and* projected time needs a field type that allows it.
- **Per-device rendering/limits** vary — target the specific watch model.
- No mid-run connectivity needed: everything (curve, coords, slopes) ships baked
  in; weather, if used, comes from the phone-synced cache, not a live fetch.

### Companion / thin-client note (non-data-field variants)

A glance/widget or device app could show "today's best target" at rest, as a
**thin client**: fetch a small precomputed answer from the Pages site rather
than running the model on-device. The bingo *card* (which numbers you need)
realistically stays on the phone (entering 100 cells on a watch is painful);
the watch reads the result. Same principle throughout: **server/pipeline does
the thinking, the device displays the answer.**
