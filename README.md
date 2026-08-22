# MatVIX

MatVIX is a point-in-time, end-of-day market-state engine for the VIX options
insurance market.  It turns the Cboe volatility-index term structure, standard
monthly VX curve, VVIX, SKEW and SPX into:

- five transparent state axes: Carry Risk, Shock, Tail Price, Persistence and
  Repair;
- one deterministic market phase and a trader-readable evidence narrative;
- four event-specific 5/20-session probability questions with explicit
  eligibility, historical base rate, walk-forward OOF model status and
  calibration evidence.

It is a market weather station, not a price oracle and not a trading-order
generator.

## Reproducible environment

```bash
cd /Users/logan/MatVIX
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip install pytest==9.0.2 ruff==0.13.3 mypy==1.18.2
.venv/bin/python -m matvix doctor --project-dir .
.venv/bin/python -m pytest
```

Probability version `1.1.0` starts the regularized Logistic OOF after 252
completed event-specific samples, while retaining the 30/30 class minimum,
20-session purge and the separate 252-sample calibrated publication gate.
This makes all four real-data events testable; it does not make an
underperforming model publishable.

`scikit-learn==1.7.2` is part of the probability contract.  A different
runtime may calculate research outputs but cannot publish a formal calibrated
probability under the same probability version.

## Real-data rebuild

The locally accepted vendor snapshot is under `data/raw/vendor/` and is not
tracked by Git.  Verify its 183-file manifest before importing:

```bash
cd /Users/logan/MatVIX/data/raw/vendor
shasum -a 256 -c audit/SHA256SUMS.txt
cd /Users/logan/MatVIX
```

Then rebuild the normalized revision ledgers and state history:

```bash
.venv/bin/python -m matvix import-data \
  --cboe-dir data/raw/vendor/cboe \
  --cfe-dir data/raw/vendor/cfe \
  --spx-csv data/raw/vendor/spx_candidates/SPX_CBOE_2013_onward.csv \
  --spx-source CBOE \
  --project-dir .

.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities \
  --date 2026-08-18 --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real \
  --date 2026-08-18 --project-dir .
.venv/bin/python -m matvix export-dashboard \
  --snapshot outputs/daily/2026-08-18.json \
  --output outputs/dashboard.html --project-dir .
```

The required source snapshot ends with a complete F1-F7 curve on 2026-08-18.
Four missing SKEW observations and invalid CFE `Settle=0` values are preserved
as missing; the pipeline does not forward-fill them.

`accept-real` recomputes 13 business gates from the persisted raw ledgers,
state history, event targets, truly out-of-fold predictions, sequential Platt
calibration and the daily publication.  A model that fails Brier/ECE is an
honest accepted result only when the published event falls back to
`BASE_RATE_ONLY`.

The probability cache is accepted only when its version, runtime, spec and
state-history digest all match.

## Automatic daily runtime

MatVIX is an end-of-day batch, not an intraday streaming service.  The local
runtime has two independent macOS LaunchAgents:

- `com.matvix.daily-update` wakes every five minutes.  The Python scheduler
  does no source work before the bounded New York publication window, begins
  prefetch at 08:50 ET, never publishes before the frozen next-session 09:20 ET
  decision gate, and then polls missing sources for at most three hours.  A Mac
  that wakes after the window makes one catch-up attempt instead of skipping
  the session; `FAILED` and `BUSY` catch-up outcomes are also marked consumed
  so the five-minute LaunchAgent cannot repeat the same late attempt forever.
- `com.matvix.dashboard` keeps a read-only HTTP dashboard available at
  `http://127.0.0.1:8788/`.  It resolves the newest accepted snapshot on every
  request and keeps the last rendered-good page when a newer candidate cannot
  be rendered.  Each accepted snapshot freezes the complete five-axis
  component decomposition.  Historical states/OOF charts are shown only when
  their full-generation digests still match that snapshot's formal receipt.

Install and immediately start both services:

```bash
cd /Users/logan/MatVIX
.venv/bin/python -m matvix install-services --load --project-dir .
```

Run or inspect the same workflow manually:

```bash
.venv/bin/python -m matvix daily-update --project-dir .
.venv/bin/python -m matvix runtime-status --project-dir .
.venv/bin/python -m matvix serve --project-dir . --port 8788
```

The updater downloads only into `data/raw/live/`, merges immutable revisions
into the normalized ledgers, rebuilds state/probability artifacts, executes the
13 real-data gates, and publishes in this order: processed artifacts, daily
snapshot, then a content-bound acceptance receipt.  A missing source, failed
gate, lock collision or interrupted publish never promotes the candidate over
the prior last-good snapshot.  Runtime and launchd logs live under
`outputs/runtime/`.

The timing policy deliberately separates “downloadable” from “formally usable”.
Cboe describes its VIX history as updated daily, while CFE says Daily Market
Statistics are normally available around 10:00 CT on the next trading day.
MatVIX validates the requested CFE settlement date from the response filename
and refuses a fallback response for an older session.

## Daily contract

Machine consumers read state only from the versioned daily JSON, especially
`market_story.*` and `probability_judgment[event].*`.  Narrative text is for
human explanation and must not be parsed into trading instructions.

The trader-facing dashboard leads with one weather gauge, the
Short-temperature / Composite-judgment / Structure-stability triad, the five
business axes in their frozen order, and qualified probability summaries.
`Structure stability = 100 - CarryRisk` is a presentation inversion only, not a
sixth score or a new model.  The conflict panel explains why apparently mixed
indicators still resolve to one published phase under the frozen state machine.

The complete business and formula authority is
[`MATVIX_PRE_DEVELOPMENT_REPORT.md`](MATVIX_PRE_DEVELOPMENT_REPORT.md).
The accepted real-data evidence and probability results are summarized in
[`REAL_DATA_ACCEPTANCE.md`](REAL_DATA_ACCEPTANCE.md).

## Data rights

The local acceptance snapshot is traceable to official Cboe/CFE public
download endpoints.  Public accessibility does not grant unrestricted
commercial redistribution.  Keep vendor files out of Git and confirm the
project owner's licence before professional or commercial use.
