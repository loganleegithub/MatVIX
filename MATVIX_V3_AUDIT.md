# MatVIX V3 阶段 A 业务审计与阶段 B 语义冻结

> 合同：`MATVIX_V3_CONSTRUCTION_PLAN.md` v1.3
> 审计日期：2026-08-22
> 最近修订：2026-08-23
> 分支：`codex/matvix-v3`
> V2 代码基线：`a2a8a584f6435d7ffc972eb57b0928eeb0e4a802`
> 原合同提交：`b1394e7aa87de3e37648ed6fd61e47a33cf22df8`
> 合同修订提交：`6eaa18b4bd21fc6851eb2e22c2234740a5a166b0`
> v1.2 修订提交：`1c7981eeaad5b8a967f816530f3750fe35ca4880`
> v1.3 修订提交：`281e29aec7fb042311824fc4ac3f5555de6e5ddd`
> 当前裁决：`ADAPTER-002=REJECTED_BY_FROZEN_HISTORICAL_PROBE`
> 下一项：`CURRENT CONTRACT STOPPED / PROSPECTIVE OBSERVATION ONLY`
> 最终结论：`NO_COMPREHENSIVE_INCREMENT / NO_PRODUCTION_PROMOTION`

---

## 1. 结论先行

阶段 A 已完整重放 calibration、Carry duration-conditioned 10D、Broad direct-10D、
`calm_carry_breaks_5d`、micro-churn 和高级数据可行性。按合同 v1.0，当时唯一触发的停止条件是：

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

这正中合同 v1.0 第 9 节“Broad 仍不足 252 个实际可发布 OOF或直接 skill 不足”的停止条件，
因此提交 `3f0e394` 当时合法停止且没有进入阶段 B–F。

随后的人类明确决定以合同 v1.1 将 Broad direct-10D 条件模型关闭为 `BASE_RATE_ONLY` 产品范围，
并正式接纳 Fragility 与受限 risk-on churn。这只解除 Broad 的旧阻断，不把上述失败改写成通过，
也不预设 Carry、Fragility、状态或经济结果。本文第 12 节现以纯文档冻结阶段 B 规格；阶段 C 仅按：

```text
PROB-CAL-002
→ PROB-CARRY-002
→ PROB-CARRY-SATURATION-003 (only if v1.2 controlled exception is needed)
→ PROB-FRAGILITY-002
→ STATE-CHURN-002
```

逐项施工。任一项触发新合同停止条件时仍须立即停止。

`PROB-CARRY-002` 的第一版正式重建随后以 +34.67% Brier Skill、7.413% ECE 失败并停止。第 13.3
节先完成结果后只读残差审计，2026-08-23 的人类决定再以合同 v1.2 只授权一个替换式 bounded-age
候选：cap=20、不改任何门槛、不扫描、不读价格、只正式重建一次。该唯一重建通过原门；随后
Fragility 唯一正式候选因 published OOF 不足触发第 11.1 节停止：

```text
PROB-CARRY-SATURATION-003=PASS / HISTORICAL_RESEARCH_SUPPORT
→ PROB-FRAGILITY-002=REJECTED_INSUFFICIENT_PUBLISHED_OOF
→ CONTRACT_STOP
```

2026-08-23 的人类随后以合同 v1.3 选择第四路径：不改 252 门、不把 114 条 OOF 升格为有效概率，
而是把正式气象站冻结为 acute/front/mid/carry 四个条件模型加 Broad 基准率参考；Fragility 的正式
拒绝保持不变。唯一候选数值输出只可在阶段 D 通过后，以
`UNQUALIFIED_FRAGILITY_VETO_SHADOW` 在 adapter/policy 层接受一次只减仓的历史证伪。该决定解除的
是正式产品范围阻断，不是统计门；当前恢复顺序为：

```text
STATE-CHURN-002
→ STAGE_D: FOUR CONDITIONAL MODELS + ONE BASE-RATE REFERENCE
→ STAGE_E: PURE-DOCUMENT VETO SHADOW FREEZE
→ ADAPTER-002
→ STAGE_F: ONE ECONOMIC PROBE
```

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

固定天气标签在阶段 A 只到 `ACCEPTED_FOR_STAGE_B_SPEC_FREEZE`；合同 v1.1 随后解除 Broad
范围阻断，并由本文第 12.5 节正式接纳事件、一次冻结 predictor set。以下仍是 Stage-A 历史证据，
不是正式 rolling-origin PASS。

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
但它不是 `$2,204.41` 成本的直接解释。合同 v1.1 后仅第 12.7 节冻结的 risk-on phase publication
确认获得施工授权。

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
- reproduction command：`.venv/bin/python -m matvix train-probabilities --full-rebuild
  --project-dir .`，随后 `.venv/bin/python -m matvix accept-real --date 2026-08-20
  --project-dir .`。
- causal evidence：Platt 算术误差 0、cohort count mismatch 0；score 年度尺度漂移、负 slope 与
  reliability 倒置同时出现。
- business consequence：published probability 可能把风险排序反向，不能诚实驱动状态解释或适配器。
- minimal repair：固定 slope=1，仅拟合 prior outcome-available raw OOF 的 252-row intercept；warm-up
  明示 `IDENTITY_WARMUP`。
- rejected alternatives：自由/负 slope、event-specific calibrator、窗口扫描、同日择优 raw/calibrated。
- affected existing files：`probability/calibration.py`、`walk_forward.py`、`engine.py`、配置合同、
  Schema、acceptance、dashboard、pipeline 与对应测试；一次性 Stage-A Python 脚手架已按 12.9 删除。
- semantic/version impact：probability/output/model/package 已升 3.0.0；artifact contract 已升 2。
- station acceptance criterion：无负 slope；逐行 publication 算术、cohort、purge、append invariance
  可重放；三个当前 PASS 事件不退化；四个必需条件模型各自满足 252/20/20/Skill/ECE 门。
- economic relevance：只修复概率可信度，不直接证明收益。
- status：`IMPLEMENTED / FORMAL_HISTORICAL_REPLAY_PASS`

### 9.2 `PROB-CARRY-002`

- defect_id：`PROB-CARRY-002`
- severity：P1
- layer：PROBABILITY
- observed symptom：V2 predictors 缺少 spell age；恢复率从 age 1–2 的约 63–66% 降至 age
  11–20 的约 17–19%。
- reproduction command：`.venv/bin/python -m matvix build-history --project-dir .`，随后
  `.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .` 与
  `.venv/bin/python -m matvix accept-real --date 2026-08-20 --project-dir .`。
- causal evidence：206/206 Stage-A leave-one-spell-out 保持负方向；正式 duration raw OOF Skill
  +35.19%。rolling-intercept published Skill +34.67%，但 ECE 7.413% 超过 7.000% 上限；
  `2026-08-13` 最近 eligible 日的严格 as-of ECE 为 8.312%。
- business consequence：不按 duration conditioning 会系统混合早期可恢复和长 spell 低恢复状态。
- minimal repair：仅增加 `log1p_carry_spell_age` 与 `carry_recovering_flag`，保持 direct 10D 标签。
- rejected alternatives：首版加入 SPX/VVIX/VRP 包、survival library、标签或 horizon 改写。
- affected existing files：state duration、constants/config、probability history fingerprint、acceptance
  与测试；未新增依赖或候选特征。
- semantic/version impact：feature/probability/schema/model/package 为 3.0.0，标签与 horizon 不变。
- station acceptance criterion：duration 不跨 UNKNOWN；两窗方向不系统反转；正式 published OOF
  同时满足 Skill≥2%、ECE≤7%，且 reliability 不倒置。
- economic relevance：可能改善 Carry 风险识别，但未读取价格，不能声称改善 Short 风险。
- status：`IMPLEMENTED / FORMAL_HISTORICAL_REPLAY_FAIL_ECE / CONTRACT_STOP_RECORDED /
  V1_2_EXCEPTION_ONLY`

### 9.3 `PROB-BROAD-002`

- defect_id：`PROB-BROAD-002`
- severity：P2
- layer：PROBABILITY
- observed symptom：补足 252 actual raw OOF 后 V2 Skill 仅 +0.82%；固定 duration/breadth
  候选 raw Skill -0.48%，rolling-intercept Skill -3.16%、ECE 9.83%。
- reproduction command：同上；见 summary 的 `broad_direct_10d`。
- causal evidence：warm-up 70 行已完全归因；87 raw clusters/65 calibrated clusters 被单独计数；
  direction facts 稳定但不产生 direct-10D probability increment。
- business consequence：direct-10D 条件模型不能诚实发布；V3 只能把该问题保留为历史基准率参考。
- minimal repair：不施工模型；保留 10D 事件语义并强制 `BASE_RATE_ONLY / HISTORICAL_REFERENCE`。
- rejected alternatives：5D 替代 10D、Bayesian prior 伪增样本、feature/window/regularization scan、
  event-specific 算法。
- affected existing files：概率配置、publication、acceptance、Schema 与测试；Broad predictor 列表为空。
- semantic/version impact：概率发布与 Schema 已升 3.0.0；事件标签语义不变。
- station acceptance criterion：逐行因果 base rate、PIT、censoring、append invariance 与
  `BASE_RATE_ONLY` 标记一致；不参加模型 Skill/ECE 门且绝不被称为模型 PASS。
- economic relevance：只作为天气历史参考，不直接进入 Fragility adapter 谓词。
- status：`IMPLEMENTED / BASE_RATE_REFERENCE_PASS / NO_MODEL_PASS_CLAIM`

### 9.4 `PROB-FRAGILITY-002`

- defect_id：`PROB-FRAGILITY-002`
- severity：P1
- layer：PROBABILITY
- observed symptom：V2 适配器没有正式的 calm-carry future-weather break 概率事件。
- reproduction command：同上；见 `calm_carry_breaks_5d`。
- causal evidence：371 completed、158/213 classes、74 overlapping-window clusters、两窗基准率约
  42%、最大现有标签一致率 64.42%。
- business consequence：唯一正式候选没有资格进入气象站概率层；任何下游使用都必须与正式站隔离，
  且只能减少既有 Short 暴露。
- minimal repair：无概率修复。保留唯一候选失败证据并从正式运行表面移除；v1.3 仅允许阶段 E
  复现同一候选为 `UNQUALIFIED_RESEARCH_SCORE`。
