# MatVIX V3 阶段 A 业务审计与停止裁决

> 合同：`MATVIX_V3_CONSTRUCTION_PLAN.md` v1.0
> 审计日期：2026-08-22
> 分支：`codex/matvix-v3`
> V2 代码基线：`a2a8a584f6435d7ffc972eb57b0928eeb0e4a802`
> 合同提交：`b1394e7aa87de3e37648ed6fd61e47a33cf22df8`
> 当前裁决：`STAGE_A_STOP / STATION_NOT_READY / NO_STAGE_B_SEMANTIC_FREEZE`
> 最高允许结论：`NO_IMPLEMENTATION / NO_ECONOMIC_PROBE / NO_PRODUCTION_PROMOTION`

---

## 1. 结论先行

阶段 A 已完整重放 calibration、Carry duration-conditioned 10D、Broad direct-10D、
`calm_carry_breaks_5d`、micro-churn 和高级数据可行性。唯一触发的合同停止条件是：

```text
broad_actual_252_or_direct_skill_insufficient = true
```

Broad 不再缺少 252 个 raw OOF，但直接 10D 增量仍失败：

| Broad 10D 诊断 | 样本 | 正/负 | Brier Skill | ECE | AUC | 裁决 |
|---|---:|---:|---:|---:|---:|---|
| V2 raw Logistic | 252 | 100/152 | +0.82% | 5.69% | 0.556 | Skill 未到 2% |
| V2 rolling-intercept 诊断 | 252 | 100/152 | -1.74% | 6.72% | 0.520 | Skill 失败 |
| 固定 duration/breadth raw 候选 | 252 | 100/152 | -0.48% | 5.31% | 0.540 | Skill 失败 |
| 固定 duration/breadth + rolling intercept | 252 | 100/152 | -3.16% | 9.83% | 0.502 | Skill、ECE 同时失败 |

这正中合同第 9 节“Broad 仍不足 252 个实际可发布 OOF或直接 skill 不足”的停止条件。
因此本轮不创建阶段 B V3 语义规格提交，不修改 feature/state/event/probability 语义，不执行
`PROB-CAL-002 → PROB-CARRY-002 → PROB-BROAD-002` 施工，不进入阶段 D–F。

---

## 2. 证据边界与可复现产物

本审计只读取冻结 V2 天气站基线：

```text
outputs/v3_baseline/v2_features.parquet
outputs/v3_baseline/v2_states.parquet
outputs/v3_baseline/v2_targets.parquet
outputs/v3_baseline/v2_oof.parquet
outputs/v3_baseline/v2_station_summary.json
outputs/v3_baseline/v2_manifest.json
```

边界事实：

- 未读取 `SVXY / SGOV / VXZ` 价格或逐日收益；
- 未打开 `outputs/v2_economic_probe/` 的逐日/报告内容；只在开工和基线 manifest 中核对冻结 hash；
- 未读取或恢复 `/Users/logan/MatVIX_cleanup_quarantine/`；
- 未生成策略、仓位、P&L、NAV 或 HTML；
- 未扫描阈值、模型、窗口、calibrator 或特征组合；
- 只比较合同冻结的 `CURRENT_FREE_PLATT_504 / RAW_LOGISTIC_IDENTITY /
  ROLLING_INTERCEPT_252`；
- confirmation 分区只标记为 `HISTORICAL_REUSE_NOT_UNTOUCHED`；
- 所有 rolling-intercept、duration 与单变量结果均为污染历史诊断，不是独立确认。

正式阶段 A 产物：

| 产物 | 行/列 | SHA-256 |
|---|---:|---|
| `outputs/v3_baseline/v2_manifest.json` | — | `00ff101e2b48403b03b9a84d901c6d9b6903566b653f7604d91233eda65ee574` |
| `outputs/v3_audit/business_audit_daily.parquet` | 3,334 / 307 | `fc60d18ed22ad4cc6ceb1bed7b4f4e726b856a3aa1254f685c455d4d81d27c8d` |
| `outputs/v3_audit/business_audit_summary.json` | — | `6c2b7e2f8e6e44e0a3311b85d20dc5ceb72fee5ead7fb798ceec307a462bb815` |

