# E15 occurrence research history through 2026-08-30

Status: `ARCHIVED`

Role: 保留 Round 1 已执行的 E15 研究路径、关键数字和 artifact 导航。本文只记录 point-in-time
证据与当时裁决，不授权任何当前施工、晋升或交易。是否存在真正不同的新问题，由当前 active
brief 按 `AGENTS.md` 判断。

## Target and support

历史主 target 是 `max(k=1..5) log(VIX_close[t+k]/VIX_close[t]) >= 0.15`。2016–2023
有 2,012 个有效 origin、407 个阳性 origin 和 84 个 universal first-crossing episode。
`OK + CONTANGO` 历史行动域有 1,698 个 origin、341 个阳性 origin。

P0 先在 3,339 个 XNYS session 上完成日历、target maturity、first crossing、episode、
cohort、PIT 代理和 V3 artifact 校验，得到 84 个完整 episode 和 77 个 eligible onset
veto ceiling。这仅证明考卷和机械上限成立，不证明候选概率或交易 alpha。

## H1: front curvature

H1 在日频 VIX9D²、VIX²、VIX3M² 前端斜率/曲率及其变化上执行唯一冻结
candidate。正式裁决为 `H1_FAILED / H1_CLOSED`：

- C1 相对 B0 的 all-origin Brier increment 为 `-0.007493`，90% CI
  `[-0.012842, -0.002967]`。
- 84 个正 episode 等权后，正例 log-loss 仍差于 B0：`-0.118153`，90% CI
  `[-0.206105, -0.033150]`；也差于 B1：`-0.039904`，CI
  `[-0.077287, -0.005957]`。
- 84 个 crossing 的间隔中位数为 28 个 session，最长 84。固定 20-session 与
  40–504-session block 的 proper score、concentration 和总裁决都失败。
- utility 对重采样单位更敏感：冻结 20-session 门为 `FAIL`，整年簇为
  `INCONCLUSIVE`。严格表述是 proper score 与 concentration 稳健失败，utility
  只在冻结门下失败；H1 总体仍失败。
- 2024–2026 自然新增 26 个 episode 后，描述性 C1-vs-B0 Brier/log-loss 仍为
  `-0.008357 / -0.027624`。这不是独立 holdout，但没有显示“再等几个 episode”会翻转。

失败不是大量负例淹没预警；C1 在正 episode 上分配的概率质量本身也更差。

## H2: daily measurement state

H2 不重拟合 H1，只新增 daily `log(VWA/VWB)` 与 `log(VSTN/VSTF)`。缺失和官方停播日
回退 B1。正式裁决为 `H2_FAILED / H2_CLOSED`：

- C2-vs-B0 all-origin Brier increment `-0.006323`，90% CI
  `[-0.010830, -0.002435]`；log-loss `-0.022815`，CI
  `[-0.039992, -0.009377]`。
- 正 episode 等权 log-loss increment 对 B0/B1 为 `-0.110630 / -0.032381`，两个 90%
  上界都低于零。
- all-origin reliability 为 `0.008162`，差于 B0 `0.003782` 与 B1 `0.006950`；
  calibration slope 为 `-0.038959`。
- proper score、positive-episode mass、concentration 和 calibration 失败；20-session utility
  `INCONCLUSIVE`，whole-year sensitivity `FAIL`。

H2 只关闭这个 daily measurement-state 信息块，不关闭真实盘前报价的 freshness/quality。

## H3 exact-tick data route

第一个 H3 问题要求 09:20 ET 前 exact-event 双边 VX1/VX2 报价。当时本地字节、官方
sample 和零价公开路径无法建立同质的 2016–2023 考卷，因此裁决为
`H3_PREOPEN_UNTESTABLE_DATA / H3_NOT_FITTED`。没有 scaler、fit、OOF 或科学门，不得把它
写成 H3 科学失败。

## H3 Q1m: pre-open VX repricing

后续使用 QuantConnect/AlgoSeek 的非 fill-forward 标准月 VX minute QuoteBar 建立了不同于
exact-tick 主张的 Q1m 考卷。原始云端数据不分发，本地仅保留允许的 cloud result 和派生
研究数据。

