# MatVIX V3 概率、脆弱性与状态稳定性施工合同

> 状态：AMENDED / AUTHORIZED FOR STAGE B
> 合同版本：1.1
> 冻结日期：2026-08-22
> 修订日期：2026-08-22
> V2 代码基线：`a2a8a584f6435d7ffc972eb57b0928eeb0e4a802`
> 正式 main 基线：`6ac5b93b8d6f9fbd66807f9aaa0779e9214934e5`
> 目标分支：`codex/matvix-v3`
> 执行方式：下一独立 Codex session 直接审计、冻结规格、按 defect_id 施工和本地复核
> 核心顺序：概率校准治理 → Carry duration → 凸性脆弱性事件 → risk-on 状态微震荡 → 完整站内验收 → 固定适配器 → 一次经济诊断与前向观察

---

## 0. 本合同解决什么

V2 已关闭 `DATA-001 / TENOR-001 / STATE-001 / TIMING-001 / PROBABILITY-001`，并通过
DATA、TENOR、STATE/TIMING 与 PROBABILITY INTEGRITY 验收，但没有获得晋升：

- `carry_environment_recovers_10d` 最新 252 个完成 calibrated OOF 的
  Brier Skill 为 `-6.67%`、ECE 为 `21.73%`；
- `broad_stress_persists_10d` 只有 191 个完成 calibrated OOF，记为
  `INSUFFICIENT_EVIDENCE`；
- Short 固定探针总收益由 V1 的 `-18.59%` 改善至 V2 的 `+0.83%`，但最大回撤由
  `-23.80%` 恶化至 `-24.54%`，最差滚动 20 日由 `-13.15%` 恶化至 `-13.97%`；
- V2 因此保持 `NOT_READY / NO_PROMOTION / NO_COMPREHENSIVE_INCREMENT`。

阶段 A 随后补足并重放了 Broad 的 252 个 raw OOF，但 V2 raw Logistic 的直接 10 日 Brier
Skill 仍只有 `+0.82%`，固定 duration/breadth 候选也没有获得直接增量。2026-08-22 的人类明确
决定因此修订产品边界：

- `broad_stress_persists_10d` 的天气事件、eligibility、标签和事实语义继续保留；
- 它的 V3 概率输出固定为因果 `BASE_RATE_ONLY` 历史参考，不再施工或发布
  `FEATURE_CONDITIONAL` direct-10D 模型；
- 它从 Brier Skill/ECE 的正式模型通过门中豁免，但不从 PIT、outcome availability、base-rate
  算术、censoring、append invariance 和诚实状态标记中豁免；
- `BASE_RATE_REFERENCE=PASS` 只表示基准率发布合同完整，绝不表示 Broad 模型通过或具备预测增量；
- 该范围决定关闭原 Broad P0 阻断，并授权从阶段 B 继续；它不反向改写阶段 A 的失败证据。

V3 只回答六个问题：

1. 当前顺序 Platt 为什么把本来有排序增量的 Carry 原始概率校准坏？
2. Carry 恢复是否首先是带有 spell-age 依赖的离散时间 hazard，而不是缺少更多市场指标？
3. Broad direct-10D 被诚实降级后，如何发布可重放且不冒充条件模型的因果基准率参考？
4. 能否在不读取产品价格的条件下定义并验证“平静 Carry 下未来 5 日天气恶化”的凸性脆弱性事件？
5. 947 次 phase 转换中，哪些是真实天气变化，哪些才是无业务意义的 micro-churn？
6. 站内全部通过后，一个事先冻结、非调参的 V3 Short 适配器能否相对 V2 同时改善收益、最大回撤与 Worst-20D？

本合同是下一轮 V3 增量工作的唯一执行权威。未被 V3 明确修改的 V2 定义继续服从：

1. 人类在本合同之后给出的明确决定；
2. 本合同；
3. 阶段 B 正式冻结的 V3 规格修订；
4. `MATVIX_PRE_DEVELOPMENT_REPORT.md` 第 21 节的 V2 语义；
5. `MATVIX_V2_CONSTRUCTION_PLAN.md` 未被替代的证据与执行合同；
6. 当前 V2 代码、配置和 Schema。

### 0.1 已确认根因、候选假说与明确非根因

已确认、必须进入阶段 A 重放的根因：

- 当前 Platt 允许自由斜率，并把不同 rolling fit 产生的 decision score 混合校准；Carry 最新
  252 行中 173 行 `platt_a<0`，汇总可靠性排序发生反转；
- Carry 最新 252 行原始 Logistic 的 Brier Skill 为 `+13.09%`，但 ECE 为 `11.50%`；故原始
  模型有排序增量，当前二级校准和基准率漂移是首要问题，但原始概率仍未通过 ECE 门；
- Carry eligible spell 的恢复率具有明显且跨分区稳定的 duration dependence；当前正式 predictors
  没有 spell age；
- Broad 有 524 个完成 target、261 个完成 raw OOF、191 个完成 calibrated OOF；191 行约来自
  65 个连续事件簇。它不是简单的“正例极端稀少”；
- Broad 直接使用最新 252 个 raw OOF 时 Brier Skill 约为 `+0.82%`、ECE 约为 `5.69%`，即使
  消除 191 样本门，模型增量本身仍未通过 2% 门；
- 阶段 A 固定 duration/breadth Broad 候选 raw Skill 为 `-0.48%`，rolling-intercept Skill 为
  `-3.16%`；V3 据此采用 `BASE_RATE_ONLY` 产品范围决定，而不是继续搜索模型；
- 经济区间内 V2 combined 有 507 次 phase 变化、241 次实际资产切换；278 次 phase 变化没有
  触发交易。V2 turnover 低于 V1，故 947 次 phase 转换不是 `$2,204.41` 成本的直接原因；
