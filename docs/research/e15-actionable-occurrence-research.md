# Actionable E15 occurrence research brief

Status: `ACTIVE`

Execution state: `DESIGN_ONLY / NOT_FROZEN / NOT_EXECUTED`

Authority: `EXPLORATORY_RESEARCH_ONLY / NO_PRODUCT_CHANGE / NO_TRADING_AUTHORITY`

Research ID: `MATVIX_E15_ACTIONABLE_OCCURRENCE_RESEARCH_001`

Decision date: `2026-08-28`

## 1. Architecture decision

Full-amplitude Severity is no longer an active MatVIX research objective. E30, E60, conditional
quantiles and complete path distributions remain point-in-time evidence only. No current work may
restart them by renaming the model or changing the algorithm.

The only authorized post-V3 forecast question is now:

> Given all information honestly available at the forecast clock, what is the calibrated
> probability that VIX first crosses the existing E15 threshold within the next five XNYS
> sessions, and does that probability improve one prewritten short-vol action over a causal
> baseline?

This decision does not modify the frozen V3 surface. E15 research remains outside the product,
consumer, portfolio and order boundaries until independent evidence exists.

## 2. What the current evidence does and does not say

The existing physical label is retained for comparability:

```text
Y_t   = max(k=1..5) log(VIX_close[t+k] / VIX_close[t])
E15_t = 1[Y_t >= 0.15]
```

The historical name `E15` therefore means a `0.15` log move, equivalent to approximately a
`16.18%` simple increase. It is not silently changed to a literal `15%` simple return. A literal
15% sensitivity may be reported, but it cannot replace the primary label after results are seen.

Current reconstruction gives the following effective support:

| cohort | valid origins | E15-positive origins | merged E15 episodes |
|---|---:|---:|---:|
| 2016--2023, all valid states | 2,012 | 407 | 85 |
| 2016--2023, `OK + CONTANGO` | 1,698 | 341 | 78 |
| 2019--2023, all valid states | 1,258 | 249 | 53 |
| 2019--2023, `OK + CONTANGO` | 1,088 | 222 | 48 |

This is enough for small, strongly regularized probability models. It is not enough for an
algorithm tournament: overlapping origins are useful observations, but the independent evidence
is closer to 85 weather episodes than 2,012 independent trials.

The frozen modern evaluation found no usable ranking signal in the old information set. Relative
to causal path climatology, the structural B1 model had first-passage IBS Skill `-0.022223`; its
E15 day-one through day-five Brier improvements were all negative and median AUC was approximately
`0.496`. The option-bound increment had E15 AUC approximately `0.502` and also failed its paired
gate. These results reject the old six-feature structural hazard and option-bound candidates. They
do not prove that E15 is unforecastable with genuinely new sensors.

The completed perfect-label action studies establish only that advance binary E15 information can
have large post-result attribution value. They do not establish forecastability. They may also
overstate early-warning value because repeated positive origins inside one already-visible stress
episode received daily perfect information. Before any fit, the action ceiling must therefore be
recomputed on episode-onset and incremental-lead-time semantics.

There is no pristine historical holdout left at the project level. Any 2016--2026 reconstruction
is mechanism screening or, at best, a temporal post-sample check. A reliability claim requires a
freeze followed by prospective receipt-time forecasts.

## 3. Scientific reframing: a finite-horizon committor

E15 is not a VIX-level regression and not an ordinary independent-row classifier. It is a
finite-horizon rare-transition probability, often called a **committor**:

```text
p5(t) = P(E15 occurs within five sessions | information available at t)
```

An equivalent discrete survival representation is:

```text
h_k(t) = P(first crossing occurs on day k | no earlier crossing, information at t)
p5(t)  = 1 - product(k=1..5) [1 - h_k(t)]
```

This representation preserves first crossing, censoring, lead time and the five-day event
calendar. It also prevents a crisis episode from being treated as a pile of unrelated positives.

The weather object and action object are deliberately different:

- The weather object scores `p5(t)` on every valid origin.
- The primary action population is `data_status == OK and front_slope30 > 0`: term structure still
  permits short-vol exposure, so an E15 forecast can change a decision before the existing state
  gate has already become defensive.
- Backwardation E15 remains a diagnostic output. It is not pooled into the primary action claim;
  the completed VIXY experiment did not establish a robust long-vol action.
- `PRE_ONSET` and `ACTIVE_CASCADE` are reported separately. A warning after stress is observable
  is useful for response but cannot be called an early warning.

## 4. What other forecasting domains teach us

