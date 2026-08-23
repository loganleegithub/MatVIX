# MatVIX prospective evidence directories

This file is a directory index, not a second protocol description. Current freeze, P6 and
external-consumer semantics are defined only in
`MATVIX_V3_EXTERNAL_STRATEGY_CONSUMER.md`.

Prospective 001 P6 is activated by `matvix-prospective-001-activation`. Runtime Prediction
and Outcome Schemas and the append-only writer/resolver are installed. At the 2026-08-24
repository freeze no natural Core prediction had yet been captured; runtime counts may
advance after that date and must be read from `/api/status` or the Core paths below. Historical
snapshots must never be backfilled.

Document roles are deliberately distinct: `MATVIX_PROSPECTIVE_001_CONTRACT.md` is the frozen
protocol, `MATVIX_PROSPECTIVE_001_POWER_DESIGN.md` is the pre-freeze P0 evidence, and
`MATVIX_PROSPECTIVE_001_ACCEPTANCE.md` is the point-in-time P5 report. Their earlier-stage
status lines are historical evidence rather than claims about the current P6 state.

- Core predictions: `core/predictions/YYYY-MM-DD.json`
- Core outcomes: `core/outcomes/YYYY-MM-DD/EVENT_ID.json`
- Core provenance: `core/README.md`

The CSV below is a separate rejected-adapter counterfactual ledger.

## Fragility prospective shadow ledger

Status: `ESTABLISHED_EMPTY_APPEND_ONLY / COUNTERFACTUAL_RESEARCH_ONLY`

The adapter implementation was frozen at
`84fa1d3df2f527a4d41944cbabe0f055401d12bf` on 2026-08-23. The frozen historical
probe ends at outcome-through 2026-08-20 and rejected `ADAPTER-002` as
`NO_COMPREHENSIVE_INCREMENT`, so this directory starts with a header-only ledger
and zero prospective observations.

Rules:

- Never backfill a signal, execution, price, or outcome from on or before the
  adapter freeze.
- Append only after a complete common signal, execution, and return-through
  session is observable using information available at each causal timestamp.
- Preserve every existing row byte-for-byte; do not update or delete prior rows.
- Record the frozen unqualified score and counterfactual mapping only. The ledger
  grants no trading authority and cannot qualify `PROB-FRAGILITY-002`.
- A future adjudication requires a separate, prospectively frozen power/evidence
  contract. It cannot alter the frozen V3 historical verdict.

`v3_fragility_shadow_ledger.csv` contains the frozen columns needed to trace
signal -> counterfactual position -> price -> cost -> outcome -> NAV. The current
data-row count is zero.