- 2024-09-03 的共同 SVXY 暴露之前，V2 已发布 `tail=EXTREME`、
  `carry_compensation=THIN` 和 `TAIL_RICH_QUIET_CURVE`，但 V2 固定 Short 适配器没有读取这些
  字段。该事实证明接口消费缺口，不自动证明应把 tail/VRP 混入 carry answer。

只允许作为候选假说、不得预设有效：

- SPX 5 日动量；
- VIX9D/VIX 收敛速度；
- `d1_log_vvix`；
- VVIX/VIX 耦合残差；
- 现有 `vrp_ewma94` 与 `carry_compensation`；
- Tail/SKEW level 与 5 日变化；
- 5D/10D 多时间尺度模型和 Bayesian/hierarchical shrinkage。

明确非根因或不可直接施工的说法：

- “947 次 phase 转换直接产生 2,204 美元成本”；
- “Broad 的 191 行仅因为 10 日事件罕见”；
- “VRP<0 或 VVIX 单日上涨能覆盖现有全部左尾缺口”；
- “confidence 0–100 可以未经校准直接驱动仓位”；
- “SKEW term structure、Parkinson/Garman-Klass RV、variance-swap basis 已存在于当前正式数据”。

### 0.2 版本与分支边界

V3 是未晋升 V2 的研究后继，不是 mainline 升级。分支关系固定为：

```text
main @ 6ac5b93                     # 正式 V1，保持不变
  \
   codex/matvix-v2 @ a2a8a58      # 冻结 V2 代码与 NO_PROMOTION 裁决
      \
       [本合同纯文档提交]
          \
           codex/matvix-v3        # 下一 session 创建
```

不得为了启动 V3 而先把 V2 合并到 main。V3 开工前的合同提交只能新增本文件；其代码父基线必须
仍为 `a2a8a584...`。

V3 正式实现采用就地升级：

- `MODEL_ID=MATVIX_CBOE_CORE_V3`；
- 概率语义改变后 `probability_version=3.0.0`；
- 新增正式 feature 或 state 后，对应 version 升为 `3.0.0`；
- 输出合同改变后 Schema 升为 `3.0.0`；
- V3 研究构建完成时 Python package 版本升为 `3.0.0`；
- V2 只通过 Git 基线和只读基线产物保存；
- 不在运行代码中保留 `_v2/_v3` 双实现、版本开关或平行概率引擎。

### 0.3 明确不做

- 不恢复或读取 `/Users/logan/MatVIX_cleanup_quarantine/`；
- 不合并、不推送 V2 或 V3，不表述为 production/ready；
- 阶段 A–D 不读取 `SVXY/SGOV/VXZ` 原始价格、逐日收益或 V2 经济账本；
- 不围绕已知 ETF 亏损日搜索 VVIX、SKEW、VRP、概率或状态阈值；
- 不把 Tail、VRP 或 fragility 直接并入 `carry_answer`；
- 不改变 V2 的 DATA-001 VXCM30、F1–F7、TENOR、PIT 或 UNKNOWN 语义，除非阶段 A 发现新 P0；
- 不新增仓位梯度、止损、杠杆、期望效用、资产、成本或执行时点；
- 不建设通用 ML 平台、模型搜索器、feature store、状态治理框架、renderer 或发布框架；
- 不购买、抓取或导入新的 SPX option chain、SKEW term structure 或 SPX OHLC 数据；
- 不用 Bayesian prior、合成标签、重采样伪样本或降低样本门制造通过；
- 不把历史经济诊断表述为未污染的确认集或真实前瞻绩效。

---

## 1. 新 session 开工协议

新 session 必须先逐字阅读本文件，再执行：

```bash
cd /Users/logan/MatVIX
git status --short --branch
git fetch --prune origin
git branch -avv --no-abbrev
git worktree list --porcelain
git rev-parse HEAD
git rev-parse refs/heads/codex/matvix-v2
git rev-parse refs/heads/main
git rev-parse refs/remotes/origin/main
git diff --name-only a2a8a584f6435d7ffc972eb57b0928eeb0e4a802..HEAD
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src/matvix
.venv/bin/python -m matvix doctor --project-dir .
```

开工条件：

- 工作树干净；
- `main == origin/main == 6ac5b93b8d6f9fbd66807f9aaa0779e9214934e5`；
- `codex/matvix-v2` 包含 `a2a8a58`，且 `a2a8a58..HEAD` 只新增本合同；
- V2 代码与配置相对 `a2a8a58` 零变化；
- 全量测试、Ruff、Mypy、doctor 通过；
- 本合同、第 2.2 节三个冻结 hash 与本地文件一致；
- 没有其他 worktree 正在修改本仓库同一文件。

满足后创建：

```bash
git switch -c codex/matvix-v3
```

若 `codex/matvix-v3` 已存在，先只读检查其 SHA、worktree 和状态；不得删除、重置或覆盖。若基线、
hash、测试或并发编辑不满足，停止施工并报告，不得边清理边实现。

开工后第一项动作是冻结 V2 基线产物；不得先改任何业务语义。

---

## 2. 证据隔离、污染台账与基线产物

### 2.1 四层证据严格分开

```text
原始/PIT 天气输入
→ feature/state/event/probability
→ 固定产品适配器
→ price/cost/P&L/NAV
```

阶段 A–D 只允许前两层。阶段 E 只冻结第三层文档和代码合同，仍不得读取价格。阶段 F 在所有站内
门通过、适配器提交冻结后，才允许一次读取第四层。

V2 已产生的经济摘要属于已知污染事实，可从本合同和 `MATVIX_V2_AUDIT.md` 读取；禁止在阶段
A–E 打开或查询：

```text
outputs/v2_economic_probe/daily_ledger.csv
outputs/v2_economic_probe/report.json
outputs/v2_economic_probe/report.html
data/raw/economic_probe/
```

不得从这些文件做新的日期筛选、cohort 收益、阈值扫描或特征选择。

### 2.2 冻结文件 hash

以下 hash 只用于确认 V2 证据未漂移，不授权阶段 A–E 读取文件内容：