- rejected alternatives：ETF 日期筛选、Tail/VRP 直接并入 carry answer、阈值扫描、Dashboard 半成品。
- affected existing files：候选曾涉及 feature/config/targets/walk-forward/publication/acceptance/Schema/
  Dashboard 与测试；这些正式路径已从跟踪树移除。后续只允许 adapter 隔离实现。
- semantic/version impact：不属于正式 V3 event/schema/model surface；失败候选只保留审计 hash。
- station acceptance criterion：`FRAGILITY_BOUNDARY=PASS` 要求正式目录、Schema、Dashboard、daily
  output 与模型计数均不含该事件，并保留 114/252 `NOT_ELIGIBLE` 证据。
- economic relevance：阶段 D 通过后，只可作为 exposure-reducing veto shadow 接受一次历史证伪；
  经济结果不能提升其概率资格。
- status：`CLOSED_BY_SCOPE / FORMAL_REJECT_RETAINED / NOT_A_MODEL_PASS`

### 9.5 `STATE-CHURN-002`

- defect_id：`STATE-CHURN-002`
- severity：P2
- layer：STATE / TIMING
- observed symptom：947 次 transition 中有 34 个满足严格 A→B→A micro-churn 定义。
- reproduction command：同上；见 `micro_churn.records` 的编号证据。
- causal evidence：无 gap、无 raw weather cluster boundary、端点五 answer 相同；但中间 answer/
  fragility eligibility 仍可能改变。
- business consequence：14 个 risk-on 候选可能造成短暂开门/解险；20 个 risk-off 候选不可阻尼。
- minimal repair：只对 14 个 risk-on 所代表的三个 phase 方向实施一次因果确认；risk-off 零新增阻尼。
- rejected alternatives：追求 transition 总数下降、V1 通用计日滞回、延迟 acute/inversion/broad risk-off。
- affected existing files：最多 state transition、state config、acceptance 与测试。
- semantic/version impact：phase publication 语义与 state/model/package 升 3.0.0；answer/event 不变。
- station acceptance criterion：risk-off timing 逐事件不劣于 V2，原始 event label/eligibility 不变。
- economic relevance：不能把 947 transitions 等同成本；未读取逐日资产切换。
- status：`IMPLEMENTED / FORMAL_HISTORICAL_REPLAY_PASS / RISK_OFF_DELAY_ZERO`

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
- observed symptom：正式 Fragility 因 114/252 被拒绝；v1.3 只授权四模型站通过后的隔离减仓 veto。
- reproduction command：读取本审计 `contract_stop_conditions`；不得运行经济命令。
- causal evidence：Broad 基准率与 bounded Carry 已通过；Fragility 唯一候选只有 114 条完成 OOF，
  确定性 VVIX/SKEW 规则和 acute 替代也没有充分捕获其天气正例。
- business consequence：阶段 D 前 Short V3 probe 仍为 `NOT_ELIGIBLE`；阶段 D 后只允许研究型减仓门。
- minimal repair：先完成 `STATE-CHURN-002` 与四模型阶段 D，再纯文档冻结唯一 shadow mapping。
- rejected alternatives：Fragility BASE_RATE_ONLY、正式概率特批、Tail/VVIX/VRP 第二硬门、确定性红灯、
  acute 替代、阈值扫描、提前读取价格。
- affected existing files：`fragility_shadow.py`、`economic_probe.py`、`cli.py`、通用 OOF feature override、
  acceptance 拒绝证据 hash 与聚焦测试；正式事件、Schema、state、Dashboard 无变化。
- semantic/version impact：adapter spec `1.0.0`；正式 feature/state/probability/package version 不变。
- station acceptance criterion：合同第 6.5 节四模型、Broad reference 与 Fragility boundary 全部满足，
  且站内验收提交后工作树干净。
- economic relevance：阶段 F 只可运行一次；成功最多 `HISTORICAL_RESEARCH_SUPPORT`，失败即拒绝。
- status：`ONE_PROBE_COMPLETE / REJECTED_BY_FROZEN_HISTORICAL_PROBE`

### 9.8 `PROB-CARRY-SATURATION-003`

- defect_id：`PROB-CARRY-SATURATION-003`
- severity：P1
- layer：PROBABILITY
- observed symptom：`PROB-CARRY-002` 的最新 252 个正式 published OOF 保留 +34.67% Brier
  Skill，但 ECE 为 7.413%；最低概率 quintile 的预测/实际为 5.82%/13.73%，并由长 spell 主导。
- reproduction command：先只读关联 `data/probability/oof_ledger.parquet` 与
  `data/processed/states.parquet`；合同升版后只执行一次第 9.2 节冻结的正式命令链。
- causal evidence：最低 quintile 51 行全部 `carry_spell_age>20`，其中 68.63% 为 age>60；但 51
  行只来自 2 个 spell，全部 7 个正例集中在其中 1 个 spell。既有 published OOF 在 development
  的 age>20 行为 4.58%/7.94%（预测/实际，n=340），confirmation 为 17.07%/20.85%
  （n=259），两窗均为同向低估。该证据确认的是长 spell 残差，不证明任何修补必然通过。
- business consequence：未受限的 `log1p_carry_spell_age` 可能把极长、且独立 spell 数很少的尾部
  外推为过低恢复概率；但不能用集中样本伪称稳定的新规律。
- minimal repair：仅允许考虑
  `bounded_log1p_carry_spell_age = log(1 + min(carry_spell_age, 20))`，并替换而非并列保留旧
  `log1p_carry_spell_age`。20 只来自阶段 A 事先冻结的 `11–20 / 21–60` 业务分箱边界，不来自
  cap 扫描。
- rejected alternatives：ECE 放宽至 7.5%、Skill/ECE 综合效用特批、age>15 事后惩罚、cap 扫描、
  新 calibrator/window/model、同时保留 bounded/unbounded age、外部特征包。
- affected existing files：仅涉及 Carry duration fact、唯一 predictor 配置、重放完整性验收与聚焦
  测试；未改变标签、horizon、eligibility、模型或校准器。
- semantic/version impact：合同 v1.2 与本节已以纯文档冻结唯一替换语义；现有 V3
  feature/probability/schema/model/package 版本仍为 3.0.0。
- station acceptance criterion：原 252/20/20、Brier Skill≥2%、ECE≤7% 与可靠性门一字不改；
  development/confirmation 及 spell 集中度必须并列报告；若唯一正式重建失败则停止，不得第三次尝试。
- economic relevance：仅修复气象站概率；阶段 D 前仍不得读取产品价格或运行经济探针。
- status：`IMPLEMENTED / FORMAL_HISTORICAL_REPLAY_PASS / HISTORICAL_RESEARCH_SUPPORT`

---

## 10. Scope-to-defect 与变更预算

| 变更 | 目的 | defect/阶段 | 语义影响 |
|---|---|---|---|
| `src/matvix/v3_audit.py` | 唯一阶段 A 审计入口 | Stage A 全六项 | 无业务语义变化 |
| `src/matvix/cli.py` 的 `audit-v3` | 调用唯一入口 | Stage A | 无 |
| `tests/test_v3_audit.py` | calibration warm-up 与 weather-only fragility 标签聚焦测试 | Stage A | 无 |
| `MATVIX_V3_AUDIT.md` | 阶段 A 证据、缺陷台账与阶段 B 规格 | Stage A/B | 第 12 节构成纯文档语义冻结 |

阶段 A 新增非生成 Python 与测试为 1,498 行，不超过 1,500；新增跟踪文件 3 个，不超过 6；无新增
依赖、无 model registry、无 feature search、无新 renderer。合同 v1.1 重开施工后的净预算处理按
第 12.9 节执行。

---

## 11. 合同 v1.0 下的阶段 A 历史裁决

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

提交 `3f0e394` 时的历史状态（已由合同 v1.1 解除 Broad 范围阻断，但证据不变）：

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

### 11.1 `PROB-FRAGILITY-002` 唯一正式重建与停止裁决

按第 12.5 节冻结语义完成了唯一候选：当前 eligibility、四条完整 5D 天气 future facts、各自
formal-vintage censoring、新增 `d1_log_vvix` / `spx_5d_log_momentum` 因果事实，以及以下固定
predictor 顺序均先由聚焦测试锁定：

```text
p_neg_front_slope30
p_d1_log_vvix
p_d5_log_vvix
p_neg_spx_5d_log_momentum
```

候选代码的聚焦测试、243 项完整 pytest、Ruff、Mypy、doctor 与 Schema 验证通过。随后只运行一次
合同正式链：

```bash
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real --date 2026-08-20 --project-dir .
```

标签 cohort 与阶段 A 完全一致：371 个 completed，158/213 正负类。可是 252 个完成标签首先只能
作为模型训练集，首条 raw/published OOF 到 `2023-06-16` 才出现；截至固定验收日只形成 115 条
published OOF，其中 114 条已 outcome-available，正/负为 44/70。正式模型门结果为：

| 门 | 固定要求 | 实际 | 裁决 |
|---|---:|---:|---|
| completed published OOF | 252 | 114 | **FAIL** |
| 正类 | 20 | 44 | PASS |
| 负类 | 20 | 70 | PASS |
| Brier Skill | ≥2% | 不计算 | NOT_ELIGIBLE |
| ECE | ≤7% | 不计算 | NOT_ELIGIBLE |

`real_acceptance_2026-08-20.json` 的 14 个账本、PIT、发布与运行时完整性控制均通过；其中
`v3_oof_calibration_integrity` 对该事件明确记录
`published_oof=115 / completed_published_available=114 / validation_complete=false / accepted=false`。
这些控制的 PASS 只证明失败证据内部一致，不能替代 252 样本模型门，也不能写成 Fragility PASS。

唯一正式候选产物 hash：

```text
states.parquet             e22b51acccaea60f97dcfe98ce561ae700b87e1239a5ca66c8f6674e5f8c4d16
target_ledger.parquet      9e77c5be6e2f4a2b387d877b7f5184376f922301a2585077f0704382a920523e
oof_ledger.parquet         44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770
artifact_contract.json     42e54a87ab5d365ea3cf90dbd9bfa513d0b9a3456e8fa08c3a11f42f7a3dba00
daily/2026-08-20.json      d24de3122be8fdd060d07b8f9d9bec7f03c65eec15bd3f19e678168653360eef
real_acceptance.json       54c8d59d9052de39c5d1fe90e3ba07cb987eb45942a36818ce9950e52a325f31
```

