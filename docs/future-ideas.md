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

Key realisation: we don't need the user to *type in* their result. After the
next `latestresults` refresh the app already has that event's finisher data, so
it can pull the missing half of the outcome back automatically. The user only
supplies the one thing the results data can't tell us: **which finisher was
them.** Three ways to bridge that, with very different privacy costs:

- **A. User enters their POSITION** ("I finished 108th on 2026-11-07"). The app
  looks up the time recorded at position 108 that week and which needed numbers
  108 ticked, then reconciles against the aim. Identity-free.
- **B. User enters their TIME** (which they always know from their watch / result
  text). The app does the inverse lookup — what position did that time land that
  week — and reconciles. Also identity-free, and *time* is the number a runner
  most reliably has to hand.
- **C. User enters their parkrun ATHLETE ID once**, app finds their row every
  week automatically. The frictionless dream — but see the hard constraint
  below.

**Hard constraint / privacy fork (don't cross this by accident):** the collector
*deliberately strips names and athlete IDs*. A raw finisher record is only
`{position, time_seconds, gender, age_group}`, and the shipped bundle is purely
statistical (per-position bands — individual finishers aren't even in it). So:

- A and B work with the data model as-is, except the app would need that
  specific event+date's actual position->time results available (the raw data
  has this; the *shipped bundle* currently doesn't — it ships aggregated bands
  only). Modest, PII-free data change.
- **C requires the pipeline to START keeping names/IDs** — a reversal of the
  privacy-preserving design, and on the *public* GitHub Pages host it would mean
  **publishing identifiable per-runner results.** That's a policy decision, not
  a feature toggle. Prefer A or B unless there's a strong reason.

### Rough first step, when picked up

Ship **Level 1, identity-free (option B: enter your time)**, local, with the app
auto-reconciling position + ticks after the next refresh, and a single honest
"your aimed hit-rate" number. This needs the per-event, per-week position->time
results shipped to the app (or fetched), which is a small, PII-free extension of
the bundle. Prove this frictionless flow before considering Level 2 (feedback
into predictions) or option C (identity, with its privacy cost).

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