```text
84be43b1f6a6320aa5a4ad508f727f6a5f16653c15207245bd7da6d761e37f6b  outputs/v2_economic_probe/daily_ledger.csv
106ebdbe0c645eb41412308e6c351bd99ca6b0f58feba8e70caaeafb333a0428  outputs/v2_economic_probe/report.json
6da18f2ebf10ed95aaee9eb25b827c2ac814f06a594bc662f1cd904b14a45361  outputs/v2_station_acceptance/summary.json
```

### 2.3 V2 只读基线产物

修改代码前，以 `a2a8a58` 的正式顺序重建并保存：

```text
outputs/v3_baseline/v2_features.parquet
outputs/v3_baseline/v2_states.parquet
outputs/v3_baseline/v2_targets.parquet
outputs/v3_baseline/v2_oof.parquet
outputs/v3_baseline/v2_station_summary.json
outputs/v3_baseline/v2_manifest.json
```

`v2_manifest.json` 至少记录：

- V2 code SHA、配置 digest、Schema digest；
- 原始输入 manifest/hash；
- 每张表的行数、列、日期边界和 SHA-256；
- 五事件计数、raw/calibrated OOF 首次可用日；
- 正式命令、Python/依赖版本和 UTC 时间；
- `ASSUMED_PIT` 历史边界；
- 第 2.2 节经济文件 hash，但不复制其内容。

这些均为本地忽略产物，不新增 V2 运行代码。

### 2.4 时间与确认边界

- 站内全历史：沿用 V2 的 `2013-05-20` 至最新完整 session；
- 开发窗：截至 `2021-12-31`；
- 确认窗：`2022-01-03` 至最新完整 session；
- 概率：逐 session rolling-origin、event-specific eligibility、20-session purge、严格 outcome availability；
- 接受指标：最新 252 个已完成且当时实际可发布的 OOF；
- 事件稳定性：按连续事件簇 block/leave-one-cluster-out，不把重叠日当作独立事件；
- 已检查的历史 ETF 区间截至 `2026-08-20`，永久标记 `ECONOMIC_HISTORY_CONTAMINATED`；
- 真正前向经济账本只能从 V3 适配器提交之后的首个完整共同 session 开始，不得回填。

由于 V3 立项前已经检查过最新 252 行、2022–2026 分区表现和若干候选修复，以上“确认窗”只保留为
历史后段稳定性分区，不再是 untouched holdout。不得把 V3 在该窗口的通过表述为独立样本确认；
独立证据只能来自合同冻结后的 append-only prospective ledger。

探索性诊断得到的 `ROLLING_INTERCEPT_252`、spell-age 效果等只用于确定施工优先级，不得计入
V3 正式通过证据。正式 V3 必须从本合同冻结后的实现产生完整账本并如实标记历史复用边界。

---

## 3. 阶段 A：V3 站内业务审计

阶段 A 不修改 feature/state/event/probability 含义，不读取产品价格，不生成策略收益或 HTML。
优先复用 V2 基线 artifacts、现有 probability/acceptance 代码和只读临时分析。

唯一允许的输出：

```text
outputs/v3_audit/business_audit_daily.parquet
outputs/v3_audit/business_audit_summary.json
MATVIX_V3_AUDIT.md
```

只允许一个最小 V3 审计入口；不得建设通用实验框架或自动模型搜索器。

### 3.1 PROBABILITY CALIBRATION 审计

对五个 V2 正式事件逐行重放：

- raw probability、decision score、base rate、calibrated probability；
- 每一行训练边界、purge、outcome availability 与 calibration cohort；
- `platt_a/platt_b`、样本数、正负类、收敛；
- raw、当前 Platt 和 frozen base rate 的 Brier/Brier Skill/ECE/reliability/AUC；
- 最新 252、开发/确认、逐年、危机/平静分层；
- 不同 rolling model 产生的 decision score 尺度、截距与排序是否可比较；
- 负斜率行数、日期段及其对 rank/reliability 的影响；
- 当前 504-session calibration history 对基准率漂移的滞后。

阶段 A 只能比较三种已冻结诊断：

```text
CURRENT_FREE_PLATT_504
RAW_LOGISTIC_IDENTITY
ROLLING_INTERCEPT_252
```

不得扫描其他窗口、正则、bin 数、calibrator 或事件专属算法。`ROLLING_INTERCEPT_252` 的历史
结果已经被观察，属于污染诊断；阶段 A 只重放算术，不把它宣布为正式 V3 通过。

### 3.2 CARRY RECOVERY HAZARD 审计

保持 `carry_environment_recovers_10d` 的 onset、eligibility、horizon 和 future predicate 不变，先审计：

- 连续 eligible spell 数、spell 长度、最大长度；
- `spell_age=1–2 / 3–5 / 6–10 / 11–20 / 21–60 / 61+` 的恢复率；
- 开发/确认分区和 leave-one-spell-out 方向；
- `CLOSED` 与 `RECOVERING` 的独立恢复率；
- 当前 predictors 在各 spell-age 区间的可靠性与残差；
- 现有 `repair_scaled`、VIX9D/VIX convergence、VVIX collapse、VRP、SPX 5 日动量的单变量方向；
- 这些方向是否在开发/确认中反转；
- 长 spell 是否支配 252 日指标和校准基准率。

必须先检验最小 duration features：

```text
carry_spell_age
log1p_carry_spell_age
carry_recovering_flag
```

本阶段的 `hazard` 是待检验的业务假说；首版正式模型仍预测原有固定 10 日标签，只增加 duration
conditioning，不得把普通 Logistic 输出包装成完整 survival/hazard 模型。

只有 duration 仍不能解释剩余误差时，才允许在阶段 B 为某个外部市场候选特征立单独 defect。

### 3.3 BROAD PERSISTENCE 审计

保持 `broad_stress_persists_10d` 正式语义不变，报告：