合同第 5.4 节要求未通过完整概率门时从正式事件集合彻底拒绝且不留 Dashboard 半成品，因此候选
业务代码、配置、Schema、Dashboard 与测试已从当前跟踪树移除；没有尝试第二组 feature、模型、
窗口、阈值或 calibrator。`STATE-CHURN-002`、阶段 D、适配器以及阶段 E/F 均未启动，且未读取
SVXY/SGOV/VXZ 价格或冻结经济探针逐日/报告内容。

正式裁决：

```text
PROB-CAL-002=PASS
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
PROB-CARRY-002=HISTORICAL_FIRST_ATTEMPT_FAIL_RETAINED
PROB-CARRY-SATURATION-003=PASS_HISTORICAL_RESEARCH_SUPPORT
PROB-FRAGILITY-002=REJECTED_INSUFFICIENT_PUBLISHED_OOF
FORMAL_FRAGILITY_MODEL=NOT_ELIGIBLE
CONTRACT_STOP=TRUE
STATE-CHURN-002=NOT_AUTHORIZED_TO_START_AFTER_STOP
STAGE_D=BLOCKED
ADAPTER=BLOCKED
ECONOMIC_PROBE=NOT_RUN
PRODUCT_PRICES_READ=FALSE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 11.2 合同 v1.3 的第四路径裁决

本节只使用天气审计账本与唯一候选的冻结 OOF 证据，`PRODUCT_PRICES_READ=FALSE`。三条替代路径
在升版前按其原始主张做了机械核对：

1. **确定性物理断路器未获接纳。** 用现有 causal percentile 语义固定复现
   `d1_log_vvix > 2.5σ OR SKEW percentile >= 95%`，在 371 个完成 calm-carry 标签上触发 70 次，
   `TP/FP/FN/TN=36/34/122/179`，sensitivity 22.78%、precision 51.43%、FPR 15.96%。其中
   VVIX 2.5σ 单独只触发 1 次；组合只捕获 4/26 个 `HARD_ACUTE`、0/9 个 front inversion、
   12/58 个 broad-pressure 和 33/152 个 carry-closed-2 组件。它不是已经证明可直接清仓的物理定律。
2. **全市场 acute 模型不能替代子状态。** 正式 acute 模型自身通过并保留；但在 365 个可共同匹配的
   calm-carry 完成行上，用同样预冻结的 `published score > causal base rate` 只触发 30 次，
   `TP/FP=10/20`、正例 sensitivity 6.41%，且未捕获 26 个 `HARD_ACUTE` fragility 组件中的任何一个。
   因此不把它改写成 Short 专用 Fragility 模型。
3. **日历跨度不能替代 published OOF。** 114 个完成 published OOF 跨 2023–2026，年度计数为
   `33/46/32/3`，正负为 44/70，但只有 19 个独立正例簇；即使采用外部建议的 50-cluster 辅助条件，
   也未达门。252 样本门与 completed/outcome-available 口径保持不变。

由此冻结第四路径：

```text
FORMAL_STATION_MODELS = acute + front + mid + carry
BROAD = BASE_RATE_ONLY_REFERENCE
PROB-FRAGILITY-002 = CLOSED_BY_SCOPE / FORMAL_REJECT_RETAINED
FORMAL_FRAGILITY_EVENT = ABSENT

ADAPTER_RESEARCH_HYPOTHESIS = UNQUALIFIED_FRAGILITY_VETO_SHADOW
allowed direction = SVXY -> SGOV only
threshold = frozen shadow_score > frozen causal_base_rate
formal probability/model claim = prohibited
economic runs = exactly one, after Stage-D and pure-document Stage-E freeze
```

未来稀疏概率候选新增 `OOF_CAPACITY_PRECHECK`：在业务实现前按 eligibility、training minimum、purge、
horizon、outcome availability 与固定截止日计算 completed published OOF 的机械上限；上限低于正式门
即停止概率施工。该治理只防止无效实现，不为当前 Fragility 补样本或改变既有失败。

v1.3 恢复施工时的裁决：

```text
PROB-CAL-002=PASS
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
PROB-CARRY-SATURATION-003=PASS_HISTORICAL_RESEARCH_SUPPORT
PROB-FRAGILITY-002=CLOSED_BY_SCOPE_FORMAL_REJECT_RETAINED
STATE-CHURN-002=NEXT_AUTHORIZED
STAGE_D=AUTHORIZED_AFTER_CHURN
ADAPTER-002=AUTHORIZED_ONLY_AFTER_STAGE_D_AND_STAGE_E_DOC_FREEZE
ECONOMIC_PROBE=ONE_RUN_ONLY_AFTER_ADAPTER_COMMIT
PRODUCT_PRICES_READ=FALSE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

## 12. 阶段 B：V3 语义与 Schema 冻结

本节最初由合同 v1.1 授权，是第一行业务语义代码修改前的阶段 B 规格。合同 v1.2 只替换第 12.4
节的 Carry transformed-age 字段。合同 v1.3 在第 11.2 节的人类范围决定下，只把未达样本门的
Fragility 从正式事件/Schema/模型计数移除，并授权阶段 D 后另行冻结 adapter shadow；其历史标签、
候选公式、hash 和失败行为不根据经济结果修改。

### 12.1 版本与正式事件目录

V3 就地替换 V2 运行语义，不保留 `_v2/_v3` 双引擎或运行开关：

```text
MODEL_ID = MATVIX_CBOE_CORE_V3
package_version = 3.0.0
schema_version = 3.0.0
feature_version = 3.0.0
state_version = 3.0.0
probability_version = 3.0.0
probability_artifact_contract_version = 2
```

正式目录冻结为：

| event_id | horizon | publication policy | predictors |
|---|---:|---|---|
| `acute_front_stress_5d` | 5 | `FEATURE_CONDITIONAL_REQUIRED` | V2 六项不变 |
| `front_inversion_5d` | 5 | `FEATURE_CONDITIONAL_REQUIRED` | V2 四项不变 |
| `mid_curve_pressure_accelerates_5d` | 5 | `FEATURE_CONDITIONAL_REQUIRED` | V2 六项不变 |
| `broad_stress_persists_10d` | 10 | `BASE_RATE_ONLY_EXEMPT` | 无；禁止训练模型 |
| `carry_environment_recovers_10d` | 10 | `FEATURE_CONDITIONAL_REQUIRED` | V2 六项加 bounded age 与 recovering flag |
| `calm_carry_breaks_5d` | 5 | `FORMAL_REJECT_RETAINED / NOT_IN_RUNTIME` | 唯一失败候选四项只作审计证据 |

因此阶段 D 验收对象是四个条件模型与一个 Broad 基准率参考，并单独检查
`FRAGILITY_BOUNDARY`。任何必需条件模型缺样本或未通过门，均不能用 `BASE_RATE_ONLY` 或
unqualified shadow 抵消 `PROBABILITY_MODEL=FAIL`。

### 12.2 统一 BaseRate、Logistic 与 rolling intercept

每个事件在 prediction session `t` 的因果基准率只使用 `t` 的 `decision_as_of` 前已经
outcome-available、且 `prediction_date < t` 的完成标签：

```text
cohort = latest 756 completed eligible labels
minimum = 252
alpha = 1
beta = 1
base_rate = (positive + alpha) / (samples + alpha + beta)
```

BaseRate 不使用 20-session model purge；它仍受 outcome availability 和 prediction-date 严格过去门。
所有 feature-conditional 原始模型继续使用固定 Logistic：最近 1,500 个完整训练样本、最少 252、
正负各至少 30、20 formal-session purge、`C=1/lbfgs/L2` 与锁定 sklearn 版本不变。

二级校准唯一允许公式：

```text
z_t = logit(clip(raw_probability_t, 1e-6, 1 - 1e-6))
published_probability_t = expit(z_t + intercept_b_t)

calibration cohort:
    prior outcome-available raw OOF only
    latest 252
    positive >= 20
    negative >= 20
    slope = 1.0 fixed

intercept_b:
    unique root in [-40, 40] where
    mean(expit(logit(raw_probability_i) + b)) == mean(label_i)
```

不得保留、调用或发布自由 Platt slope。`CURRENT_FREE_PLATT_504` 只存在于 V2 Git 基线与阶段 A
证据。逐行发布状态冻结为：

```text
raw model unavailable, BaseRate ready:
    model_status = BASE_RATE_ONLY
    probability_kind = HISTORICAL_REFERENCE
    calibration_method = NOT_APPLICABLE
    probability = base_rate

raw model ready, calibration class gate not ready:
    model_status = IDENTITY_WARMUP
    probability_kind = FEATURE_CONDITIONAL
    calibration_method = IDENTITY_WARMUP
    probability = raw_probability

raw model and calibration ready, as-of model gate earned:
    model_status = CALIBRATED_MODEL
    probability_kind = FEATURE_CONDITIONAL
    calibration_method = ROLLING_INTERCEPT_252
    probability = expit(logit(raw_probability) + intercept_b)

raw/calibration ready but as-of model gate not earned:
    public daily event falls back to BASE_RATE_ONLY;
    OOF ledger retains the frozen candidate output for station acceptance.
```

Broad 例外不进入原始 Logistic 或校准代码路径。BaseRate ready 时固定为第一种状态；不足 252 时
为 `INSUFFICIENT_HISTORY`，不得使用短 cohort、prior 或合成样本。

### 12.3 OOF 与 daily event Schema 3.0.0

OOF ledger 就地替换 V2 Platt 字段，至少持久化：

```text
event_id / prediction_date / outcome_available_at / label / label_status
raw_probability / published_probability
base_rate_at_prediction / base_rate_samples / base_rate_positive / base_rate_negative
training_samples / training_positive / training_negative
training_latest_prediction_date / training_latest_outcome_available_at / converged
calibration_method / calibration_samples / calibration_positive / calibration_negative
intercept_b
```

V3 不保留 `decision_score / base_probability / calibrated_probability / platt_a / platt_b` 的平行正式
字段。历史 V2 列只在冻结 Git/artifact 中存在。