日账本边界为 `2013-05-20` 至 `2026-08-20`。V2 calibration 的 cohort 样本数逐行重放差异为
0，所有已发布 Platt 行的算术最大绝对误差为 0；Carry/Broad 固定候选的 20-session purge 与
outcome availability 违规均为 0。

复现命令：

```bash
.venv/bin/python -m matvix audit-v3 --project-dir .
.venv/bin/python -m pytest -q tests/test_v3_audit.py
.venv/bin/ruff check src/matvix/v3_audit.py src/matvix/cli.py tests/test_v3_audit.py
.venv/bin/mypy src/matvix/v3_audit.py src/matvix/cli.py
```

---

## 3. Calibration 审计

### 3.1 五事件最新 252 诊断

| 事件 | Current Platt Skill / ECE | Raw Skill / ECE | Rolling intercept Skill / ECE | 最新 252 负 slope |
|---|---:|---:|---:|---:|
| `acute_front_stress_5d` | +7.31% / 5.19% | +8.66% / 5.73% | +7.13% / 3.17% | 0 |
| `front_inversion_5d` | +9.55% / 3.77% | +11.77% / 2.83% | +10.71% / 3.00% | 0 |
| `mid_curve_pressure_accelerates_5d` | +14.31% / 5.65% | +17.00% / 7.21% | +11.79% / 5.08% | 0 |
| `broad_stress_persists_10d` | -4.81% / 14.98%（191） | +0.82% / 5.69% | -1.74% / 6.72% | 80 |
| `carry_environment_recovers_10d` | -6.67% / 21.73% | +13.09% / 11.50% | +9.67% / 6.81% | 173 |

### 3.2 Platt 失败原因

这是已重放的业务根因，不是账本漂移：

- Carry 的逐年 decision-score 均值从 `-1.715` 到 `-0.518`，逐年标准差从 `0.314` 到
  `0.528`；自由 Platt 把不同 rolling fit 的不可比 score 尺度混在同一 504-row cohort；
- Carry 最新 252 行中 173 行 `platt_a<0`。Current Platt 最低预测分位的实际恢复率为
  `50.98%`，最高预测分位只有 `4.00%`，但均值预测从 `37.74%` 升到 `47.00%`，排序被反转；
- Carry 最新实际恢复率为 `26.19%`，504-row Platt cohort 平均正例率为 `42.68%`，冻结因果
  base-rate 均值为 `41.66%`，说明长历史对当前基准率存在明显滞后；
- Broad 最新 252 raw 中有 80 行负 slope。Current Platt 最低/最高预测分位的实际事件率为
  `58.97% / 21.05%`，同样倒置；
- 所有存量 Platt 行逐行算术与 cohort 样本数完全一致，故失败来自自由 slope、score 尺度混合和
  基准率漂移，而不是未来数据、重复 key 或发布算术错误。

固定 slope=1 的 rolling intercept 能消除负 slope，但不能自动创造模型增量：它令存量 Carry
诊断达到 `Skill=+9.67% / ECE=6.81%`，却令 Broad 为 `-1.74% / 6.72%`。该历史结果只说明
`PROB-CAL-002` 的最小方向合理，不授权实现，因为 Broad 已触发停止。

### 3.3 Warm-up 归因

| 事件 | raw OOF | calibrated OOF | total不足 | positive不足 | negative不足 | non-convergence |
|---|---:|---:|---:|---:|---:|---:|
| Acute | 2,387 | 2,142 | 44 | 201 | 0 | 0 |
| Front | 2,075 | 1,773 | 44 | 258 | 0 | 0 |
| Mid | 1,347 | 1,289 | 44 | 14 | 0 | 0 |
| Broad | 261 | 191 | 45 | 25 | 0 | 0 |
| Carry | 1,634 | 1,500 | 40 | 0 | 94 | 0 |