- target/raw OOF/calibrated OOF 的总行数、正负类和首次可用日；
- 连续 eligible spell/event cluster 数、长度和重叠标签比例；
- 191 calibrated 与 261 raw OOF 的差额逐项来自何种 warm-up/可用性条件；
- 最新 252 raw published-candidate 的 Brier Skill、ECE、reliability；
- `broad_spell_age`、过去 5/10 日 broad day count、F4–F7 breadth/level/slope 的条件方向；
- 开发/确认与 leave-one-cluster-out 稳定性；
- 5D 辅助 horizon 是否提供独立信息，还是仅改写 10D 问题；
- Bayesian/hierarchical shrinkage 是否能提高直接 10D OOF，而不是只收窄参数。

不允许把 5D 标签替换 10D 事件，不允许把 prior 当作新增 OOF 样本。

### 3.4 CALM-CARRY BREAK 脆弱性审计

审计候选事件固定为：

```text
event_id candidate: calm_carry_breaks_5d

eligible at t:
    data_status == OK
    AND carry_answer == SUPPORTIVE
    AND shock_answer == CALM
    AND persistence_answer == NORMAL

positive within t+1 ... t+5 if any:
    hard_acute == TRUE
    OR front_slope30 < 0
    OR broad_pressure_day == TRUE
    OR carry_environment_state == CLOSED for 2 consecutive sessions
```

阶段 A 必须先确认：

- future predicate 完全由天气事实构成，不含 SVXY/SGOV/VXZ；
- label 完整、PIT、censoring 与 UNKNOWN 行为；
- 完成样本、20/20 类门、开发/确认和独立事件簇数量；
- 与现有 acute/front/broad/carry 事件是否只是重复；
- 以下候选 predictors 的可用性、方向和增量：

```text
d1_log_vvix
d5_log_vvix
vvix_level / vvix_vix_coupling_residual
tail_price_score / skew level / d5 skew
vrp_ewma94 / carry_compensation
spx_5d_log_momentum
near_stress_log_ratio / d5_near_stress
front_slope30 / d5_front_slope30 / basis30_eod
```

不足 252、类不平衡、标签重复或两窗方向不稳时，候选必须 `REJECTED`；不得为获得 Short 交易而放宽。

### 3.5 STATE MICRO-CHURN 审计

原始 947 次 phase transition 只作为全集，不是缺陷计数。V3 micro-churn 候选定义：

```text
A -> B -> A within <= 3 formal sessions
AND no data gap / UNKNOWN bridge
AND no raw weather event cluster starts or ends in the interval
AND endpoint carry/shock/tail/persistence/repair answers are identical
```

逐项报告：

- micro-churn 数、涉及 phase 对、持续时间；
- risk-off、risk-on、lateral 三类；
- 是否改变稳定 answer、fragility eligibility 或概率 event status；
- 与实际 V2 probe asset switch 的交集只可从本合同冻结摘要读取，不得打开价格账本；
- 边界距离/多轴确认能否解释反转；
- 若增加恢复确认，会造成多少原始事件延迟、漏报或继续关闭。

只有 micro-churn 被独立复现，才能开启 `STATE-CHURN-002`。不得以降低总 transition 数为目标。

### 3.6 新数据与高阶特征可行性审计

当前正式数据允许直接派生：

- `d1_log_vvix`；
- SPX close-to-close 5 日动量；
- VIX9D/VIX 近端收敛；
- 因果 trailing VVIX/VIX coupling residual；
- 现有 EWMA94 VRP proxy。

当前正式数据不允许宣称：

- SKEW 1M/3M/6M term structure；
- Parkinson RV（需要 high/low）；
- Garman-Klass RV（需要 OHLC）；
- matched-horizon VRP surface；
- near variance-swap basis 或 SPX option-chain surface。

阶段 A 只记录数据缺口、来源候选、历史覆盖、许可/PIT 要求和方法边界，不下载、不购买、不导入。
现有 DATA/TENOR 已通过，缺少高级数据不是当前 P0 defect。

---

## 4. 阶段 B：冻结缺陷台账与 V3 语义规格

`MATVIX_V3_AUDIT.md` 中每个缺陷必须包含：

```text
defect_id
severity = P0 | P1 | P2
layer = DATA | TENOR | STATE | TIMING | PROBABILITY | ADAPTER
observed symptom
reproduction command
causal evidence
business consequence
minimal repair
rejected alternatives
affected existing files
semantic/version impact
station acceptance criterion
economic relevance, if any
status
```

初始 defect 候选与开工状态：

| defect_id | 初始状态 | 层 | 说明 |
|---|---|---|---|
| `PROB-CAL-002` | REQUIRED | PROBABILITY | 自由 Platt 排序倒置、漂移滞后和 warm-up publication 语义 |
| `PROB-CARRY-002` | REQUIRED | PROBABILITY | Carry recovery 的 duration/hazard 信息缺失 |
| `PROB-BROAD-002` | CLOSED_BY_SCOPE | PROBABILITY | direct-10D 条件模型拒绝；固定为 `BASE_RATE_ONLY` 参考并豁免模型门 |
| `PROB-FRAGILITY-002` | REQUIRED / AUDIT_ACCEPTED | PROBABILITY | `calm_carry_breaks_5d` 正式进入阶段 B 冻结与完整模型验收 |
| `STATE-CHURN-002` | REQUIRED_LIMITED | STATE/TIMING | 只允许处理阶段 A 编号的 14 个 risk-on 候选；20 个 risk-off 禁止阻尼 |
| `DATA-OPTION-002` | DEFERRED | DATA | 需要新授权数据时另行立项，不属于默认 V3 |
| `ADAPTER-002` | BLOCKED_BY_STAGE_D | ADAPTER | 站内全通过后只冻结一个 fragility-aware 固定探针 |

阶段 B 冻结后的正式概率集合固定为：

