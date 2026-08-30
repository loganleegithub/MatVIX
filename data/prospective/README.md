# MatVIX prospective evidence directories

This is a directory index, not a second protocol. The active append-only prediction/outcome rules
are defined by [`../../MATVIX_PROSPECTIVE_001_CONTRACT.md`](../../MATVIX_PROSPECTIVE_001_CONTRACT.md).
Prospective 001 was activated by tag `matvix-prospective-001-activation`; current counts must be
read from `/api/status` or the Core paths, never copied from a dated report.

- Predictions: `core/predictions/YYYY-MM-DD.json`
- Outcomes: `core/outcomes/YYYY-MM-DD/EVENT_ID.json`
- Core provenance: [`core/README.md`](core/README.md)

Historical stage reports are archived at
[`../../docs/archive/prospective-001/`](../../docs/archive/prospective-001/):

- `power-design.md`: pre-freeze P0 design evidence;
- `acceptance.md`: point-in-time P5 engineering acceptance.

`v3_fragility_shadow_ledger.csv` is a header-only frozen V3 release-manifest input for a rejected
counterfactual adapter. It is retained only because the frozen V3 identity binds it. It is not an
active research route and grants no authority to append observations, change V3 or trade.