Broad 的 70-row 差额被完整解释为 45 行总样本 warm-up 与 25 行正例门，不是非收敛或数据丢失。

---

## 4. Carry duration-conditioned 10D 审计

Carry onset、eligibility、horizon 与 future predicate 保持 V2 不变。审计复现 206 个 eligible
spell，最大 spell 273 个 formal session；UNKNOWN/UNOBSERVABLE 均中断 spell，下一 eligible
row 从 age=1 重启。

### 4.1 Spell-age 恢复率

| spell age | Development | Confirmation |
|---|---:|---:|
| 1–2 | 65.66%（130/198） | 63.19%（103/163） |
| 3–5 | 56.32%（98/174） | 51.82%（71/137） |
| 6–10 | 41.26%（59/143） | 40.57%（43/106） |
| 11–20 | 19.38%（25/129） | 17.39%（20/115） |
| 21–60 | 9.05%（18/199） | 18.54%（38/205） |
| 61+ | 2.98%（9/302，2 spells） | 29.63%（16/54，2 spells） |

`log1p_carry_spell_age` 与恢复标签的整体 Spearman 为 `-0.468`；206 次 leave-one-spell-out
全部保持负方向。Development/Confirmation 在 1–20 age bins 的方向一致，证明 duration 是直接、
稳定的业务事实；61+ 只有各 2 个 spell，必须保留集中度警告。

现有候选中，VIX9D/VIX convergence 与 VRP 在两个分区发生方向反转；本审计没有把它们加入
duration 模型。固定比较只使用：

```text
V2 predictors
vs
V2 predictors + log1p_carry_spell_age + carry_recovering_flag
```

### 4.2 固定 duration 候选 OOF

| 候选 | 样本 | Brier Skill | ECE | AUC | 结论 |
|---|---:|---:|---:|---:|---|
| raw | 252 | +35.19% | 9.30% | 0.827 | 排序增量强，ECE 失败 |
| rolling intercept | 252 | +34.67% | 7.41% | 0.804 | ECE 比 7% 高 0.41pp |

因此 duration facts 有稳定、直接的 OOF 增量，但首个固定候选仍未同时通过正式 ECE 门。
`PROB-CARRY-002` 保持 REQUIRED/未关闭；不得把普通 Logistic 表述为 survival/hazard 模型。

---

## 5. Broad direct-10D 审计

### 5.1 样本、warm-up 与事件簇

- 完成 target：524（224 positive / 300 negative）；
- raw OOF：261，87 个连续簇，最大 14 sessions；
- calibrated OOF：191，65 个连续簇，最大 12 sessions；
- 最新 252 raw OOF：85 个连续簇，最大 14 sessions；
- 全部完成 target：159 个 eligible spell，最大 20 sessions；
- eligible row 的重叠比例为 69.66%。

这证明 191 行不是“事件极端稀少”，同时也证明逐日样本不能当作 191 个独立事件。

### 5.2 Duration/breadth 方向与直接模型

`log1p_broad_spell_age`、过去 5/10 日 broad day count、F4–F7 level/slope/inversion 在
Development/Confirmation 的单变量方向均未反转；159 次 leave-one-spell-out 的 duration
方向也全部同号。然而固定的最小 duration/breadth Logistic 没有把方向事实转成直接 10D OOF
增量：raw Skill 为 `-0.48%`，rolling-intercept Skill 为 `-3.16%`。

这意味着当前失败已经不是 warm-up 样本口径问题，而是 direct-10D 特征条件模型没有可接受的
概率增量。合同禁止为了通过而搜索 feature subset、窗口、正则、5D 头或 event-specific 算法。

### 5.3 5D 与 Bayesian/hierarchical 边界