`daily_output.schema.json` 不得包含已拒绝的第六个 Fragility event。五个正式 event（四个条件模型
加 Broad reference）的 required 字段为：

```text
event_status
model_status
probability_kind
raw_probability
probability                  # published probability
base_rate
uplift
calibration_method
calibration_samples
calibration_positive
calibration_negative
intercept_b
valid_through_session
interpretation
```

枚举固定为：

```text
model_status:
    CALIBRATED_MODEL | IDENTITY_WARMUP | BASE_RATE_ONLY |
    INSUFFICIENT_HISTORY | NOT_RUN
probability_kind:
    FEATURE_CONDITIONAL | HISTORICAL_REFERENCE | null
calibration_method:
    ROLLING_INTERCEPT_252 | IDENTITY_WARMUP | NOT_APPLICABLE | null
```

交叉字段规则：

- `CALIBRATED_MODEL`：raw/base/probability/intercept 均有限，method 为 rolling intercept，
  `uplift = probability - base_rate`；
- `IDENTITY_WARMUP`：`probability == raw_probability`、`intercept_b=null`；
- `BASE_RATE_ONLY`：`raw_probability=null`、`probability == base_rate`、`uplift=0`、method 为
  `NOT_APPLICABLE`；
- `NOT_APPLICABLE/UNOBSERVABLE`：所有概率与 calibration 数值均为 null；
- Broad eligible 行只允许 `BASE_RATE_ONLY` 或 `INSUFFICIENT_HISTORY`。

### 12.4 `PROB-CARRY-SATURATION-003` bounded duration facts

`carry_environment_recovers_10d` 的 onset、eligibility、10-session label、future `OPEN` predicate、
censoring 与 outcome availability 全部不变。新增字段逐行定义：

```text
carry_spell_age:
    event_status == ELIGIBLE  -> prior consecutive age + 1, first row = 1
    event_status == NOT_APPLICABLE -> null and reset
    event_status == UNOBSERVABLE   -> null and hard reset
    a formal-session gap           -> hard reset

bounded_log1p_carry_spell_age = log(1 + min(carry_spell_age, 20))

carry_recovering_flag:
    ELIGIBLE and carry_environment_state == RECOVERING -> 1.0
    ELIGIBLE otherwise                                 -> 0.0
    non-ELIGIBLE                                       -> null
```

正式 predictor 顺序一次冻结为：

```text
repair_scaled
p_d5_front_slope30
p_neg_d5_near_stress
p_d5_f4_f7_slope30
p_neg_d5_log_f4_f7_level
shock_scaled
bounded_log1p_carry_spell_age
carry_recovering_flag
```

原 `log1p_carry_spell_age` 被替换，不得与 bounded 字段同时存在于 runtime state、配置、模型
fingerprint 或验收列中。20 来自阶段 A 预冻结 `11–20 / 21–60` 分箱边界，不允许扫描。不得加入
SPX、VVIX、VRP、VIX9D convergence 或新的 hazard/survival library。标签、horizon、eligibility、
Logistic、regularization、rolling fit、校准、purge、252/20/20、Skill≥2% 与 ECE≤7% 全部不变；
模型仍称为 `DURATION_CONDITIONED_FIXED_10D_LOGISTIC`。

只允许一次正式全历史/OOF 重建。通过只记 `HISTORICAL_RESEARCH_SUPPORT` 并进入下一 defect；
失败即 `CONTRACT_STOP`，不得尝试其他 cap、惩罚、feature、model、window 或 calibrator。

### 12.5 `PROB-FRAGILITY-002` 唯一失败候选的冻结证据

以下是已经执行并失败的唯一正式候选规格，用于 hash 重放和阶段 E shadow 来源约束；v1.3 后它不再
是正式事件、不得恢复进 runtime/Schema/Dashboard。候选当时的 eligibility 为：

```text
data_status == OK
AND formal_vintage_eligible == true
AND carry_answer == SUPPORTIVE
AND shock_answer == CALM
AND persistence_answer == NORMAL
AND all frozen predictors observable at t
```

如果 data/current answer/predictor/PIT 不可知则 `UNOBSERVABLE`；事实可知但谓词不成立则
`NOT_APPLICABLE`。只有完整的 `t+1 ... t+5` 五个 formal sessions 中，以下四条天气事实及各自
vintage flag 全部可知，标签才完成：

```text
positive if any:
    hard_acute == true
    front_slope30 < 0
    broad_pressure_day == true
    carry_environment_state == CLOSED on two consecutive future sessions
```

任一未来事实或对应 vintage 缺失时整条标签 `CENSORED`；即使第一日已为正，也只能在第五个
session 的 `decision_as_of` 后 outcome-available。

新增原始/百分位 facts：

```text
d1_log_vvix = log(vvix_close_t / vvix_close_{t-1})
spx_5d_log_momentum = log(spx_close_t / spx_close_{t-5})
p_d1_log_vvix = causal rolling midrank percentile(d1_log_vvix)
p_neg_spx_5d_log_momentum = causal rolling midrank percentile(-spx_5d_log_momentum)
```

两项 percentile 均复用 756 reference / 504 minimum / exclude-current / methodology-isolation，遇 gap、
非正价格或不同方法历史时为 null。正式 predictor 顺序一次冻结为：

```text
p_neg_front_slope30
p_d1_log_vvix
p_d5_log_vvix
p_neg_spx_5d_log_momentum
```

选择依据只来自阶段 A 预列名、两窗同向且 confirmation Brier 增量为正的价格盲诊断；未读取 ETF
结果。明确拒绝 Tail/VRP 硬门、VVIX/VIX residual、SKEW、threshold/model/window/feature subset 扫描。
这一个 rolling-origin 候选已因 114/252 失败。v1.3 保留该失败并关闭正式概率范围；阶段 E 只能在
阶段 D 通过后，把同一数值构造隔离复现为 `UNQUALIFIED_RESEARCH_SCORE`，不得改变 predictor、模型、
窗口、门槛或名称边界。

### 12.6 `PROB-BROAD-002` 基准率豁免

Broad 的事件状态、future 10-session 中至少五个 broad-pressure day 的标签、完整 horizon、PIT 和
censoring 保持 V2 不变。运行时 `LOGISTIC_FEATURES` 对它为空，正式 OOF 只建立因果 BaseRate 行：

```text
raw_probability = null
published_probability = base_rate_at_prediction
calibration_method = NOT_APPLICABLE
intercept_b = null
model_status = BASE_RATE_ONLY
probability_kind = HISTORICAL_REFERENCE
```

`BASE_RATE_REFERENCE=PASS` 只检查公式、可用性、标记、append invariance 和事件重放，不计算或展示
Broad model PASS rate。阶段 A 的 direct model 结果只保留在历史诊断中。

### 12.7 `STATE-CHURN-002` 因果 risk-on 确认

冻结的 14 个 Stage-A risk-on IDs 为：

```text
3, 4, 9, 10, 11, 13, 15, 16, 18, 23, 24, 28, 30, 34
```

它们只产生三个允许确认的 phase 方向：

```text
MIXED_TRANSITION -> TAIL_RICH_QUIET_CURVE
MIXED_TRANSITION -> CARRY_SUPPORTIVE_LOW_STRESS
TAIL_RICH_QUIET_CURVE -> CARRY_SUPPORTIVE_LOW_STRESS
```

由于严格 micro-churn 定义允许最多两个中间 sessions，因果发布要求同一 risk-on destination 连续
出现三个 `data_status=OK` formal sessions 后才发布；前两日继续发布 source phase。候选改变、
UNKNOWN/gap 或任一同级/更高风险 raw phase 会清空 pending；任何同级/更高风险 phase 立即发布。
现有 acute release 规则优先且保持不变。

该确认只允许修改 `phase` publication，不修改：

```text
raw_phase / carry_answer / shock_answer / tail_answer /
persistence_answer / repair_answer / feature / event_status / label /
probability eligibility / probability value
```

阶段 D 必须报告所有受影响行。若出现允许列表之外的 risk-on pair、任何 risk-off 延迟、任何 raw
event/answer/probability 差异或 UNKNOWN bridge，`STATE-CHURN-002=FAIL`。不得按历史日期硬编码 ID。

### 12.8 阶段 D 验收与停止门

四个 `FEATURE_CONDITIONAL_REQUIRED` 事件各自在最新 252 个完成、当时实际可发布 OOF 上必须满足：

```text
samples = 252
positive >= 20
negative >= 20
Brier Skill versus frozen causal BaseRate >= 2%
ECE <= 7%
```

并单列 raw/published、reliability quintiles、AUC、年度/开发确认分区与事件簇 block 稳定性。
此外：

- acute/front/mid 不得因统一校准退化；
- Carry duration 不跨 gap，且 reliability 不倒置；
- Fragility 必须保持从正式目录、Schema、Dashboard 与模型计数移除，并保留 114/252 拒绝证据；
- Broad 必须通过 `BASE_RATE_REFERENCE`，但不得出现在模型通过计数；
- V2 DATA/TENOR、raw state answer、raw event timing、PIT 与 UNKNOWN 传播不退化；
- Churn 只改变允许的 risk-on phase publication，risk-off timing 完全不劣于 V2；
- probability OOF 和 daily event 的公式、Schema、cache digest 与 append invariance 全部可重放。

任一必需条件模型、Broad reference、Fragility boundary、完整性或其他 P0/P1 defect 未通过时，结论固定为
`STATION_NOT_READY`，不得编写阶段 E adapter 或读取产品价格。

### 12.9 变更预算与阶段 A 代码归档

阶段 A 已使用合同的几乎全部净新增代码预算。`src/matvix/v3_audit.py`、`audit-v3` CLI 与
`tests/test_v3_audit.py` 是一次性审计施工脚手架，不是 V3 运行产品。阶段 C 第一项实现提交必须在
保留本文件、阶段 A artifact hash 与 Git 提交 `3f0e394` 可复现边界的同时删除或实质复用这些行，
使相对 `a2a8a58` 的净新增非生成 Python 与测试继续不超过 1,500 行。不得通过增加第二套框架绕过。

阶段 B 冻结提交时的状态（后续正式结果见第 11.1 节）：