```text
FEATURE_CONDITIONAL_REQUIRED:
    acute_front_stress_5d
    front_inversion_5d
    mid_curve_pressure_accelerates_5d
    carry_environment_recovers_10d
    calm_carry_breaks_5d

BASE_RATE_ONLY_EXEMPT_FROM_MODEL_GATE:
    broad_stress_persists_10d
```

这在验收计数上是五个条件概率模型加一个基准率参考。不得为形成“四加一”的口头计数而删除
Carry、Fragility 或三个既有通过事件中的任何一个。

阶段 B 必须以纯文档提交冻结：

- calibration input、公式、窗口、warm-up publication、fallback 和 model status；
- Carry duration features 与 Broad `BASE_RATE_ONLY` 发布的公式、reset/UNKNOWN/PIT 行为；
- 正式事件集合及每个 onset/horizon/future predicate/censoring/predictors；
- 是否接纳 `calm_carry_breaks_5d`；
- micro-churn 是否构成 defect，以及只允许修改的转移方向；
- feature/state/probability/schema/model/package version；
- 各 defect 的站内验收；
- 明确拒绝的特征、模型与数据路径。

第一行语义代码修改前必须先完成该文档提交。没有 defect_id 不得改业务代码。

---

## 5. 阶段 C：按 defect_id 最小施工

顺序固定：

1. `PROB-CAL-002`；
2. `PROB-CARRY-002`；
3. `PROB-FRAGILITY-002`；
4. `STATE-CHURN-002`，严格限于已接纳的 risk-on 编号；
5. 必要的 output/Schema/narrative/Dashboard 兼容；
6. 阶段 D 完整站内验收。

每个 defect 一个提交：

```text
复现失败测试
→ 最小实现
→ 聚焦测试
→ 正式历史/OOF 重建
→ 完整站内回归
→ 更新缺陷状态和证据
```

### 5.1 PROB-CAL-002 固定候选

V3 的二级校准主候选固定为：

```text
z_t = logit(clip(raw_logistic_probability_t, 1e-6, 1-1e-6))
p_t = expit(z_t + b_t)
```

其中 `b_t` 只用 prediction time 前已经 outcome-available 的完成 raw OOF 拟合：

```text
calibration_max = 252
calibration_min_positive = 20
calibration_min_negative = 20
slope = 1.0 fixed
purge/outcome availability = unchanged
```

发布语义固定为：

```text
raw model unavailable                 -> existing base-rate/history fallback
raw model available, calibrator ready -> ROLLING_INTERCEPT_252
raw model available, calibrator warmup -> IDENTITY_WARMUP using raw probability
```

每行必须持久化 `raw_probability / published_probability / calibration_method /
calibration_samples / calibration_positive / calibration_negative / intercept_b`。

禁止：

- 自由或负 slope；
- event-specific calibration algorithm；
- 结果后改窗口；
- 在 identity warm-up 行伪称已拟合二级 calibrator；
- 以 raw/secondary calibration 中事后更好的一个作为同日输出。

`CURRENT_FREE_PLATT_504` 只保留在冻结 V2 artifact 和审计对照中，V3 运行代码不得保留双路径。

### 5.2 PROB-CARRY-002 最小修复

第一版只允许在现有 Logistic 中增加已冻结 duration facts，不引入 survival library：

```text
carry_spell_age:
    consecutive formal sessions with carry event_status == ELIGIBLE
    reset when NOT_APPLICABLE
    null on UNOBSERVABLE/UNKNOWN
    next eligible row after UNKNOWN restarts at 1; never bridges a gap

log1p_carry_spell_age = log(1 + carry_spell_age)
carry_recovering_flag = 1 if carry_environment_state == RECOVERING else 0
```

`carry_environment_recovers_10d` 的标签语义保持不变。初始模型只比较：

```text
V2 predictors
V2 predictors + log1p_carry_spell_age + carry_recovering_flag
```

不得同时加入 SPX/VVIX/VRP 候选。duration 模型仍失败时，只能返回本 defect 或为一个经阶段 A
确认的残差事实新立 defect；不得一次加入特征包。

### 5.3 PROB-BROAD-002 `BASE_RATE_ONLY` 范围关闭

`broad_stress_persists_10d` 的 onset、eligibility、horizon、future predicate、censoring 和标签保持不变，
但 V3 不训练、不选择、不发布它的 feature-conditional Logistic 或二级 calibrator。eligible 且 outcome
尚未知的当日发布值只允许复用阶段 B 冻结的既有因果历史基准率公式，并明确持久化：

```text
probability_kind = BASE_RATE_ONLY
model_status = BASE_RATE_ONLY
calibration_method = NOT_APPLICABLE
raw_probability = null
published_probability = causal_base_rate
```

实际枚举名必须在阶段 B 按现有 Schema 能力冻结；若现有枚举不同，使用语义等价的既有值，不得建立
平行表示。Broad 仍参加 probability integrity 与 `BASE_RATE_REFERENCE` 验收，但不参加 252/20/20、
Brier Skill、ECE 或 AUC 的 `FEATURE_CONDITIONAL` 模型门。不得把参考值标记为 calibrated model、
不得把 base-rate reference 的完整性写成 Broad 模型 `PASS`，也不得继续搜索 direct-10D 特征。

### 5.4 PROB-FRAGILITY-002

只有阶段 A 样本、类门、事件独立性和分区方向全部通过时，才把
`calm_carry_breaks_5d` 加入正式事件集合。predictor 集必须在阶段 B 一次冻结，并满足：

- 仅含 prediction time 已知天气事实；
- 优先复用现有 feature；
- 最多新增 `d1_log_vvix`、`spx_5d_log_momentum`、一个因果 VVIX/VIX residual；
- Tail/VRP 可作为 predictor，不能成为 `carry_answer` 硬门；
- 不得从 ETF 结果筛选 predictor 或阈值；
- 不通过完整概率门则从正式事件集合彻底拒绝，不留 Dashboard 半成品。