| domain | matching structure | transferable discipline | limit for MatVIX |
|---|---|---|---|
| Flood and severe weather | nonlinear five-day threshold crossing | ensembles, calibration against climate, Brier skill and lead-time verification | modern flood systems learn from thousands of basins and physical weather forecasts, far more data than VIX has |
| Clinical deterioration and seizures | repeated observations before clustered rare events | dynamic survival, event-level sensitivity, time-in-warning and alarm burden | high AUROC can coexist with intolerable false alarms; noncausal smoothing can create fake skill |
| Earthquake aftershocks | background hazard plus self-exciting cascades | generic prior, sequence-specific Bayesian update and prospective evaluation | financial excitation parameters drift and market participants react |
| Wildfire and grid failure | vulnerability plus trigger plus propagation | model `fuel x ignition x weather x spread`, not one magic indicator | the trigger may be an unforecastable news shock |
| Epidemic forecasting | regime change and heterogeneous models | a small ensemble of validated mechanisms reduces variance | an ensemble cannot repair shared leakage or a missing sensor |
| Molecular rare transitions | probability of reaching a new state before returning | directly estimate the committor instead of reconstructing an average path | market state is only partially observed and nonstationary |

The strongest existence proof is not finance. A 2024 global flood system produced useful
one-to-five-day forecasts for extreme threshold events across 5,680 gauges and was deployed in more
than 80 countries. This shows that short-horizon extremes are not unforecastable in principle; it
also shows what MatVIX lacks: many independent systems, physical drivers and forward exogenous
inputs.

## 5. Feasibility judgment

A **limited, calibrated and sometimes abstaining E15 probability is scientifically plausible**.
A daily siren with both high recall and few false alarms is not presently supported.

Success would mean all of the following:

- probabilities beat a causal dynamic climatology under proper scores;
- low, medium and high forecasts correspond to materially different observed frequencies;
- the gain survives episode, year and regime sensitivity analysis;
- a prewritten cost/loss action improves at a fixed alert budget;
- prospective forecasts retain calibration;
- missing, stale or out-of-support inputs produce `ABSTAIN`, not invented confidence.

Some E15 events will remain irreducible because the cause arrives after the forecast clock. The
system can estimate **susceptibility to an arbitrary shock** and update rapidly after overnight
evidence; it cannot know the content of tomorrow's unscheduled news.

## 6. New information hypotheses, in priority order

### H1. Five-day front-end curvature

The old B1 features did not fully represent the short-dated SPX volatility surface. Test
`VIX9D^2`, `VIX^2`, `VIX3M^2`, maturity-normalized forward-variance slopes, front curvature, one-
and five-day changes and acceleration. VIX level must be in the baseline because the percentage
threshold is mechanically easier to cross in index points when VIX is low.

Cboe's official term structure confirms that VIX9D is the closest published index to the E15
window. A 2026 working paper reports that VIX9D-based front inversion improves five- and ten-day
realized-volatility forecasts, including recursive OOS tests. This is a mechanism hypothesis, not
direct E15 evidence and not yet mature consensus.

### H2. Signed jump and cojump cascade

Daily closes may erase the pressure sequence that matters. Construct a few causal summaries:

- SPX downside and VIX upside intraday jump counts and magnitudes;
- SPX-down/VIX-up cojumps;
- time since the last cojump;
- one-, three- and five-day exponentially decayed excitation scores.

Use these as low-parameter Hawkes-inspired features. Do not fit a neural Hawkes model on 85
episodes. Recent high-frequency option and cojump research supports asymmetric information in
signed paths, but it predicts variance or risk premia rather than the E15 label.

### H3. Left-tail versus diffusive risk

Cboe's SPOTVOL is designed to isolate jump-robust spot volatility from short-dated options, while
LTV targets one-week extreme left-tail risk. Test `LTV / SPOTVOL`, `VIX9D - SPOTVOL` and the
interaction between front-end acceleration and rising left-tail share.

These are risk-neutral prices, not physical E15 probabilities. The indices are recent and may use
backfilled histories. Reconstructed values must be labelled research proxies unless their
historical receipt-time availability is proved; prospective capture is the clean route.

### H4. Cross-asset fragility before equity volatility catches up

Test whether credit, funding, safe-asset and global-volatility nodes deteriorate together while
VIX remains locally calm. Candidate summaries are breadth and acceleration, not hundreds of raw
levels. OFR's Financial Stress Index is useful only through pre-registered non-volatility
components, lagged by its actual publication delay; revised history is not vintage PIT.

### H5. Known catalyst interaction