审计用固定的“未来 5 日至少 3 个 broad day”只做标签关系核对：与 direct 10D 在 524 个共同
完成样本上的一致率为 81.30%，有 71 个 5D-only positive 和 27 个 10D-only positive。它使用
未来重叠事实，在 t 时点不是 predictor，不能替代 direct 10D 事件。

Bayesian/hierarchical prior 不能新增实际发布 OOF、独立事件簇或直接 10D 信息，本轮未把它作为
初始修复。不得用 prior 收窄参数来声称 Broad 通过。

---

## 6. `calm_carry_breaks_5d` 审计

固定天气标签通过阶段 A 接纳门，但只到 `ACCEPTED_FOR_STAGE_B_SPEC_FREEZE`；由于 Broad 停止，
它没有进入正式事件集合，也没有冻结 predictor set。

| 指标 | 结果 |
|---|---:|
| 当前 eligible | 372 |
| 完成标签 | 371 |
| positive / negative | 158 / 213 |
| Development positive / negative | 93 / 126 |
| Confirmation positive / negative | 65 / 87 |
| 重叠窗口正例簇 | 74 |
| 与现有事件最大精确标签一致率 | 64.42% |

正例组件（可重叠）为：`HARD_ACUTE=26`、`FRONT_INVERSION=9`、`BROAD_PRESSURE=58`、
`CARRY_CLOSED_2=152`。当前 eligibility 与 Broad/Carry eligibility 同日重叠均为 0，说明它不是
现有 Broad 或 Carry 事件的直接改名。

固定候选中，`d1_log_vvix`、`d5_log_vvix`、SKEW level、现有 VRP、SPX 5D momentum、
`d5_near_stress` 与 front-slope 相关量出现两窗同向且 development-fit/confirmation-test 的正
Brier 增量。这些只是预先列名候选的历史单变量诊断，不是经过阶段 B 冻结的正式 predictor set，
更不是正式 rolling-origin PASS。

---

## 7. Micro-churn 审计

原始 phase transition 精确复现为 947；严格 A→B→A 定义得到 34 个 micro-churn：

- 29 个在 2 formal sessions 内返回，5 个在 3 sessions 内返回；
- 20 个按冻结风险序列属于 risk-off，合同禁止对其增加任何阻尼；
- 14 个属于 risk-on，0 个 lateral；
- 34 个都改变了至少一个中间稳定 answer：shock 29、tail 10、repair 8、persistence 2；
- 28 个改变 `calm_carry_breaks_5d` eligibility；
- 2 个改变至少一个正式 probability event status；
- 允许进一步考虑的仅是编号的 14 个 risk-on 候选；20 个 risk-off 候选明确禁止施工。

冻结经济摘要只允许说明经济区间内 507 次 phase change、241 次实际资产切换、278 次 phase
change 未触发交易；本审计没有打开价格账本，也没有计算逐日交集。Micro-churn 被独立复现，
但它不是 `$2,204.41` 成本的直接解释，且 Broad 停止使 `STATE-CHURN-002` 不得施工。

---

## 8. 高级数据可行性

当前正式数据可直接、因果派生并已在审计账本复现：

- `d1_log_vvix`；
- SPX close-to-close 5D momentum；
- VIX9D/VIX convergence；
- 以 prior 756 / minimum 504 为固定窗口的 causal VVIX/VIX coupling residual；
- 现有 EWMA94 VRP proxy。

当前正式数据不能支持：

| 能力 | 缺口 | 独立合同要求 |
|---|---|---|
| SKEW 1M/3M/6M term structure | matched tenor history | source、许可、release/revision PIT |
| Parkinson RV | SPX high/low | 授权 OHLC、session available_at |
| Garman–Klass RV | SPX OHLC | 授权 OHLC、method/version |
| matched-horizon VRP surface | horizon-matched IV/RV | PIT option chain、expiry/forward matching |
| near variance-swap / option surface | SPX option chain | quote PIT、rates、许可与再分发边界 |