- 2,012 个 origin 都有一个终态；1,952 个取得有效双腿 QuoteBar，不是 2,012 个都有报价。
- 1,696 个 origin 输出 genuine H3，60 个 `ABSTAIN_DATA`，256 个 `ABSTAIN_WARMUP`。
- 正式 H3/B1 common 为 1,453 个 origin、301 个阳性、68 个正 episode。

| gate | 决定性证据 |
|---|---|
| Proper score | H3-vs-B0 Brier increment `0.009831`，90% CI `[0.005082, 0.015131]`；log-loss `0.027087`，CI `[0.015591, 0.039659]` |
| Positive episode mass | episode-equal log-loss increment 对 B0/B1 为 `0.127608 / 0.227979`，两个下界均为正 |
| Concentration | 移除 COVID 或最有利 episode 后 Brier 下界仍为正；pre-2020/2020-onward 方向均为正 |
| Calibration sanity | H3 reliability `0.000941`，优于 B0 `0.003972` 和 B1 `0.008431`；slope `1.022384` |
| 当时的规范化 utility | 对 B0/B1 的 PRE_ONSET increment `0.004162 / 0.010311`；whole-year 最薄 B0 下界仅 `0.000028` |

历史裁决为 `H3_Q1M_NOMINATED`。它是 occurrence sensor nomination，不是 exact-tick、receipt-time、
prospective、产品或交易证据。

### 2024–2026 temporal diagnostic

成熟 cohort 有 661 个 origin：590 个 genuine update，71 个 B0-copy abstention。H3/B1 genuine-common
为 558 个 origin、130 个阳性、24/26 个正 episode。combined H3 Brier increment 对 B0/B1
为 `0.013419 / 0.023345`，log-loss increment 为 `0.036453 / 0.072209`；20-session 与
84-session 下界均为正，各可用年份的 point direction 也为正。

裁决是 `RECENT_SUPPORTS_H3`，但不是全新 holdout；2025 正 episode log-loss 对 B1 为负，
合并区间不确定，PRE_ONSET utility 总体不确定且可用 2026 敏感性为负。2026-06-01
起的 71 个缺口保留为 abstention，没有 fill-forward 或插值。

## Common-cohort and probability-semantics audit

Round 1 随后冻结已有 H1/H2/H3 ledgers，不重拟合任何候选，并在三者 genuine-common cohort 上
审查候选集合内的唯一性、H3 概率字面含义和制度稳定性。

- genuine-common 有 1,429 个 origin、292 个阳性、65 个正 episode。H3 Brier/log loss 为
  `0.153825 / 0.482354`，优于 C1 的 `0.174205 / 0.554160` 和 C2 的
  `0.172585 / 0.541450`；H3-vs-C1/C2 的 20/84-session block 区间下界均大于 0。
- 因 H1/H2 只使用 prior-close 信息，H3 使用次日 09:20 信息，这个结果最多支持
  `ONLY_NOMINATED_AMONG_EXECUTED_CHALLENGERS / STRONGEST_OBSERVED_ON_COMMON_COHORT`，不能建立
  same-clock 或 global best。
- 2,286 个 genuine H3 origin 的 pooled 平均预测为 `22.39%`、实现率 `21.43%`、calibration
  slope `0.913`、固定箱 WRMS gap `2.25 pp`，风险箱实现率保持有序。
- pooled 结果掩盖制度反转：2020–2023 平均预测/实现率为 `23.83% / 19.79%`，2024–2026 为
  `20.33% / 24.07%`。calibration gap shift 为 `7.78 pp`；20-session 90% 区间
  `[1.82, 13.86] pp`，84-session 为 `[1.70, 13.98] pp`。

因此 H3 的 Round 1 概率终态为 `CALIBRATION_UNSTABLE`。它仍保留历史 occurrence-sensor nomination，
但没有获得 literal posterior、same-clock best、prospective 或产品身份。

## RI252 calibration leaf

Round 1 只执行了一个 causal、只用已成熟 outcome、斜率固定为 1 的 rolling-intercept candidate：

```text
logit(p_RI,t) = logit(p_H3,t) + b_t
```

`b_t` 最多使用最近 252 个已成熟 genuine H3 origin，并要求至少 20 个正例和 20 个负例；否则保持
原 H3。该 leaf 没有搜索窗口、Platt、isotonic、beta calibration 或第二个模型。