```text
STAGE_B_SEMANTICS_FROZEN
PROB-CAL-002=PASS
PROB-CARRY-002=FORMAL_FAIL_ECE_RECORDED
PROB-CARRY-SATURATION-003=PASS_HISTORICAL_RESEARCH_SUPPORT
PROB-FRAGILITY-002=NEXT_AUTHORIZED
STATE-CHURN-002=BLOCKED_PENDING_FRAGILITY_RESULT
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
STAGE_D_NOT_RUN
ADAPTER_BLOCKED
ECONOMIC_PROBE_BLOCKED
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

---

## 13. 阶段 C 正式施工账本

### 13.1 `PROB-CAL-002` 与 Broad 基准率参考

在冻结实现上执行一次全历史价格盲重建，随后对 `2026-08-20` 最新完整 session 执行正式
`accept-real`。13 个气象站与概率完整性 gate 全部通过。最新 252 个完成且当时可发布 OOF 为：

| 事件 | publication policy | samples | Brier Skill | ECE | 结论 |
|---|---|---:|---:|---:|---|
| `acute_front_stress_5d` | conditional | 252 | 7.13% | 3.17% | PASS |
| `front_inversion_5d` | conditional | 252 | 10.71% | 3.00% | PASS |
| `mid_curve_pressure_accelerates_5d` | conditional | 252 | 11.79% | 5.08% | PASS |
| `carry_environment_recovers_10d` | conditional，尚未加入 duration facts | 252 | 9.67% | 6.81% | PASS |
| `broad_stress_persists_10d` | base-rate reference | 267 reference rows | — | — | PASS / EXEMPT |

本结果证明 rolling intercept、Schema 3.0、artifact contract 2、Broad 零训练路径和逐行重放满足
当前正式历史账本门；它复用了 V3 立项前已检查的历史，只能标记
`FORMAL_HISTORICAL_REPLAY_PASS`，不是独立前向确认。Carry 行只证明 `PROB-CAL-002` 下的旧六项
predictor 仍通过，不关闭下一项 `PROB-CARRY-002`。

本地忽略证据 hash：

```text
target_ledger.parquet  fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet     357ca2b737880e1d1f7220d81feb8925772317e057ab44d31a3ab8add182bcb7
artifact_contract.json 25fb9e58443eb4c2f3b0b2afa2cb2dedcf4fddcff7ed55a5db284475846f0a02
real_acceptance.json   f9750664900d6fb9cc26b5d9d5a622a1421cc50e546885a2eefd0a4bb1043640
```

代码验证：225 项 pytest 全通过，Ruff 全通过，Mypy 全通过，doctor 全通过；相对冻结 V2 基线的
非生成 Python 与测试净新增 344 行，未超过 1,500 行预算。

```text
PROB-CAL-002=PASS
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
PROB-CARRY-002=NEXT_AUTHORIZED
PROB-FRAGILITY-002=NOT_RUN
STATE-CHURN-002=NOT_RUN
STAGE_D_NOT_RUN
ADAPTER_BLOCKED
ECONOMIC_PROBE_BLOCKED
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 13.2 `PROB-CARRY-002` 正式失败与停止

只按冻结 predictor 顺序加入 `log1p_carry_spell_age` 与 `carry_recovering_flag`。逐 session duration
重放通过：1,930 个 eligible rows，最大 spell age 273；`NOT_APPLICABLE`、`UNOBSERVABLE` 与 formal
session gap 均不桥接。14 个 `accept-real` 气象站/概率完整性 gate 全部通过，但该命令只证明其各自
层级；required conditional model 的独立门如下：

```text
latest completed published OOF = 252
positive / negative = 66 / 186
raw Brier Skill = 35.1912%
raw ECE = 9.2983%
ROLLING_INTERCEPT_252 Brier Skill = 34.6690%
ROLLING_INTERCEPT_252 ECE = 7.4132%
frozen maximum ECE = 7.0000%
result = FAIL
```

最新 eligible prediction session `2026-08-13` 的严格当日 as-of gate 同样失败：Skill 35.11%、
ECE 8.31%，公开 daily event 因而按冻结语义回退 `BASE_RATE_ONLY`，fallback reason 为
`brier_or_ece_gate_not_met`。这不是 Carry 条件模型 PASS，也不能用强排序能力抵消校准门。

published reliability quintiles 的 mean probability / observed rate 为：

```text
Q1  5.82% / 13.73%
Q2 10.32% /  4.00%
Q3 17.79% / 14.00%
Q4 38.44% / 30.00%
Q5 59.98% / 68.63%
```

本地忽略证据 hash：

```text
target_ledger.parquet  fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet     2331dcf3bc97ca53ba911ad45701291f3d5edc37f8a8fb548e787d3b27481899
artifact_contract.json 3727164e805db21e00d298b3ecc287ae4dbd1a89d8bf5146d1e7ec1eef1ec679
real_acceptance.json   19bc378a73387473ab403943eed240b07ee045922d0d1451b7b62dea739ac383
```

代码验证：228 项 pytest、Ruff、Mypy、doctor 与 `git diff --check` 全通过；相对冻结 V2 基线的
非生成 Python 与测试净新增 521 行，仍在 1,500 行预算内。

失败与 Stage-A 冻结候选的 7.41% ECE 一致。继续施工只能诉诸合同禁止的结果后改 window、
event-specific calibrator 或额外 feature，因此本次不是开启第二轮调参，而是执行停止条件：

```text
PROB-CAL-002=PASS
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
PROB-CARRY-002=FAIL_ECE
STATION_NOT_READY
PROB-FRAGILITY-002=NOT_AUTHORIZED_TO_START_AFTER_STOP
STATE-CHURN-002=NOT_AUTHORIZED_TO_START_AFTER_STOP
STAGE_D=BLOCKED
ADAPTER=BLOCKED
ECONOMIC_PROBE=NOT_RUN
PRODUCT_PRICES_READ=FALSE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 13.3 `PROB-CARRY-SATURATION-003` 结果后只读残差审计

本节不重训、不模拟新候选，只对 13.2 已冻结的正式 published OOF 做分解。最新 252 行的
10 等频校准分箱中，各 quintile 对总 ECE 的绝对贡献为：

```text
Q1  1.5995 percentage points
Q2  1.3042 percentage points
Q3  0.8061 percentage points
Q4  1.7620 percentage points
Q5  1.9415 percentage points
total = 7.4132%
```

Q1 是明确残差但不是全部误差。即使反事实地把 Q1 修到零误差、其余分箱完全不变，总 ECE 也只会
机械降至约 5.81%；把 Q1 平均预测从 5.82% 提高至 10% 时，机械值约为 6.57%。这些只是算术
上界诊断，不是 bounded feature 的 OOF 结果，因此不得把外部提出的 5.5%–6.5% 区间写成预期
效果或通过保证。

最新 252 行的既有正式预测按原先冻结 age 分箱为：

| spell age | n | mean published p | observed rate |
|---|---:|---:|---:|
| 1–2 | 43 | 60.50% | 72.09% |
| 3–5 | 28 | 44.66% | 50.00% |
| 6–10 | 25 | 37.12% | 20.00% |
| 11–20 | 32 | 21.26% | 0.00% |
| 21–60 | 82 | 11.82% | 10.98% |
| 61+ | 42 | 6.05% | 16.67% |

age 61+ 的 42 行全部来自同一 spell；最低 quintile 也只有两个 spell。故这里没有足够证据授权
灵活 spline、分段惩罚或搜索 cap。唯一仍可治理的最小候选是复用阶段 A 预先存在的 20-session
边界做物理饱和，并用原门槛接受或拒绝。合同 v1.2 纯文档冻结时的开工裁决是：

```text
PROB-CARRY-002=FAIL_ECE
PROB-CARRY-SATURATION-003=SPEC_FROZEN_IMPLEMENTATION_AUTHORIZED_ONCE
FORMAL_REBUILD_BUDGET=ONE
THRESHOLDS_AND_MODEL=UNCHANGED
PRODUCT_PRICES_READ=FALSE
ECONOMIC_PROBE=NOT_RUN
```

### 13.4 `PROB-CARRY-SATURATION-003` 唯一正式重建结果

实现严格用 `bounded_log1p_carry_spell_age` 替换旧无界字段：原始 `carry_spell_age` 继续作为逐行
证据，模型、配置、fingerprint 与验收只消费 `log(1 + min(age, 20))`；验收明确要求旧 transformed
字段不存在。标签、10-session horizon、eligibility、Logistic、regularization、rolling intercept、
purge、252/20/20 与 Skill/ECE 门均未修改，也没有加入其他特征。

合同唯一一次正式链为：

```bash
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real --date 2026-08-20 --project-dir .
```

历史重建得到 3,334 行 state，其中 1,930 个 Carry eligible rows、最大 spell age 273；bounded/raw age
与 recovering flag 全部逐行重放一致，legacy transformed columns 为空。最新 252 个完成且当时实际
可发布 OOF 的原门结果为：

| 候选 | samples | 正/负 | Brier Skill | ECE | AUC | 裁决 |
|---|---:|---:|---:|---:|---:|---|
| 第一版 unbounded published | 252 | 66/186 | 34.6690% | 7.4132% | — | FAIL |
| bounded raw Logistic | 252 | 66/186 | 37.6273% | 7.0228% | 0.8385 | raw ECE 未过门 |
| bounded rolling-intercept published | 252 | 66/186 | 36.1709% | 5.0964% | 0.8068 | **PASS** |

相对第一版 published 候选，Brier Skill 增加 1.5019 percentage points，ECE 减少 2.3168
percentage points。原 7.00% 门没有放宽；通过来自 frozen bounded predictor 与既有 rolling
intercept 的组合，而不是 Skill 抵扣 ECE。

published reliability quintiles 为：

```text
Q1  8.286% /  7.843%
Q2 12.935% / 17.647%
Q3 18.588% /  6.000%
Q4 37.185% / 32.000%
Q5 65.346% / 68.000%
```

固定正 slope 与 AUC 0.8068 证明没有第一版 Platt 的全局排序反转，但 Q2/Q3 的局部非单调仍应
诚实保留，不能声称校准已完美。最近 eligible prediction session `2026-08-13` 的严格只读 as-of
重放同样通过：252 行、63/189 classes、Skill 36.6367%、ECE 5.2672%、AUC 0.8043。

两窗不是 untouched confirmation，但方向与门内结果如下：

| 历史窗 | samples | published Skill | published ECE | AUC |
|---|---:|---:|---:|---:|
| development（至 2021-12-31） | 849 | 26.2726% | 6.2300% | 0.7915 |
| confirmation（自 2022-01-03） | 780 | 16.1336% | 6.6530% | 0.7170 |

age>20 残差不再两窗同向：development 为 8.575%/7.941%（预测/实际，n=340，7 spells），
confirmation 仍为 16.538%/20.849%（n=259，8 spells）。因此不能把 cap=20 宣称为稳定物理真理。

集中度限制仍然实质存在：最新 252 行来自 26 个 spell，但最大单 spell 占 102/252（40.48%）；
age 61+ 占 42/252；66 个正例分布于 22 个 spell，最大正例 spell 占 9/66。leave-one-spell-out
删除块诊断中 Skill 始终为正且范围 25.78%–46.55%，但 ECE 范围 3.606%–12.453%；删去上述
102 行大 spell 时最差。合同没有冻结该删除块为额外通过门，故它不反向推翻正式 252 行 PASS；
但它严格限制结论为 `HISTORICAL_RESEARCH_SUPPORT`，并要求前向观察。

14 个 `accept-real` 完整性 gate、229 项 pytest、Ruff、Mypy、doctor 与 `git diff --check` 全通过；
相对冻结 V2 基线的非生成 Python 与测试净新增 571 行，仍在 1,500 行预算内。正式产物 hash：

```text
states.parquet             e82ecc2934357b0979991d9db877b14cd6787e40694726da56da10af861a6fbe
target_ledger.parquet      fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet         330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820
artifact_contract.json     533111ad28b43b41fa16c604bb4d6e098e5199805eccf7d09895ada0487c7a93
daily/2026-08-20.json      287ce0d5e16b94d2d5a3f5479c0c0a1ea00a42768f545a052478a44a23a2d215
real_acceptance.json       111169cb6ef84b9c5029c36df34475ebcedc593317bb137f32de880d8bfe9064
```

该 Carry 提交时的裁决（已由第 11.1 节后续 Fragility 结果取代）：

```text
PROB-CAL-002=PASS
PROB-BROAD-002=BASE_RATE_REFERENCE_PASS
PROB-CARRY-002=HISTORICAL_FIRST_ATTEMPT_FAIL_RETAINED
PROB-CARRY-SATURATION-003=PASS
EVIDENCE_CLASS=HISTORICAL_RESEARCH_SUPPORT
PROB-FRAGILITY-002=NEXT_AUTHORIZED
STATE-CHURN-002=NOT_RUN
STAGE_D=NOT_RUN
ADAPTER=BLOCKED
ECONOMIC_PROBE=NOT_RUN
PRODUCT_PRICES_READ=FALSE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 13.5 `STATE-CHURN-002` 受限 risk-on 正式重放

