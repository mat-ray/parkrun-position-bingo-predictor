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

### Rough first step, when picked up

Ship **Level 1 only**, local, with a one-tap logging flow and a single honest
"your aimed hit-rate" number. Prove the data-entry flow is frictionless before
even considering Level 2.

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