2,673 个输入 origin 完成零 causal-replay 违规；151 个保持 warm-up，387 个保持 H3 abstention，
2,135 个进入 RI/H3/B0 common cohort，覆盖 470 个阳性和 93 个正 episode。冻结门结果为：

| Gate | Result | 决定性证据 |
|---|---|---|
| causal replay | `PASS` | 只用当前 09:20 前已成熟 outcome；窗口、warm-up 与 abstention 零违规 |
| calibration repair | `FAIL` | 两段 gap 为 `-1.47 / +1.40 pp`，但 slope `0.703`，WRMS 90% 上界约 `6.47 pp` |
| proper score | `FAIL` | RI-vs-H3 Brier/log-loss 为 `-0.002258 / -0.005422`，2024–2026 两项均变差 |
| resolution retention | `FAIL` | 固定箱 resolution 从 `0.009131` 降至 `0.007423` |

正式裁决为 `CALIBRATION_REPAIR_NOT_ESTABLISHED / RI252_CLOSED`。RI252 缩小了平均制度 gap，却没有
改善完整概率分层或 proper score；Round 1 不再搜索另一个校准器。

## Round 1 trajectory boundary

当时预写的 three-session lag-mean candidate 依赖 H3 先获得稳定字面概率。由于 probability-semantics
门失败，该 candidate 严格 `ZERO_FIT / BLOCKED_BY_PROBABILITY_SEMANTICS`。这不是对固定同一事件、
真实 EOD→09:20 sequential update 的检验，也不是对所有 probability-frontier 研究的负结论。

## Closed action leaf

后续审查冻结 H3 概率，只测试 09:20 ET `OK + Q1m CONTANGO` 下的
`VETO_NEW_SHORT_5D`。在 2,673 个 OOF origin 中，2,112 个 eligible，1,997 个有完整
五日 path。同时钟 perfect oracle 的平均正可避免 endpoint loss 为 `0.031392`，证明动作
对象本身有容量。

H3 与 overnight repricing 的 Spearman 为 `0.815766`，与 09:20 后 endpoint loss/MAE 为
`-0.090581 / -0.070680`。在预写 10% budget 下，H3 net endpoint value `-0.000231`、
oracle-loss capture `0.096666`，都差于 B1 的 `0.002543 / 0.160666`。H3-vs-B1 的
20/84-session 区间上界均低于零。

终态为 `H3_ACTION_CLOCK_MISMATCH / H3_WEATHER_SENSOR_RETAINED /
H3_ACTION_ROUTE_CLOSED`。这只关闭该固定 action leaf，不关闭 E15 target 或 H3 occurrence
sensor。

## Local evidence map

```text
outputs/e15_actionable_occurrence/       P0/H1 report and ledgers
outputs/e15_eod_measurement_state/        H2 report and ledgers
outputs/e15_h3_preopen_feasibility/       exact-tick data-route report
outputs/e15_h3_q1m/                       H3 Q1m panel, OOF, evidence and report
outputs/e15_h3_action_clock/               closed action-leaf ledger and report
outputs/e15_occurrence_deep_dive/          common-cohort and probability-semantics audit
outputs/e15_rolling_intercept_calibration/ RI252 causal replay, ledger and report

data/raw/vendor/e15_measurement_state/     local H2 source bytes
data/raw/vendor/e15_h3_preopen_feasibility/ local source samples
data/raw/vendor/e15_h3_q1m/                local QuantConnect result bytes
artifacts/research_archive/e15_2026_08/    retired runner/test/document snapshot
```

这些路径被 Git 忽略，只限本机研究使用，不对外分发。Markdown 只保留裁决与导航；完整
ledgers、JSON 和运行代码快照保留在本地 artifact 中。

RI252 的已验证 runner 与 focused test 另由历史分支 `codex/e15-actionable-occurrence` 的 closeout
commit `eb09e7002762eab496e6a134ca605ff75fce09c0` 保存。当前 R2 checkout 不保留这两个 closed-leaf
执行入口；需要复核历史实现时从该 commit 只读查看，不得据此推导新的 fit authority。