At the forecast clock, FOMC, CPI, payroll, GDP, Treasury/refunding and major expiry calendars are
known. The hypothesis is not `event day => danger`. It is:

```text
known catalyst x front-end repricing x latent fragility
```

Post-release surprise cannot be backfilled into a pre-release origin.

### H6. EOD prior plus pre-open posterior

The most actionable new clock is a paired forecast:

```text
16:00 ET EOD_PRIOR
    -> overnight/global evidence
09:20 ET PREOPEN_POSTERIOR
    -> bounded action near the next open
```

The posterior may use timestamped VX1/VX2 changes, ES/NQ/rates overnight returns and ranges,
Asian/European volatility transmission, and price reaction to data already released by 09:20.
It must use the same E15 target and be scored against a separate pre-open baseline. Shorter lead
time cannot be presented as a better EOD algorithm.

### H7. Cross-market volatility ecology

The highest-upside, highest-risk extension is a hierarchical study across VIX, VSTOXX and other
well-defined implied-volatility ecosystems. It would learn common `curve deformation -> propagation
-> threshold crossing` structure, then recalibrate only on VIX. It is allowed only after the
single-market low-dimensional route is implemented. Leave-one-market-out and a VIX-only final
test are mandatory because different products, clocks and regimes are not interchangeable.

## 7. Baselines and bounded candidates

The research is about new sensors, not an algorithm search.

### Baselines

- `B0_DYNAMIC_CLIMATOLOGY`: Beta-Binomial-shrunk occurrence rate using only outcomes that have
  matured before the current origin, with a fixed rolling memory.
- `B1_CURRENT_INFORMATION`: B0 plus VIX level, current V3 occurrence outputs and the existing
  futures term-structure state. Every new candidate must beat this, not an unconditional mean.

### First historical screen

- `C1_FRONT_CATALYST`: B1 plus the prewritten VIX9D/front-curvature block and known-event
  interaction.
- `C2_CASCADE_FRAGILITY`: B1 plus signed cojump excitation and cross-asset breadth.
- `C3_FIXED_COMBINATION`: the fixed union of C1 and C2; no feature selection on validation years.
- `C4_PREOPEN_UPDATE`: a separate-clock Bayesian/log-odds update of the best frozen EOD prior using
  only overnight receipt-time features.

Use an unweighted ridge logistic or complementary-log-log discrete hazard with training-fold-only
standardization. A few prewritten low-degree splines or interactions are allowed. Class weighting,
SMOTE and outcome-balanced resampling are prohibited because they distort the probability scale.
Only if a simple candidate establishes repeatable skill may one shallow bagged-tree challenger be
pre-registered. Deep nets, Transformers, diffusion paths and AutoML are outside the first route.

A fixed median or linear probability pool may be tested once, and only if at least two genuinely
different members already show OOF skill. Ensemble diversity means different mechanisms, not four
algorithms trained on the same six columns.

## 8. Historical evaluation and prospective proof

Historical work is an `EXPLORATORY_MECHANISM_SCREEN`:

- walk forward in time;
- require every training row's `target_end_session < assessment_origin`;
- purge/embargo overlapping target windows;
- standardize, calibrate and choose any penalty inside the training fold only;
- retain daily origins for scoring but cluster inference by episode and calendar block;
- report pre/post-2020, pre/post-0DTE, COVID-excluded and leave-one-episode-out sensitivity;
- never call 2024--2026 prospective evidence merely because it was not in the old CSV.

Primary statistical evidence:

- Brier Skill and log-score improvement over B1;
- calibration-in-the-large, calibration slope, CORP reliability and resolution;
- paired episode/block uncertainty intervals;
- PR-AUC and ROC-AUC only as diagnostics.

Primary operational evidence:

- episode capture at fixed alert budgets;
- false-warning episodes and continuous false-warning length;
- fraction of time in warning;
- first-alert-to-first-crossing lead time;
- `PRE_ONSET` performance and incremental lead over V3/term structure;
- Murphy or equivalent cost/loss value across the prewritten action-threshold band.

The action threshold is not `0.5`. For a specific bounded sleeve it follows the cost/loss ratio:

```text
threshold = cost of unnecessary protection / loss avoided when E15 occurs
```

Low probability may authorize a bounded short-vol add in contango; high probability may reduce or
veto it. The exact weights, holding period, turnover cost and deadband must be frozen before the
formal evaluation. P&L cannot select weather features or models.