### 5.5 STATE-CHURN-002

若开启，只允许修复阶段 A 已编号的 micro-churn 转移：

- risk-off：零新增阻尼，急性/倒挂/广泛压力不得延迟；
- risk-on：允许基于同一原始轴的安全边际或多轴确认；
- lateral：只有无事件意义的 A→B→A 才可稳定；
- 不恢复 V1 通用计日滞回；
- 不发布未校准 confidence/membership；
- 不为了减少 phase 总数修改 answer、event label 或 probability eligibility。

### 5.6 DATA-OPTION-002

默认不施工。若现有数据候选均失败，需要新数据时必须停止并提交独立数据合同，至少包含：

- 数据源、许可、用途与再分发边界；
- 历史起点、覆盖、revision、available_at/PIT；
- SPX OHLC 或 option chain 的字段和单位；
- SKEW tenor/VRP surface 的期限匹配公式；
- 缺失、换方法、方法版本和追加不变性；
- 与现有单一 SKEW、close-only SPX、EWMA94 VRP 的非混淆规则。

没有人类明确批准不得下载、购买或导入。

### 5.7 实现位置与依赖

优先修改现有文件：

- feature：`src/matvix/features/builder.py`、必要的现有 feature 模块；
- state/duration：`src/matvix/state/ontology.py`、`state/transitions.py`；
- target：`src/matvix/probability/targets.py`；
- walk-forward/calibration：`probability/walk_forward.py`、`probability/calibration.py`；
- publication：`probability/engine.py`、`output.py`、现有 Schema；
- acceptance：`acceptance.py`；
- 配置：V3 就地替换 V2 配置，不保留双路径。

不得新增依赖。现有 NumPy/Pandas/SciPy/scikit-learn 足够完成固定 Logistic、截距校准和事件账本。

---

## 6. 阶段 D：完整气象站自身验收

站内验收禁止读取任何产品价格。输出：

```text
outputs/v3_station_acceptance/daily_ledger.parquet
outputs/v3_station_acceptance/summary.json
outputs/v3_station_acceptance/report.md
```

维度分别报告，不计算总分：

```text
DATA
TENOR
STATE_TIMING
PROBABILITY_INTEGRITY
PROBABILITY_MODEL
BASE_RATE_REFERENCE
FRAGILITY_EVENT
```

### 6.1 DATA/TENOR/STATE 回归门

- V2 的 3,172 direct / 162 bounded / 0 unavailable 与 5 个合法 d5 warm-up null 不恶化；
- PIT、vintage、追加不变性和 UNKNOWN 传播继续通过；
- F1–F7、TENOR 四阶段和 current fact LOCO 不恶化；
- answer/phase/event 可确定重放；
- acute/front/mid/broad/carry 的原始事件漏报不增、中位预警不晚、误报不增；
- 新 duration feature 不得改变历史 state/event label，只改变 predictor；
- 若施工 churn，risk-off timing 必须逐事件完全不劣于 V2。

### 6.2 Probability integrity 门

- 每个正式事件的 onset/horizon/future predicate/eligibility/censoring 可重放；
- training、20-session purge、outcome availability、base rate、raw model 和 calibration cohort 可重放；
- `published_probability` 与当日 `calibration_method` 算术一致；
- IDENTITY_WARMUP 明确，不伪称 intercept fitted；
- 不存在负 slope、未来 OOF、重复 key 或 append drift；
- 追加未来数据不改变过去已发布概率或 calibration method；
- 当前通过的 acute/front/mid-acceleration 三事件不得因统一算法而退化为 FAIL。

### 6.3 Probability model 门

每个 `FEATURE_CONDITIONAL_REQUIRED` 正式事件都必须在最新 252 个完成、当时实际可发布的 OOF 上满足：

```text
samples == 252
positives >= 20
negatives >= 20
Brier Skill versus frozen causal base rate >= 2%
ECE <= 7%
```

同时必须报告 raw 与 published probability、reliability quintiles、AUC、年度分层和事件簇 block
bootstrap。不得用 AUC 抵消 Brier/ECE，也不得用总体均值掩盖 rank reversal。

V3 晋级要求 acute/front/mid/carry/fragility 五个 `FEATURE_CONDITIONAL_REQUIRED` 事件全部通过。
Broad 是独立的 `BASE_RATE_ONLY` 参考，不计入模型通过率。任何必需条件模型
`FAIL/INSUFFICIENT_EVIDENCE` 时，`PROBABILITY_MODEL=FAIL`，停止进入阶段 E。

这里的 `PASS` 只表示在因果 rolling-origin 历史账本上满足冻结研究门，不能恢复已经失去的 untouched
确认资格；它只授权进入价格盲适配器冻结，不构成 production promotion。

### 6.4 Carry/Broad 专项门

Carry：

- duration 定义逐行重放且不跨 UNKNOWN；
- 开发/确认的 spell-age 恢复方向不系统反转；
- published reliability 不再出现低预测分位显著高于高预测分位的倒置；
- 相对 V2 raw/published model 的 Brier、ECE 和 cluster stability 全部报告，不隐藏任何退化。

Broad：

- 事件、eligibility、10D 标签、censoring 和实际独立事件簇继续可重放；
- 所有 eligible 发布行只使用当时 outcome-available 历史形成的冻结因果基准率；
- `probability_kind/model_status/calibration_method/raw_probability` 与 `BASE_RATE_ONLY` 合同逐行一致；
- append-only 重放不改变过去基准率，且不以 prior、重复标签或合成样本补足历史；
- `BASE_RATE_REFERENCE=PASS` 不得显示、汇总或叙述为 Broad feature-conditional model `PASS`。

### 6.5 进入适配器冻结的门槛

必须同时满足：

