# MatVIX V3 Fragility prospective shadow ledger

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