实现只在 `phase` publication 层加入第 12.7 节冻结的三组方向和三日确认；`raw_phase`、五个 answer、
结构状态、feature、event/label、probability eligibility/value 均未改。候选改变、UNKNOWN、非连续
formal session 会清空 pending；任一未列名方向立即发布；既有 acute 两日释放仍优先。

正式价格盲链：

```bash
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real --date 2026-08-20 --project-dir .
```

重建 3,334 行 state，`OK/PARTIAL=2,803/531`。相对冻结 V2 state，逐行核对
`data_status / structure / five answers / raw_phase / hard_acute / broad / repair / carry facts` 的差异为
0；只有 270 行 published `phase` 改变：

| held source → raw destination | 受影响行 |
|---|---:|
| `MIXED_TRANSITION → CARRY_SUPPORTIVE_LOW_STRESS` | 170 |
| `MIXED_TRANSITION → TAIL_RICH_QUIET_CURVE` | 92 |
| `TAIL_RICH_QUIET_CURVE → CARRY_SUPPORTIVE_LOW_STRESS` | 8 |

全历史 `phase != raw_phase` 共 449 行，其中原 acute release 179 行、新 risk-on 确认 270 行、非法或
risk-off 延迟 0 行。phase transition 从 V2 的 947 降为 706；减少 241 次只是冻结规则的结果，不是
验收目标，也不等同交易换仓或成本改善。

Churn 前后 target、OOF 与 probability artifact hash 一字不变，证明 phase-only 施工没有渗入正式
事件或概率：

```text
states.parquet             8a31d30124b616d073ff780363dbef6705a5aa6a7500e6c0569783e16ad2d7b4
target_ledger.parquet      fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet         330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820
artifact_contract.json     533111ad28b43b41fa16c604bb4d6e098e5199805eccf7d09895ada0487c7a93
real_acceptance.json       8a04f9a4728c3ef291379f8ca4d15d07eee09c6e68298a3816cdc4010f18fe54
```

14 个 `accept-real` 完整性 gate 全通过，且 `PRODUCT_PRICES_READ=FALSE`。阶段 D 的完整独立维度报告
仍未运行；本 defect 提交后的入口状态为：

```text
STATE-CHURN-002=PASS
RISK_OFF_DELAYED_ROWS=0
RAW_STATE_EVENT_PROBABILITY_DIFF=0
PROB-FRAGILITY-002=CLOSED_BY_SCOPE_FORMAL_REJECT_RETAINED
STAGE_D=NEXT_AUTHORIZED
ADAPTER=BLOCKED_PENDING_STAGE_D_AND_STAGE_E_DOC_FREEZE
ECONOMIC_PROBE=NOT_RUN
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

---

## 14. 阶段 D：四模型气象站完整验收

新增独立命令：

```bash
.venv/bin/python -m matvix accept-v3-station --project-dir .
```

它与旧 V2 的“概率模型不参与经济入口”不同；V3 入口要求以下七维全部独立 PASS：

| 维度 | 裁决 |
|---|---|
| DATA | PASS |
| TENOR | PASS |
| STATE_TIMING | PASS |
| PROBABILITY_INTEGRITY | PASS |
| PROBABILITY_MODEL | PASS |
| BASE_RATE_REFERENCE | PASS |
| FRAGILITY_BOUNDARY | PASS |

验收器首次启动时暴露两个 V2 兼容缺陷，均在不改天气业务语义、模型或门槛的条件下修复：

1. 旧 append helper 仍硬编码已由 V3 删除的 `decision_score/platt` 列，命令在形成裁决前崩溃；现按
   当前 prefix/full OOF 共同 Schema 比较全部非键因果字段，并要求列集合完全一致。
2. 首次可运行结果只因 `label / label_status / outcome_available_at` 在 cutoff 后按 5/10 日 horizon
   自然成熟而误报 DATA FAIL。合同的追加不变门约束既有 feature/state/prediction/training/base-rate/
   calibration/publication，不禁止未来 outcome 从 censored 变 observed；三列因此被显式列为 outcome
   maturation，不参与预测不变性比较。最终 6,400 个共同 OOF 的所有因果字段差异为 0，feature/state
   差异为 0，prefix/full OOF 列集合差异为 0。

四个正式条件模型的冻结 252-row 裁决：

| event | 正/负 | Brier Skill | ECE | 裁决 |
|---|---:|---:|---:|---|
| `acute_front_stress_5d` | 40/212 | 7.1313% | 3.1736% | PASS |
| `front_inversion_5d` | 26/226 | 10.7097% | 3.0033% | PASS |
| `mid_curve_pressure_accelerates_5d` | 117/135 | 11.7853% | 5.0768% | PASS |
| `carry_environment_recovers_10d` | 66/186 | 36.1709% | 5.0964% | PASS |

Broad 有 267 个 reference rows，逐行 `published_probability == causal_base_rate`、raw=null、
calibration=`NOT_APPLICABLE`，只裁决为 `BASE_RATE_ONLY_EXEMPT`，不计模型 PASS。Fragility boundary
逐项确认 EVENT_ORDER、Logistic config、target/OOF、state、Schema、daily snapshot 均无
`calm_carry_breaks_5d`；唯一候选仍为 114/252 `NOT_ELIGIBLE`，审计 hash 继续保留。

STATE_TIMING 重放差异为 0；phase/raw phase 差异只含 179 个原 acute release 与 270 个冻结 risk-on
确认，非法或 risk-off 延迟为 0。正式输出 hash：

```text
daily_ledger.parquet  24de7e129cf2349bc18bc3aef697986af4c77184ea017c7dc2ad9423b049a7ef
summary.json          54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93
report.md             10b1c08a6a547c85864a7319ccfe977aa2e42a0842479eb1c27ecd8b79a35fcd
```

阶段 D 裁决：

```text
STAGE_D=PASS
STAGE_E_ENTRY=PASS
FORMAL_CONDITIONAL_MODELS=4_OF_4_PASS
BROAD=BASE_RATE_REFERENCE_PASS_NO_MODEL_PASS_CLAIM
PROB-FRAGILITY-002=CLOSED_BY_SCOPE_FORMAL_REJECT_RETAINED
FRAGILITY_BOUNDARY=PASS_NOT_A_MODEL_PASS
PRODUCT_PRICES_READ=FALSE
ADAPTER_CODE=NOT_STARTED
ECONOMIC_PROBE=NOT_RUN
NEXT=STAGE_E_PURE_DOCUMENT_FREEZE
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

---

## 15. 阶段 E：`UNQUALIFIED_FRAGILITY_VETO_SHADOW` 价格盲冻结

阶段 D 已通过且其提交后工作树干净。本节只冻结 adapter/policy 研究对象；编写本节时仍未读取
`SVXY / SGOV / VXZ` 价格、`data/raw/economic_probe` 或 `outputs/v2_economic_probe` 的逐日或报告内容。
正式气象站继续只有 acute/front/mid/carry 四个条件模型与 Broad 基准率参考；本节不重开
`PROB-FRAGILITY-002`，也不改变其 114/252 `NOT_ELIGIBLE` 裁决。

### 15.1 唯一候选复现合同

唯一允许复现的是第 11.1、12.5 节已经执行并失败的 `calm_carry_breaks_5d` 候选。其构造逐字固定为：