没有下载、购买或导入任何新数据。`DATA-OPTION-002=DEFERRED_NOT_P0`。

---

## 9. 缺陷台账

### 9.1 `PROB-CAL-002`

- defect_id：`PROB-CAL-002`
- severity：P1
- layer：PROBABILITY
- observed symptom：Carry 最新 252 中 173 行负 Platt slope，Broad 80 行；两者 reliability
  排序倒置，504-row cohort 对当前基准率滞后。
- reproduction command：`.venv/bin/python -m matvix audit-v3 --project-dir .`
- causal evidence：Platt 算术误差 0、cohort count mismatch 0；score 年度尺度漂移、负 slope 与
  reliability 倒置同时出现。
- business consequence：published probability 可能把风险排序反向，不能诚实驱动状态解释或适配器。
- minimal repair：固定 slope=1，仅拟合 prior outcome-available raw OOF 的 252-row intercept；warm-up
  明示 `IDENTITY_WARMUP`。
- rejected alternatives：自由/负 slope、event-specific calibrator、窗口扫描、同日择优 raw/calibrated。
- affected existing files：未来仅限 `probability/calibration.py`、`walk_forward.py`、`engine.py`、
  配置、Schema、acceptance 与对应测试；本轮未修改。
- semantic/version impact：若施工则 probability/output/model/package 升 3.0.0；本轮未升版。
- station acceptance criterion：无负 slope；逐行 publication 算术、cohort、purge、append invariance
  可重放；三个当前 PASS 事件不退化；五事件各自满足 252/20/20/Skill/ECE 门。
- economic relevance：只修复概率可信度，不直接证明收益。
- status：`AUDIT_CONFIRMED / REQUIRED / NOT_IMPLEMENTED_DUE_CONTRACT_STOP`

### 9.2 `PROB-CARRY-002`

- defect_id：`PROB-CARRY-002`
- severity：P1
- layer：PROBABILITY
- observed symptom：V2 predictors 缺少 spell age；恢复率从 age 1–2 的约 63–66% 降至 age
  11–20 的约 17–19%。
- reproduction command：同上；见 summary 的 `carry_duration_conditioned_10d`。
- causal evidence：206/206 leave-one-spell-out 保持负方向；固定 duration raw OOF Skill +35.19%。
- business consequence：不按 duration conditioning 会系统混合早期可恢复和长 spell 低恢复状态。
- minimal repair：仅增加 `log1p_carry_spell_age` 与 `carry_recovering_flag`，保持 direct 10D 标签。
- rejected alternatives：首版加入 SPX/VVIX/VRP 包、survival library、标签或 horizon 改写。
- affected existing files：未来 state duration、constants/config、walk-forward、output/acceptance 与测试；
  本轮未修改。
- semantic/version impact：若施工则 feature/probability/schema/model/package 3.0.0。
- station acceptance criterion：duration 不跨 UNKNOWN；两窗方向不系统反转；正式 published OOF
  同时满足 Skill≥2%、ECE≤7%，且 reliability 不倒置。
- economic relevance：可能改善 Carry 风险识别，但未读取价格，不能声称改善 Short 风险。
- status：`AUDIT_CONFIRMED / REQUIRED / CANDIDATE_ECE_FAIL / BLOCKED_BY_BROAD_STOP`

### 9.3 `PROB-BROAD-002`

- defect_id：`PROB-BROAD-002`
- severity：P0
- layer：PROBABILITY
- observed symptom：补足 252 actual raw OOF 后 V2 Skill 仅 +0.82%；固定 duration/breadth
  候选 raw Skill -0.48%，rolling-intercept Skill -3.16%、ECE 9.83%。
- reproduction command：同上；见 summary 的 `broad_direct_10d`。
- causal evidence：warm-up 70 行已完全归因；87 raw clusters/65 calibrated clusters 被单独计数；
  direction facts 稳定但不产生 direct-10D probability increment。