- DATA/TENOR/STATE_TIMING/PROBABILITY_INTEGRITY 全部 PASS；
- acute/front/mid/carry/fragility 五个条件概率事件全部 PASS；
- Broad `BASE_RATE_REFERENCE=PASS` 且仅标记为 `BASE_RATE_ONLY`；
- 没有未关闭 P0/P1 station defect；
- V3 语义、配置、Schema 和 package version 已冻结；
- 站内验收提交完成且工作树干净。

任一条件不满足时，V3 结论为 `STATION_NOT_READY`，不得编写或运行 V3 经济适配器。

---

## 7. 阶段 E：价格盲冻结 V3 适配器

阶段 E 仍不得读取价格。只允许更新本合同或 `MATVIX_V3_AUDIT.md` 的适配器规格，并以纯文档
提交冻结后，才实现最小映射。

### 7.1 固定事实谓词

V2 谓词保持：

```text
BASE_SHORT_ALLOWED =
    data_status == OK
    AND carry == SUPPORTIVE
    AND shock == CALM
    AND persistence == NORMAL
```

V3 只消费已通过的 fragility event，不把 predictor 本身变成硬门：

```text
FRAGILITY_ELEVATED =
    calm_carry_breaks_5d.event_status == ELIGIBLE
    AND calm_carry_breaks_5d.model_status == CALIBRATED_MODEL
    AND calm_carry_breaks_5d.probability_kind == FEATURE_CONDITIONAL
    AND calm_carry_breaks_5d.probability > calm_carry_breaks_5d.base_rate

SHORT_ALLOWED_V3 =
    BASE_SHORT_ALLOWED
    AND NOT FRAGILITY_ELEVATED
```

逐行 fragility probability 或 base rate 不可用时映射 SGOV；但如果该事件没有通过阶段 D，整个
Short V3 probe 为 `NOT_ELIGIBLE`，不得以 BASE_RATE_ONLY 代替。

禁止增加 Tail、THIN、VVIX、VRP 的第二组并列硬门，禁止概率阈值扫描。`probability > base_rate`
是施工前冻结的唯一风险抬升判定。

### 7.2 固定探针

```text
Short V3:
    SHORT_ALLOWED_V3 -> 100% SVXY
    otherwise        -> 100% SGOV

Long V3:
    persistence == DIFFUSING -> 100% VXZ
    otherwise                -> 100% SGOV

Combined V3, precedence high to low:
    data_status != OK        -> 100% SGOV
    persistence == DIFFUSING -> 100% VXZ
    SHORT_ALLOWED_V3         -> 100% SVXY
    otherwise                -> 100% SGOV
```

Long 映射相对 V2 不变；它是 no-regression control，不允许为补偿 Short 收益而修改。

---

## 8. 阶段 F：一次历史经济诊断与前向观察

### 8.1 价格、时点、成本与基准

历史诊断必须复用 V2 冻结价格批次、adjusted-open 公式、共同 session、初始资金、5bp 单边成本、
t EOD → t+1 open 执行和单资产 100% 持有。不得重新下载历史价格、换提供方、修改 SGOV 起点、
填收益或改变成本。

主比较固定为 `V3 vs frozen V2`。V1 只在附表保留，不参与 V3 参数或裁决。

### 8.2 唯一输出

复用现有 `economic_probe.py` 及同一 HTML 生成路径，只扩展版本输入，不新增 renderer：

```text
outputs/v3_economic_probe/daily_ledger.csv
outputs/v3_economic_probe/report.json
outputs/v3_economic_probe/report.html
```

逐日必须保留：

```text
weather version
signal / decision_as_of / execution / return-through
carry / shock / persistence
fragility probability / base rate / model status / calibration method
BASE_SHORT_ALLOWED / FRAGILITY_ELEVATED / target asset
price / turnover / cost / gross return / net return / P&L / NAV / drawdown
```

### 8.3 固定经济判定

Short V3 只有同时满足才为 `POSITIVE`：

- 税费后终值不低于 V2 的 `$10,082.71`，且总收益不低于 `+0.83%`；
- 最大回撤严格优于 V2 的 `-24.54%`；
- 最差滚动 20 日严格优于 V2 的 `-13.97%`；
- turnover/cost 完整归因，不能用 phase transition 代替实际资产切换；
- 最差 20 个 SVXY 日的实际暴露逐日列出；
- 改善不是价格缺失、延迟执行或成本变化造成。

Long V3 必须与 V2 映射和结果逐日一致，除非经已关闭 STATE defect 改变了真实
`DIFFUSING` 事实；任何差异必须归因且主要风险不劣于 V2。

Combined V3 必须终值、最大回撤和 Worst-20D 均不劣于 V2，且完整解释 Short 与 Long 贡献。

任何一个 eligible probe 为 `MIXED/NEGATIVE`，综合历史结论均不得超过
`NO_COMPREHENSIVE_INCREMENT`。不得改变适配器后重跑。

### 8.4 污染边界与前向账本

即使历史三探针全部 `POSITIVE`，由于 2020–2026 价格和候选日期已被检查，结论只能是：

```text
HISTORICAL_RESEARCH_SUPPORT
```

不能表述为独立确认、真实前瞻或 production promotion。

完成历史诊断后，建立 append-only prospective shadow ledger：

- 起点是适配器冻结提交后的首个完整共同 session；
- 不回填冻结提交之前的日期；
- 每日只追加当时已知 signal、probability、position、price、cost 和 outcome；
- 不因前向结果修改已冻结阈值、事件或适配器；
- 正式 promotion 所需观察长度和独立 stress/fragility 事件数必须由单独 power/evidence 合同预先
  冻结，初始 V3 施工不得事后决定；
- 初始 V3 最终状态最多为 `RESEARCH_SHADOW_READY / NO_PRODUCTION_PROMOTION`。

---

## 9. 缺陷 loop 与停止条件

唯一合法 loop：

```text
站内异常
→ defect_id
→ label/feature/state/calibration 根因
→ 纯文档规格冻结
→ 单项最小实现
→ 站内完整验收
→ 若失败，只返回同一 defect_id
```

