# MatVIX Dashboard Design QA

- source visual truth path: `/Users/logan/MatVIX/design/reference/matvix-trader-dashboard-composite-1440x1024.png`
- implementation screenshot path: `/Users/logan/MatVIX/artifacts/design-qa/implementation-1280x720.png`
- viewport: `1280 × 720` CSS px, desktop, device scale factor `1`, top of `http://127.0.0.1:8788/`
- source and implementation pixel dimensions, CSS size, and density normalization used:
  - source original: `1440 × 1024` px; it is a static visual with no independent CSS viewport metadata.
  - normalized source: proportionally resized to `1280 × 910` px, then top-cropped to `1280 × 720` px; no stretching; assumed `1x` comparison density.
  - implementation: browser-rendered at `1280 × 720` CSS px and captured as `1280 × 720` px at DPR `1`.
  - full implementation capture: `1280 × 1256` px.
- state: accepted real-data session `2026-08-18`; `data_status=OK`; `phase=MIXED_TRANSITION`; top-of-page; detail panels initially collapsed; HTTP runtime `RUNNING`; last-good session `2026-08-18`.
- full-view comparison evidence:
  - side-by-side normalized comparison: `/Users/logan/MatVIX/artifacts/design-qa/comparison-source-vs-implementation.png`
  - full browser page: `/Users/logan/MatVIX/artifacts/design-qa/implementation-fullpage.png`
- focused region comparison evidence: the critical first fold—header, main weather gauge, three-instrument strip, and the start of the five axes—is already isolated at equal `1280 × 720` dimensions in the side-by-side comparison. A second crop was not needed because no critical label or alignment became too small to judge there.
- primary interactions tested:
  - opened “查看冲突依据” and verified the rising evidence, counter-evidence, and frozen-state explanation.
  - opened “方法与口径 / 展开量化详情” and verified five answers, five scores, curve/probability/history content.
  - verified `/healthz`, `/api/status`, and `/api/snapshot` against the accepted `2026-08-18` generation.
  - re-signed the same session and observed the already-open page automatically reload from the old dashboard revision to the new revision within its own polling cycle.
- console errors checked: no page-level error was observed during load, both panel interactions, status polling, or automatic same-session reload. The Dashboard LaunchAgent stderr log remained `0` bytes.

## Findings

- P0: none.
- P1: none.
- P2: none.
- P3 follow-up polish: the source mock uses denser numeric ticks and slightly larger rings. The implementation keeps the selected hierarchy and color language while reserving space for live source status, exact axis drivers, probability qualification, and the explanation that `结构稳定度 = 100 − CarryRisk` is presentation only.

## Comparison history

1. P2 — the original live header exposed long ISO timestamps and wrapped at desktop width. Fixed by formatting operational times in compact New York time and showing the next actionable check. Post-fix evidence: `implementation-1280x720.png`.
2. P2 — the middle area did not match the selected “短端温度 / 综合判断 / 结构稳定度” instrument structure. Replaced it with three segmented radial instruments mapped to `Shock`, the published composite judgment, and `100 − CarryRisk`. Post-fix evidence: `comparison-source-vs-implementation.png`.
3. P1 — short-temperature and structure-stability captions could borrow evidence from another axis or lose an axis component after the global evidence list was truncated. Fixed by freezing all component contributions in the accepted snapshot and ranking only within Shock or Carry. Post-fix evidence: the live page shows `主要驱动：VIX · VVIX` and `主要缓冲：VX 曲线 · Basis`.
4. P1 — a failed later candidate could overwrite mutable states/OOF sidecars and contaminate the last-good page. Fixed by binding exact full-generation digests in the formal receipt; mismatched history is withheld while the snapshot-frozen market story remains intact. Post-fix evidence: cold-start real-render regression and the accepted live page.
5. P1 — an accepted replacement for the same session was not guaranteed to refresh an already-open page. Fixed by including the dashboard revision token in the page and polling comparison. Post-fix evidence: live revision changed from `1787210432707094682` to `1787210607781732918` without changing session date.

final result: passed