- business consequence：五事件正式集合无法全部通过，`PROBABILITY_MODEL=FAIL`，阶段 D/E 被阻断。
- minimal repair：合同允许的首个最小 duration/breadth 候选已经失败；不得继续无规格搜索。
- rejected alternatives：5D 替代 10D、Bayesian prior 伪增样本、feature/window/regularization scan、
  event-specific 算法。
- affected existing files：无；停止条件禁止进入业务代码施工。
- semantic/version impact：无，V2 语义保持冻结。
- station acceptance criterion：direct 10D actual published OOF 必须 252/20/20、Skill≥2%、ECE≤7%，
  并报告 block/cluster stability；当前未满足。
- economic relevance：Broad 未通过时不得冻结或运行 V3 适配器。
- status：`STOP_TRIGGERED / OPEN / NO_SECOND_IMPLEMENTATION`

### 9.4 `PROB-FRAGILITY-002`

- defect_id：`PROB-FRAGILITY-002`
- severity：P1
- layer：PROBABILITY
- observed symptom：V2 适配器没有正式的 calm-carry future-weather break 概率事件。
- reproduction command：同上；见 `calm_carry_breaks_5d`。
- causal evidence：371 completed、158/213 classes、74 overlapping-window clusters、两窗基准率约
  42%、最大现有标签一致率 64.42%。
- business consequence：若未来正式通过，才可能为价格盲 Short adapter 提供 fragility predicate。
- minimal repair：阶段 B 原应一次冻结 weather-only 5D label 与最小 predictor set；本轮未冻结。
- rejected alternatives：ETF 日期筛选、Tail/VRP 直接并入 carry answer、阈值扫描、Dashboard 半成品。
- affected existing files：无；Broad 停止前不得新增正式 event。
- semantic/version impact：未接纳进正式集合，版本不变。
- station acceptance criterion：正式 rolling-origin 252/20/20、Skill≥2%、ECE≤7%、cluster stability，
  且五个 V2 事件均 PASS。
- economic relevance：仅在阶段 D 全通过后才允许适配器消费。
- status：`AUDIT_ACCEPTED_FOR_SPEC_ONLY / NOT_FORMALIZED / BLOCKED_BY_BROAD_STOP`

### 9.5 `STATE-CHURN-002`

- defect_id：`STATE-CHURN-002`
- severity：P2
- layer：STATE / TIMING
- observed symptom：947 次 transition 中有 34 个满足严格 A→B→A micro-churn 定义。
- reproduction command：同上；见 `micro_churn.records` 的编号证据。
- causal evidence：无 gap、无 raw weather cluster boundary、端点五 answer 相同；但中间 answer/
  fragility eligibility 仍可能改变。
- business consequence：14 个 risk-on 候选可能造成短暂开门/解险；20 个 risk-off 候选不可阻尼。
- minimal repair：若未来重开，只能逐编号考虑 14 个 risk-on；risk-off 零新增阻尼。
- rejected alternatives：追求 transition 总数下降、V1 通用计日滞回、延迟 acute/inversion/broad risk-off。
- affected existing files：未来最多 state transition/acceptance 与测试；本轮未修改。
- semantic/version impact：未施工，state/timing 版本不变。
- station acceptance criterion：risk-off timing 逐事件不劣于 V2，原始 event label/eligibility 不变。
- economic relevance：不能把 947 transitions 等同成本；未读取逐日资产切换。
- status：`AUDIT_CONFIRMED_LIMITED / NOT_IMPLEMENTED_DUE_CONTRACT_STOP`

### 9.6 `DATA-OPTION-002`

