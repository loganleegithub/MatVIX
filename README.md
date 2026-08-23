# MatVIX V3

MatVIX V3 is a point-in-time, end-of-day weather station for the VIX options-insurance
market. It converts the Cboe volatility term structure, standard monthly VX curve, VVIX,
SKEW and SPX into five transparent state axes, one deterministic market phase and a
catalogue of causal event probabilities.

MatVIX is a read-only research product. It does not generate orders, positions, sizing or
trading permission.

## Release status

- `RESEARCH_STATION_READY`
- `READ_ONLY`
- `NO_TRADING_AUTHORITY`
- `HISTORICAL_CORE_ACCEPTED`
- `PROSPECTIVE_CONFIRMATION_PENDING`

The engineering package and release tag are `3.0.1`. The frozen scientific Feature,
State, Probability and Schema surface remains `3.0.0`; this patch release changes no
model, threshold or probability contract.

## Frozen V3 surface

The only current product identity is `MATVIX_CBOE_CORE_V3` with Feature, State,
Probability and Schema version `3.0.0`.

- `acute_front_stress_5d`, `front_inversion_5d`,
  `mid_curve_pressure_accelerates_5d` and `carry_environment_recovers_10d` are the four
  formal `FEATURE_CONDITIONAL` events.
- `broad_stress_persists_10d` is deliberately `BASE_RATE_ONLY`; it is a historical
  reference, not a failed or hidden model.
- Fragility remains outside the formal probability and runtime surfaces. The rejected
  economic adapter grants no trading authority.

The executable authority is the checked-in V3 configuration, schema and code:

- `configs/features_v3.yaml`
- `configs/state_v3.yaml`
- `configs/probability_v3.yaml`
- `configs/source_manifest.yaml`
- `schemas/daily_output.schema.json`

`MATVIX_V3_RELEASE_MANIFEST.json` binds the local release tag, tracked configuration,
schema, dependency lock, authorized-data requirements and local evidence identities
without redistributing restricted data. It also retains the rejected Fragility candidate's
fixed 114/252 OOF boundary. Detailed construction history remains available through Git;
it is not part of the current release surface or runtime authority.

## Reproducible environment

```bash
cd /Users/logan/MatVIX
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip install pytest==9.0.2 ruff==0.13.3 mypy==1.18.2
.venv/bin/python -m matvix doctor --project-dir .
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src/matvix
```

`scikit-learn==1.7.2` is part of the formal probability contract. A different runtime may
produce research calculations, but it cannot publish formal conditional probabilities as
V3.

## Authorized-data rebuild

Vendor files are local and excluded from Git. Verify the supplied manifest before import:

```bash
cd /Users/logan/MatVIX/data/raw/vendor
shasum -a 256 -c audit/SHA256SUMS.txt
cd /Users/logan/MatVIX
```

Then rebuild and sign the latest complete session:

```bash
.venv/bin/python -m matvix import-data \
  --cboe-dir data/raw/vendor/cboe \
  --cfe-dir data/raw/vendor/cfe \
  --spx-csv data/raw/vendor/spx_candidates/SPX_CBOE_2013_onward.csv \
  --spx-source CBOE \
  --project-dir .

.venv/bin/python -m matvix import-release-generation \
  --live-dir data/raw/live \
  --manifest configs/release_live_generation.json \
  --project-dir .

.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real --project-dir .
.venv/bin/python -m matvix accept-v3-station --project-dir .
.venv/bin/python -m matvix export-dashboard \
  --snapshot outputs/daily/2026-08-20.json \
  --output outputs/dashboard.html \
  --project-dir .
```

The authorized release-data bundle consists of the vendor baseline, the nine-file live
generation named by `configs/release_live_generation.json`, and the frozen Stage-D
historical comparator named by `MATVIX_V3_RELEASE_MANIFEST.json`. The comparator is a
hash-bound scientific test input, not current runtime authority. `accept-v3-station`
rejects it if either file is missing, damaged or replaced.

`accept-real` recomputes the persisted-data, target, OOF, calibration and publication
gates. A required conditional model that loses qualification falls back honestly to the
causal base rate; the failed candidate is not promoted over the last-good publication.

The one-time seven-dimension V3 scientific acceptance is retained under
`outputs/v3_station_acceptance/`. The frozen historical price probe is retained under
`outputs/v3_economic_probe/` with verdict `NO_COMPREHENSIVE_INCREMENT`; it is
`HISTORICAL_RESEARCH_SUPPORT`, not production promotion.

## Daily runtime

MatVIX is an end-of-day batch product with two local macOS LaunchAgents:

- `com.matvix.daily-update` refreshes official sources inside the bounded publication
  window and publishes snapshot then content-bound acceptance receipt.
- `com.matvix.dashboard` serves the newest accepted snapshot at
  `http://127.0.0.1:8788/` and keeps the last rendered-good page if a candidate is absent,
  corrupt or rejected.

Install or inspect the services:

```bash
.venv/bin/python -m matvix install-services --load --project-dir .
.venv/bin/python -m matvix daily-update --project-dir .
.venv/bin/python -m matvix runtime-status --project-dir .
.venv/bin/python -m matvix serve --project-dir . --port 8788
```

Machine consumers read only accepted, versioned daily JSON from `/api/snapshot`. The
dashboard and `/api/status` expose freshness, event/model status and overall product
readiness. `READY`, `DEGRADED` and `BLOCKED` are publication-health states only; all three
remain non-trading states.

## Data rights

The local evidence is traceable to official Cboe/CFE download endpoints. Public access
does not grant unrestricted commercial redistribution. Keep vendor files and historical
product-price probes out of Git, and confirm the applicable licence before professional or
commercial use.