```text
eligibility =
    data_status == OK
    AND formal_vintage_eligible == true
    AND carry_answer == SUPPORTIVE
    AND shock_answer == CALM
    AND persistence_answer == NORMAL
    AND all predictors observable at t

horizon = next 5 formal sessions
positive =
    any hard_acute == true
    OR any front_slope30 < 0
    OR any broad_pressure_day == true
    OR carry_environment_state == CLOSED on two consecutive future sessions
outcome_available_at = after all four facts for the fifth future formal session are known

predictor order =
    p_neg_front_slope30
    p_d1_log_vvix
    p_d5_log_vvix
    p_neg_spx_5d_log_momentum

percentile = prior 756 / minimum 504 / exclude current / methodology isolation
base rate = prior max 756 / minimum 252 / Beta(1, 1)
raw learner = scikit-learn 1.7.2 LogisticRegression
              C=1 / lbfgs / fit_intercept=true / tol=1e-8 / max_iter=1500 /
              random_state=0 / max training=1500 / min training=252 /
              min classes=30/30 / purge=20 formal sessions
rolling intercept = prior max 252 / min classes=20/20 / slope=1 /
                    root=[-40, 40] / clip=[1e-6, 0.999999]
```

唯一冻结候选的完整正式 OOF hash 继续为：

```text
44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770
```

阶段 E 的首次价格盲重放发现，第 11.1 节原转录值只有 62 个十六进制字符，不可能是 SHA-256；
缺失的是相邻的 `b8` 两位。勘误前先完成两条锁定运行时交叉验证：现行五事件 OOF 全量内存重建
精确命中 `330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820`；加入唯一候选后命中
上述 64 位 OOF hash。同时，加入候选并按 canonical event/date 排序的 target ledger 精确命中既有
`9e77c5be6e2f4a2b387d877b7f5184376f922301a2585077f0704382a920523e`。本次只纠正证据转录，未改变
任何 row、feature、label、score、模型、窗口、阈值、门槛或 adapter spec hash。

候选当时有 371 个完成 label（158/213）、115 个因果 score rows；其中 114 个 label 已完成
（44/70），首个 score session 为 2023-06-16。adapter 可在 signal t 使用当时已存在且有限的
`published_probability` 与 `base_rate_at_prediction`；不能要求 t 时尚未知的未来 label 已完成。
`published_probability` 在 adapter 中必须改名为 `shadow_score`，其 transform 只能按原行保留
`IDENTITY_WARMUP` 或 `ROLLING_INTERCEPT_252` provenance，不能据此声称正式校准通过。

本节的完整 canonical adapter spec 使用 sorted-key、UTF-8、compact JSON 序列化；实现必须内置同一
对象并逐字断言：

```text
adapter_spec_id = MATVIX_V3_UNQUALIFIED_FRAGILITY_VETO_SHADOW_1.0.0
canonical_sha256 = 891ff32abe61235f7297684ae7bc4576f470312950782773761aa25da4ca8aa8
```

### 15.2 账本与唯一映射

adapter ledger 至少逐日保留：

```text
session_date
base_short_allowed
shadow_score
causal_base_rate
shadow_score_available
shadow_score_kind = UNQUALIFIED_RESEARCH_SCORE
qualification_status = INSUFFICIENT_PUBLISHED_OOF
formal_event_id = null
formal_model_status = null
shadow_transform
unqualified_fragility_veto_shadow
short_allowed_v3
```

唯一允许的布尔语义为：

```text
BASE_SHORT_ALLOWED =
    data_status == OK
    AND carry == SUPPORTIVE
    AND shock == CALM
    AND persistence == NORMAL

SHADOW_SCORE_AVAILABLE =
    a causally published candidate row exists at t
    AND shadow_score is finite
    AND causal_base_rate is finite

UNQUALIFIED_FRAGILITY_VETO_SHADOW =
    BASE_SHORT_ALLOWED
    AND SHADOW_SCORE_AVAILABLE
    AND shadow_score > causal_base_rate

SHORT_ALLOWED_V3 =
    BASE_SHORT_ALLOWED
    AND SHADOW_SCORE_AVAILABLE
    AND NOT UNQUALIFIED_FRAGILITY_VETO_SHADOW
```

当 `BASE_SHORT_ALLOWED=true` 但 score/base rate 不可用时固定为 SGOV。Combined precedence 逐字
保持为：data 非 OK → SGOV；否则 DIFFUSING → VXZ；否则 `SHORT_ALLOWED_V3` → SVXY；否则 SGOV。
因此允许的唯一变化是 `SVXY → SGOV`；不得产生 `SGOV/VXZ → SVXY`，不得改变任何 Long signal、
position、cost 或 P&L。禁止 Tail/THIN/VVIX/VRP 第二硬门、acute 替代、确定性断路器、阈值扫描、
in-sample score 或缺失值填补。

### 15.3 共同区间、价格批次与唯一运行

价格批次价格盲冻结为 V2 已使用的唯一 manifest：

```text
data/raw/economic_probe/20260822T093334.462165Z/manifest.json
```

阶段 F 只能读取该批次；禁止联网、下载、provider fallback、批次替换或补价。主比较 session 是
冻结 V2 天气、V3 天气与三个 ticker 的共同交集，并限制为 `session_date >= 2023-06-16`；交集内首日
才是双方共同 signal 起点。更早日期对 V2/V3 一并排除，不能把 shadow warm-up 当成长 SGOV 区间。
共同起点后 score 缺失仍按第 15.2 节降到 SGOV。

运行前必须核对阶段 D `summary.json` hash：

```text
54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93
```

阶段 F 只允许运行一次 `run-v3-economic-probe`。命令必须在以下任一输出已存在时拒绝覆盖，且不得
删除输出后重跑：

```text
outputs/v3_economic_probe/daily_ledger.csv
outputs/v3_economic_probe/report.json
outputs/v3_economic_probe/report.html
```

### 15.4 价格盲冻结的裁决门

Short V3 必须在完全相同的共同 sessions、价格、成本和执行时点上，同时满足：税费后 final NAV 与
total return 严格高于 frozen V2，max drawdown 严格更优，worst rolling 20-session return 严格更优。
Long V3 的 signal、asset、return、cost、NAV 必须与 V2 逐日完全一致。Combined V3 的 final NAV、
max drawdown 与 worst-20D 必须全部不劣于 V2。逐日账本还必须保留 target asset、adjusted open、
turnover、cost、gross/net return、P&L、NAV、drawdown，并列出最差 20 个 SVXY 日双方实际暴露。

任一 eligible probe 不满足即：

```text
ECONOMIC_VERDICT = NO_COMPREHENSIVE_INCREMENT
ADAPTER-002 = REJECTED_BY_FROZEN_HISTORICAL_PROBE
```

届时停止，不改 mapping、不换阈值、不运行第二次。全部满足也只能标记
`HISTORICAL_RESEARCH_SUPPORT`；不能提升 Fragility 资格、增加第五个模型、合并 main、推送或表述为
production promotion。prospective ledger 只能从 adapter 实现提交后的首个完整共同 session 起追加，
不得回填冻结提交以前的日期。

阶段 E 冻结裁决：

```text
STAGE_E=PASS_PURE_DOCUMENT_FREEZE
ADAPTER_SPEC_ID=MATVIX_V3_UNQUALIFIED_FRAGILITY_VETO_SHADOW_1.0.0
ADAPTER_SPEC_SHA256=891ff32abe61235f7297684ae7bc4576f470312950782773761aa25da4ca8aa8
PROB-FRAGILITY-002=FORMAL_REJECT_RETAINED_114_OF_252
FORMAL_STATION_SURFACE=UNCHANGED_FOUR_MODELS_PLUS_ONE_BASE_RATE_REFERENCE
PRODUCT_PRICES_READ=FALSE
ADAPTER_CODE=NEXT_AUTHORIZED
ECONOMIC_PROBE=NOT_RUN
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 15.5 `ADAPTER-002` 价格盲实现与复现证据

阶段 E 文档提交 `424667c` 与 hash 勘误提交 `c70f9f2` 完成且工作树干净后，才新增隔离模块
`src/matvix/fragility_shadow.py`、固定 V2/V3 comparison path 与聚焦测试。实现没有把候选加入
`EVENT_ORDER`、`LOGISTIC_FEATURES`、target/OOF cache、state、daily Schema、snapshot 或 Dashboard；
正式验收常量只把 62 位转录错误同步为已经价格盲证明的 64 位拒绝证据 hash。

锁定运行时的完整价格盲 replay 逐项命中：

```text
eligible_targets=372
completed_targets=371
target_positive/negative=158/213
published_oof=115
completed_published_oof=114
completed_oof_positive/negative=44/70
first_score_session=2023-06-16
formal_oof_sha256=330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820
candidate_target_sha256=9e77c5be6e2f4a2b387d877b7f5184376f922301a2585077f0704382a920523e
candidate_oof_sha256=44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770
```

115 个 score rows 在唯一映射下分为 43 个 `UNQUALIFIED_FRAGILITY_VETO_SHADOW=true` 与 72 个
`SHORT_ALLOWED_V3=true`；全历史 372 个 `BASE_SHORT_ALLOWED` 中，首个 score 以前的 257 行不被
填补或冒充为 score。阶段 F 会把双方共同区间裁到 2023-06-16 以后；共同起点后任一缺分数行仍固定
SGOV。实现逐行断言 V3 Short 不能在 frozen V2 `BASE_SHORT_ALLOWED=false` 时为真；Long 决策完全
绕过 shadow，并在经济裁决中使用核心逐日字段 exact-equality gate。

提交前完整价格盲回归结果：全量 pytest、Ruff、Mypy、doctor 通过；history 仍为 3,334 行、
`OK/PARTIAL=2,803/531`；正式全 OOF 重建与阶段 D 七维再验收全部 PASS。正式产物未漂移：

```text
states.parquet                         8a31d30124b616d073ff780363dbef6705a5aa6a7500e6c0569783e16ad2d7b4
target_ledger.parquet                  fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet                     330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820
artifact_contract.json                 533111ad28b43b41fa16c604bb4d6e098e5199805eccf7d09895ada0487c7a93
v3_station_acceptance/daily            24de7e129cf2349bc18bc3aef697986af4c77184ea017c7dc2ad9423b049a7ef
v3_station_acceptance/summary          54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93
v3_station_acceptance/report           10b1c08a6a547c85864a7319ccfe977aa2e42a0842479eb1c27ecd8b79a35fcd
```

相对 V2 基线的非生成 Python 与测试净新增为 1,499 行，不超过 1,500 行预算；没有新增依赖、模型
registry、renderer、数据源或参数搜索器。正式 V3 economic outputs 三个路径均不存在，且截至本提交
仍未读取冻结价格 manifest、原始价格 JSON 或 V2 逐日/报告内容。

```text
ADAPTER-002=PASS_PRICE_BLIND_IMPLEMENTATION
ADAPTER_SPEC_SHA256=891ff32abe61235f7297684ae7bc4576f470312950782773761aa25da4ca8aa8
FORMAL_STATION_SURFACE=UNCHANGED
PROB-FRAGILITY-002=FORMAL_REJECT_RETAINED_114_OF_252
STAGE_D=SEVEN_DIMENSION_PASS_REPLAYED
PRODUCT_PRICES_READ=FALSE
STAGE_F=NEXT_AUTHORIZED_EXACTLY_ONE_RUN
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