经济阶段：

```text
固定探针失败
→ signal/fragility/position/price/cost/P&L 归因
→ 记录结论并停止
→ 不从产品结果反推天气或概率阈值
```

合同 v1.1 的人类范围决定明确解除 v1.0 中“Broad direct skill 不足即停止全部施工”的阻断：
阶段 A 的 direct-10D 失败证据继续保留，`PROB-BROAD-002` 以 `CLOSED_BY_SCOPE /
BASE_RATE_ONLY` 关闭，阶段 B–F 不得再次把它当成待修复条件模型。该豁免只作用于 Broad 的模型
Skill/ECE 门，不豁免基准率发布完整性，也不预先保证 Carry、Fragility、状态或经济验收通过。

以下情况必须停止：

- V2 基线/hash/测试无法复现；
- calibration 或 duration 诊断不能按 PIT 重放；
- 需要 event-specific 算法、阈值扫描或大规模 feature search 才能通过；
- Broad 被发布为 feature-conditional/calibrated model，或把基准率完整性冒充成模型增量 PASS；
- Fragility event 样本、独立性或两窗方向不足；
- 需要新 option/OHLC 数据但没有独立授权合同；
- risk-off timing 因 churn 修复而变慢；
- 当前三个已通过概率事件发生退化；
- 第二次实现仍无法关闭同一 defect；
- 任何 P0/P1 station defect 未关闭；
- 经济探针已运行一次后提出修改 mapping/threshold/cost/lag。

---

## 10. 反过度设计与变更预算

V3 必须复用 V2 已有 pipeline、概率、acceptance 和 economic probe。阶段 F 之前：

- 净新增非生成 Python 与测试不超过 1,500 行；
- 新增跟踪文件不超过 6 个；
- 不新增第三方依赖；
- 不新增超过一个 V3 审计模块；
- 不新增通用 model registry、feature search、calibration framework 或 state framework；
- 每个新增字段、配置、CLI 和测试必须映射到一个当前 defect 的验收准则。

越线立即停止并更新 `MATVIX_V3_AUDIT.md` 的 scope-to-defect 表；行数不是质量目标，重用和删除
错误路径优先于增加抽象。

---

## 11. 提交与最终验证顺序

合同 v1.0 session 已提交：

```text
docs: freeze MatVIX V3 construction plan
```

V3 后续提交边界：

1. `audit(v3): record probability and stability defects`；
2. `docs(v3): amend Broad base-rate and fragility scope`；
3. `docs(v3): freeze probability and fragility semantics`；
4. `fix(PROB-CAL-002): publish monotone causal probabilities`；
5. `fix(PROB-CARRY-002): model carry recovery duration`；
6. `feat(PROB-FRAGILITY-002): publish calm carry break risk`；
7. `fix(STATE-CHURN-002): remove confirmed risk-on micro churn`；
8. `test(v3): complete weather-station self-acceptance`；
9. `docs(v3): freeze fragility-aware economic adapter`；
10. `feat(ADAPTER-002): implement frozen fragility adapter`；
11. `test(v3): run frozen V2 versus V3 probes`；
12. `docs(v3): record verdict and prospective boundary`。

每个功能提交运行聚焦测试、正式历史/OOF 重建和完整站内回归。最终必须运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src/matvix
.venv/bin/python -m matvix doctor --project-dir .
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-v3-station --project-dir .
git diff --check
git status --short --branch
```

只有阶段 D 全部通过且适配器已纯文档冻结，才允许再运行一次：

```bash
.venv/bin/python -m matvix run-v3-economic-probe --project-dir .
```

最终报告必须直接回答：

1. 当前 Platt 为什么失败，V3 如何防止排序倒置和 warm-up 失真；
2. Carry duration facts 是否提供稳定、直接的 OOF 增量；
3. Broad 10D 是否严格保持 `BASE_RATE_ONLY`，且没有被冒充为条件模型通过；
4. `calm_carry_breaks_5d` 是否被接纳并通过；
5. micro-churn 是否存在、改了什么、有没有牺牲 risk-off timing；
6. 五个必需条件模型、Broad 基准率参考和各自独立状态结论；
7. V3 vs V2 固定探针是否实现 Short 帕累托改善；
8. 哪些结果只是污染历史支持，哪些仍需前向观察；
9. 尚未验证、被拒绝或因数据权利延后的能力。

V3 不得直接合并 main 或推送。初始施工结束的最高合法状态为：

```text
RESEARCH_SHADOW_READY / NO_PRODUCTION_PROMOTION
```

---

## 12. 新 session 的第一条执行指令

```text
逐字阅读 /Users/logan/MatVIX/MATVIX_V3_CONSTRUCTION_PLAN.md，并把它作为唯一施工合同。
先验证 main、冻结 V2 代码基线 a2a8a58、三个证据 hash、完整测试与工作树；确认合同提交
相对 a2a8a58 只新增该文档后，创建 codex/matvix-v3。先冻结 V2 只读基线，再严格完成
阶段 A 的 calibration、Carry hazard、Broad、calm-carry break、micro-churn 与数据可行性审计。
阶段 A–D 不得读取 SVXY/SGOV/VXZ 价格或 v2_economic_probe 逐日文件，不得恢复隔离包，
不得扫描阈值、模型、窗口或特征。只有 MATVIX_V3_AUDIT.md 缺陷台账和 V3 语义规格以纯文档
提交冻结后，按 PROB-CAL-002 → PROB-CARRY-002 → PROB-FRAGILITY-002 →
STATE-CHURN-002 的顺序分别施工；Broad 只发布 `BASE_RATE_ONLY` 参考，不再施工 direct-10D
条件模型。五个必需条件概率事件与 Broad 基准率完整性全部通过后，先价格盲冻结唯一适配器，
才能运行一次历史经济诊断；
历史结果只允许标记 HISTORICAL_RESEARCH_SUPPORT，不得晋升或推送。
```
