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

The accepted source snapshot ends with a complete F1-F6 curve on 2026-08-18.
Four missing SKEW observations and invalid CFE `Settle=0` values are preserved
as missing; the pipeline does not forward-fill them.

`accept-real` recomputes 13 business gates from the persisted raw ledgers,
state history, event targets, truly out-of-fold predictions, sequential Platt
calibration and the daily publication.  A model that fails Brier/ECE is an
honest accepted result only when the published event falls back to
`BASE_RATE_ONLY`.

For the normal daily update, rerun `import-data`, `build-history`, then use
`train-probabilities --incremental`.  The probability cache is accepted only
when its version, runtime, spec and state-history digest all match.

## Daily contract

Machine consumers read state only from the versioned daily JSON, especially
`market_story.*` and `probability_judgment[event].*`.  Narrative text is for
human explanation and must not be parsed into trading instructions.

The complete business and formula authority is
[`MATVIX_PRE_DEVELOPMENT_REPORT.md`](MATVIX_PRE_DEVELOPMENT_REPORT.md).
The accepted real-data evidence and probability results are summarized in
[`REAL_DATA_ACCEPTANCE.md`](REAL_DATA_ACCEPTANCE.md).

## Data rights

The local acceptance snapshot is traceable to official Cboe/CFE public
download endpoints.  Public accessibility does not grant unrestricted
commercial redistribution.  Keep vendor files out of Git and confirm the
project owner's licence before professional or commercial use.
