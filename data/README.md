# MatVIX local data

Vendor bytes, normalized tables, model ledgers and prospective observations are machine-local
unless a file is explicitly tracked. Do not copy changing row counts or latest dates into this
document; inspect the data or runtime status at the time of use.

```text
raw/vendor/     entitled or public source bytes; never committed or redistributed
raw/live/       bounded live source generation used by the V3 runtime
processed/      rebuildable normalized product tables
probability/    rebuildable V3 target and OOF artifacts
prospective/    local append-only V3 prediction/outcome evidence
```

E15 historical research data is also local only:

```text
raw/vendor/e15_measurement_state/
raw/vendor/e15_h3_preopen_feasibility/
raw/vendor/e15_h3_q1m/
```

The QuantConnect directory contains locally retained cloud-result bytes for backtesting and audit;
it is not a redistribution surface. Historical QuoteBar exchange time is not exact-tick age,
MatVIX receipt time or an executable quote.

For the frozen V3 product, `configs/source_manifest.yaml`,
`configs/release_live_generation.json` and `MATVIX_V3_RELEASE_MANIFEST.json` define the required
source identities. Preserve missing, invalid, stale and censored observations; never forward-fill
them to make a research gate pass.