---

## 16. 阶段 F：唯一冻结历史经济诊断

### 16.1 原始运行证据与机械裁决

价格盲实现提交为 `84fa1d3df2f527a4d41944cbabe0f055401d12bf`。该提交之后仅成功执行一次：

```text
.venv/bin/python -m matvix run-v3-economic-probe --project-dir .
```

命令复用了第 15.3 节冻结批次 `20260822T093334.462165Z`，`reused_existing_batch=true`；没有联网、
provider fallback、替换批次、补价或参数重估。共同区间有 797 个 signal sessions、795 个完成的
open-to-open sessions；首个共同 signal 为 `2023-06-16`，首次执行为 `2023-06-20`，最后 outcome
through 为 `2026-08-20`。

| Probe | V2 final NAV | V3 final NAV | V2 / V3 return | V2 / V3 MaxDD | V2 / V3 Worst-20D | 机械分类 |
|---|---:|---:|---:|---:|---:|---|
| Short | 10,393.2499 | 10,616.0196 | 3.9325% / 6.1602% | -16.1332% / -13.9655% | -13.965535794659623% / -13.965535794659600% | `POSITIVE` |
| Long | 11,739.2076 | 11,739.2076 | 17.3921% / 17.3921% | -10.9271% / -10.9271% | -8.6118% / -8.6118% | `POSITIVE` |
| Combined | 10,582.4163 | 10,809.2406 | 5.8242% / 8.0924% | -20.9681% / -21.7004% | -16.727818202191790% / -16.727818202191802% | `MIXED` |

Short 的 final NAV、return、MaxDD 与浮点意义下 Worst-20D 四个布尔门为真；Long 逐日 exact；
Combined final NAV 不劣，但 MaxDD 与浮点意义下 Worst-20D 两门为假。合同第 8.3/15.4 节规定任一
eligible probe 为 `MIXED/NEGATIVE` 即综合失败，因此生成器如实写出：

```text
SHORT=POSITIVE
LONG=POSITIVE
COMBINED=MIXED
ECONOMIC_VERDICT=NO_COMPREHENSIVE_INCREMENT
HISTORICAL_EVIDENCE_CLASS=NO_COMPREHENSIVE_INCREMENT
ADAPTER-002=REJECTED_BY_FROZEN_HISTORICAL_PROBE
PRODUCTION_PROMOTION=FALSE
```

本地忽略但保留的冻结输出及 SHA-256 为：

```text
outputs/v3_economic_probe/daily_ledger.csv  2262667420ba371d25d552959b918d4ca53abae4c7293bd14b1192f568b5321e
outputs/v3_economic_probe/report.json       5c6ff064bb1d5a63153967656aac33d1c7f707db006eb1c31e70833370c5a8b5
outputs/v3_economic_probe/report.html       300dbf179bd90029421d6d20278d52f1e73d96a202c0d7ad7568186a367f714a
```

三个输出受存在性保护；不得删除、覆盖或运行第二次经济命令。以上结果不改变
`PROB-FRAGILITY-002=FORMAL_REJECT_RETAINED_114_OF_252`，也不改变四模型加一个 Broad 基准率引用的
正式气象站表面。

### 16.2 经济归因与最终裁决

唯一适配器造成 43 个逐日资产差异，全部为合同允许的 `SVXY -> SGOV`，没有任何反向增仓或 Long
变化。但这 43 次 veto 在最差 20 个 SVXY open-to-open sessions 中命中数为 **0**。Short 的
Worst-20D 两值落在同一 `2024-09-18` outcome-through 窗口；窗口内资产、turnover 与 gross return
完全相同，veto 日为 0，所谓“严格改善”仅约 `+2.2e-16` 的浮点尾差。Combined 的 Worst-20D 也落在
同一 `2024-09-04` 窗口，经济上相同，约 `-1.1e-16` 的浮点尾差令机械门为假。既不事后加 tolerance，
也不把任一尾差解释为真实风险变化。

Short final NAV 提高 `$222.77` 的同时，累计成本减少约 `$268.08`，但 gross final NAV 反而减少
约 `$54.60`；Combined final NAV 提高 `$226.82`，累计成本减少约 `$255.85`，gross final NAV 反而
减少约 `$58.50`。主要增量来自减少切换与成本，而不是候选在最差 SVXY 日前识别了脆弱性。

Combined 的实质失败是 MaxDD：

- V2 从 `2024-01-11` 的峰值 `$11,131.53` 跌至 `2024-09-23` 的 `$8,797.46`，MaxDD `-20.9681%`；
- V3 从较晚的 `2024-05-02` 峰值 `$11,438.34` 跌至同一 `2024-09-23` 的 `$8,956.17`，MaxDD
  `-21.7004%`。

V3 的绝对谷值虽然更高，但其此前峰值也更高，按冻结的相对 drawdown 定义仍明确更差。Short
自身的 MaxDD 从 `-16.1332%` 改善为 `-13.9655%`，不能覆盖 Combined 的合同失败。故不接受
“Short 单项通过”替代三探针联合门，最终裁决冻结为：

```text
STAGE_F=COMPLETE_EXACTLY_ONE_RUN
ECONOMIC_VERDICT=NO_COMPREHENSIVE_INCREMENT
ADAPTER-002=REJECTED_BY_FROZEN_HISTORICAL_PROBE
PROB-FRAGILITY-002=FORMAL_REJECT_RETAINED_114_OF_252
FORMAL_STATION=FOUR_FEATURE_CONDITIONAL_PLUS_BROAD_BASE_RATE_REFERENCE
SECOND_ECONOMIC_RUN=FORBIDDEN
MAPPING_OR_THRESHOLD_CHANGE=FORBIDDEN_UNDER_V1_3
NO_MERGE
NO_PUSH
NO_PRODUCTION_PROMOTION
```

### 16.3 前向观察边界

价格盲 adapter 冻结提交发生于 `2026-08-23`，冻结价格 outcome 只到 `2026-08-20`，因此当前没有
任何合法的 post-freeze 完整共同 session。现建立 header-only、append-only 前向账本
`data/prospective/v3_fragility_shadow_ledger.csv` 与约束说明 `data/prospective/README.md`；数据行数为 0，
不回填任何历史行。

该账本只允许被动记录拒绝候选的 counterfactual research observation，不授予 Short 暴露、交易、
模型资格、历史裁决翻案或 promotion 权限。未来第一行必须来自冻结提交之后当时可得的 signal、score、
position、price、cost 与完成 outcome；既有行不得修改或删除。若人类将来要重新裁决 adapter，必须先
另立 power/evidence 合同并预先冻结观察长度、独立 stress/fragility 簇数与裁决门，不能使用本次历史
结果事后选择规则。

```text
PROSPECTIVE_LEDGER=ESTABLISHED_EMPTY_APPEND_ONLY
PROSPECTIVE_ROWS=0
FIRST_ELIGIBLE_POST_FREEZE_SESSION=NOT_YET_OBSERVED
OBSERVATION_MODE=COUNTERFACTUAL_RESEARCH_ONLY
TRADING_AUTHORITY=NONE
CURRENT_CONTRACT_VERDICT=IMMUTABLE_NO_COMPREHENSIVE_INCREMENT
```

### 16.4 最终回归与交付状态

第 16.2/16.3 节冻结后，按合同第 11 节运行全量 pytest、Ruff、正式 Mypy 范围、doctor、history
重建、概率 full rebuild 与 V3 Stage D 再验收。pytest 退出 0（缓存记录 287 个 collected node ids）；
Ruff 全绿；Mypy 对 45 个 `src/matvix` source files 为 `Success`；doctor 的锁定依赖与四个本地数据
artifact 全部 PASS/FOUND。history 为 3,334 行，`OK/PARTIAL=2,803/531`。

Stage D 最终重放结果为：

```text
DATA=PASS
TENOR=PASS
STATE_TIMING=PASS
PROBABILITY_INTEGRITY=PASS
PROBABILITY_MODEL=PASS
BASE_RATE_REFERENCE=PASS
FRAGILITY_BOUNDARY=PASS
STAGE_E_ENTRY=PASS
```

正式 artifacts、Stage D 输出与唯一经济输出 SHA-256 均未漂移：

```text
states.parquet                          8a31d30124b616d073ff780363dbef6705a5aa6a7500e6c0569783e16ad2d7b4
target_ledger.parquet                   fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913
oof_ledger.parquet                      330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820
artifact_contract.json                  533111ad28b43b41fa16c604bb4d6e098e5199805eccf7d09895ada0487c7a93
v3_station_acceptance/daily             24de7e129cf2349bc18bc3aef697986af4c77184ea017c7dc2ad9423b049a7ef
v3_station_acceptance/summary           54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93
v3_station_acceptance/report            10b1c08a6a547c85864a7319ccfe977aa2e42a0842479eb1c27ecd8b79a35fcd
v3_economic_probe/daily_ledger.csv       2262667420ba371d25d552959b918d4ca53abae4c7293bd14b1192f568b5321e
v3_economic_probe/report.json            5c6ff064bb1d5a63153967656aac33d1c7f707db006eb1c31e70833370c5a8b5
v3_economic_probe/report.html            300dbf179bd90029421d6d20278d52f1e73d96a202c0d7ad7568186a367f714a
```

最终分支为 `codex/matvix-v3`；`main` 与 `origin/main` 仍共同停在
`6ac5b93b8d6f9fbd66807f9aaa0779e9214934e5`。没有合并、推送、第二次经济诊断或 production promotion。