- defect_id：`DATA-OPTION-002`
- severity：P2
- layer：DATA
- observed symptom：高级 SKEW tenor、SPX OHLC 与 option-chain surface 不在当前正式数据。
- reproduction command：同上；见 `advanced_data_feasibility`。
- causal evidence：当前 schema 只有单一 SKEW 与 SPX close，缺少 OHLC/chain/tenor-match 字段。
- business consequence：不能声称 Parkinson/Garman–Klass、matched VRP 或 option surface 能力。
- minimal repair：只有人类另行批准的数据合同才可开启。
- rejected alternatives：下载、购买、抓取或用现有字段冒充高级数据。
- affected existing files：无。
- semantic/version impact：无。
- station acceptance criterion：独立合同需覆盖 source、许可、PIT、revision、units、missing 和方法版本。
- economic relevance：无当前授权。
- status：`DEFERRED_NOT_P0`

### 9.7 `ADAPTER-002`

- defect_id：`ADAPTER-002`
- severity：P1
- layer：ADAPTER
- observed symptom：阶段 D 入口未满足。
- reproduction command：读取本审计 `contract_stop_conditions`；不得运行经济命令。
- causal evidence：`PROB-BROAD-002` direct-10D gate 失败；Carry 固定候选 ECE 也未过门。
- business consequence：Short V3 probe 为 `NOT_ELIGIBLE`。
- minimal repair：无；必须先关闭全部 P0/P1 station defect并完成阶段 D。
- rejected alternatives：BASE_RATE_ONLY 替代 fragility、Tail/VVIX/VRP 并列硬门、提前读取价格。
- affected existing files：无。
- semantic/version impact：无适配器规格冻结、无代码、无版本变化。
- station acceptance criterion：合同第 6.5 节全部满足且站内验收提交后工作树干净。
- economic relevance：阶段 F 未授权。
- status：`BLOCKED_BY_STAGE_A_STOP`

---

## 10. Scope-to-defect 与变更预算

| 变更 | 目的 | defect/阶段 | 语义影响 |
|---|---|---|---|
| `src/matvix/v3_audit.py` | 唯一阶段 A 审计入口 | Stage A 全六项 | 无业务语义变化 |
| `src/matvix/cli.py` 的 `audit-v3` | 调用唯一入口 | Stage A | 无 |
| `tests/test_v3_audit.py` | calibration warm-up 与 weather-only fragility 标签聚焦测试 | Stage A | 无 |
| `MATVIX_V3_AUDIT.md` | 缺陷台账与停止裁决 | Stage A | 明确不构成阶段 B 规格 |

新增非生成 Python 与测试为 1,498 行，不超过 1,500；新增跟踪文件 3 个，不超过 6；无新增依赖、
无模型 registry、无 feature search、无新 renderer。由于已触发 Broad 停止，后续净新增预算不再使用。

---

## 11. 最终阶段 A 裁决

直接回答合同问题：

1. Platt 失败来自 rolling score 尺度不可比、自由负 slope 和 504-row 基准率滞后；算术/PIT 重放无误。
2. Carry duration facts 跨两窗稳定并显著提高 raw OOF 排序/Skill，但固定候选 ECE 仍为 7.41%，未关闭。
3. Broad direct 10D 没有通过；它不是靠 5D/prior/样本口径可修复的问题。
4. `calm_carry_breaks_5d` 通过阶段 A 接纳门，但未正式化、未获得模型 PASS。
5. 严格 micro-churn 有 34 个；20 个 risk-off 禁止阻尼，14 个 risk-on 也因停止条件未施工。
6. 五个 V2 正式事件没有形成 V3 独立模型结论；阶段 C/D 从未开始。
7. V3 vs V2 固定探针未授权、未运行，故没有 Short 帕累托改善结论。
8. 本文件全部概率/duration/fragility 结果都是历史复用诊断；真正前向观察尚未开始。
9. 高级 SKEW tenor、SPX OHLC、matched VRP/option surface 因数据权利和字段缺口延后。

最终状态：

```text
STATION_NOT_READY
STAGE_A_STOP
NO_STAGE_B_SEMANTIC_FREEZE
NO_V3_PROBABILITY_OR_STATE_IMPLEMENTATION
NO_ADAPTER
NO_ECONOMIC_PROBE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```