After a candidate survives the historical screen, one contract may freeze the target, two clocks,
candidate set, minimum event support, maximum duration and terminal rule. From the next session,
inputs, receipt times, B0/B1/candidate probabilities, abstentions and outcomes are appended before
they mature. Only that ledger can establish operational reliability.

## 9. Abstention and drift

- Missing, late or provenance-invalid inputs: `ABSTAIN_DATA`.
- Sensor vector outside historical support or severe model disagreement: `ABSTAIN_OOD`.
- On abstention, publish B0/B1 and prohibit a candidate-induced position change.
- A middling probability is not missing information; it is an honest uncertain forecast.
- Near an action threshold, a transaction-cost deadband should retain the current position.
- Online conformal or sequential risk controls may be sidecars, but they cannot create skill and
  cannot assume financial observations are exchangeable.

## 10. Execution sequence and stopping rules

### P0: semantics, value and data feasibility

1. Preserve the existing `0.15` log label and publish the literal-15% sensitivity separately.
2. Recompute perfect-information value on `OK + CONTANGO`, one credit per episode, separating
   `PRE_ONSET` from `ACTIVE_CASCADE` and measuring incremental lead over existing gates.
3. Audit historical/public availability, release delays, revisions, rights and prospective
   receipt for VIX9D, SPOTVOL/LTV, intraday jumps, cross-asset nodes and pre-open futures.
4. Start prospective raw receipt for the two-clock sensor panel even while historical screening
   is running; receipt capture is evidence collection, not model activation.

If the onset-only oracle has little bounded action value, stop before fitting.

### P1: EOD mechanism screen

Run B0, B1 and the fixed C1--C3 set once. Reject an information block if it has no positive proper-
score increment, depends on one episode, fails PIT provenance or has no value in the action band.

### P2: pre-open update

Run C4 only if receipt-time data are auditable. It must beat both its clock-matched baseline and
the EOD prior on identical executable dates.

### P3: one high-upside extension

Cross-market hierarchical transfer is the only permitted major extension. It requires a separate
brief and cannot reuse the same VIX validation outcomes for model search.

### P4: prospective terminal test

Freeze one surviving candidate or fixed ensemble. If it fails the terminal proper-score,
calibration and action-value gates, close the current E15 information set and wait for new episodes
or a genuinely new sensor. Do not recycle the same outcomes through another algorithm family.

## 11. What is explicitly not authorized

- no restart of full Severity, E30/E60 or path-scale prediction;
- no change to V3 probabilities or state axes;
- no live position, order, product or public forecast;
- no historical `UNKNOWN` relabelling to hide errors;
- no use of future P&L, outcomes or revised data as weather features;
- no generic news/LLM embedding or social sentiment in the first screen;
- no claim that option-implied risk-neutral prices are physical E15 probabilities;
- no production API, schema or immutable prediction system before a candidate passes the research
  screen and a separate promotion decision is made.

## 12. Primary public sources

- Cboe, [VIX term structure](https://www.cboe.com/tradable-products/vix/term-structure/) and
  [SPOTVOL/LTV indices](https://www.cboe.com/us/indices/spotvol-and-ltv-indices/).
- Bai and Cai, [Predicting VIX with adaptive machine learning](https://www.tandfonline.com/doi/full/10.1080/14697688.2024.2439458), 2025.
- Lim, [The Front End of the VIX Term Structure and Forward Realised Volatility](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6752518), 2026 working paper.
- Mascolo et al., [Gaussian Framework and Optimal Projection of Weather Fields for Prediction of Extreme Events](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2024MS004487), 2025.
- Nearing et al., [Global prediction of extreme floods in ungauged watersheds](https://www.nature.com/articles/s41586-024-07145-1), Nature 2024.
- Yeche et al., [Dynamic Survival Analysis for Early Event Prediction](https://proceedings.mlr.press/v248/yeche24a.html), 2024.
- USGS, [Operational Aftershock Forecast scientific background](https://earthquake.usgs.gov/data/oaf/background.php).
- Taylor et al., [Evaluation of probabilistic infectious-disease forecasts](https://wwwnc.cdc.gov/eid/article/30/9/24-0026_article), CDC/EID 2024.
- Schorlemmer et al., [Prospective evaluation of earthquake forecasts](https://www.nature.com/articles/s41467-026-76243-7), Nature Communications 2026.
- Gneiting et al., [User-focused forecast verification](https://journals.ametsoc.org/view/journals/wefo/39/8/WAF-D-23-0201.1.xml), 2024.
- SEC DERA, [Demystify the Surge in VIX](https://www.sec.gov/files/dera-vix-working-paper-2504.pdf), 2025.
