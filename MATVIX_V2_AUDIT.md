# MatVIX V2 阶段 A：V1 五维业务审计与缺陷台账

> 审计合同：`MATVIX_V2_CONSTRUCTION_PLAN.md` 1.0
> 审计对象：冻结的 `MATVIX_CBOE_CORE_V1`
> 基线提交：`6ac5b93b8d6f9fbd66807f9aaa0779e9214934e5`
> 历史范围：`2013-05-20` 至 `2026-08-20`，3,334 个正式 session
> 审计日期：2026-08-22
> 状态：PHASE_A_COMPLETE / PHASE_B_SPEC_FROZEN / NO_SEMANTIC_CODE_CHANGED

## 1. 结论先行

V1 的 PIT 选择、三值 UNKNOWN 传播、目标删失、20-session purge、rolling-origin OOF
和顺序校准没有发现未来函数或算术篡改。以 `2024-12-31` 截断原始数据重新生成的
2,925 行 feature/state 前缀逐列不变，5,104 条共同 OOF 的预测、校准和训练边界也不变。

V1 仍有五项阻断 V2 的业务缺陷：

| defect_id | severity | layer | 一句话结论 | status |
|---|---|---|---|---|
| `DATA-001` | P0 | DATA | 严格 30 日 `VXCM30` 在完整 F1–F7 仍可得时周期性失去左夹逼锚；162 个直接缺口令 324 个 5 日变化不可用，另有 5 个合法 warm-up null | CLOSED |
| `TENOR-001` | P1 | TENOR | V1 没有直接发布 F4–F7 level/slope/breadth/change，`Persistence` 不能回答中期限当前处于扩散、已计价还是衰减 | CLOSED |
| `STATE-001` | P1 | STATE | `Persistence`、`PRESSURE_BUILDING` 和 `Repair` 混合不同业务阶段；边际修复不等于 carry 已恢复 | IMPLEMENTED / TIMING_GATE_PENDING |
| `TIMING-001` | P1 | TIMING | 相对独立原始事件簇，V1 对中期限扩散、衰减和 carry 恢复存在漏报、误报或延迟，现有滞回不能证明业务时效完整 | SPEC_FROZEN |
| `PROBABILITY-001` | P1 | PROBABILITY | 概率流水线完整，但现有 broad/repair 标签不是直接 F4–F7 扩散与 carry 恢复问题，两个模型也未提供可发布增量 | SPEC_FROZEN |

本审计没有读取任何产品价格，没有生成收益、仓位、策略、HTML、V1.1 路径，也没有读取
`/Users/logan/MatVIX_cleanup_quarantine/`。旧 Research Shadow 数字没有作为预期答案或证据。

## 2. 可复现证据与边界

唯一审计入口：

```bash
cd /Users/logan/MatVIX
.venv/bin/python -m matvix audit-v2 --project-dir .
```

它只生成：

```text
outputs/v2_audit/business_audit_daily.parquet
outputs/v2_audit/business_audit_summary.json
```

人工结论仅为本文件。逐 session 事实、候选 F1–F7 字段、原始事件簇、V1 信号和现有
概率 label/status 均在 daily ledger；本文数字来自同一次 JSON 汇总。

### 2.1 正式 V1 基线

- `main`、tracking、`origin/main` 在开工时均为 `6ac5b93`，工作树干净；
- 合同提交的直接父提交为合同指定的 `f57e7f5efe2480b7f8a170b4c094459698fc4993`；
- 开工测试 203 项通过，Ruff、Mypy、doctor 全部通过；
- 正式顺序 `build-history → train-probabilities --full-rebuild → accept-real` 通过 13 个 V1 门；
- 冻结产物：features 3,334 行、states 3,334 行、targets 13,336 行、OOF 6,207 行；
- `v1_manifest.json` 已记录代码、配置、Schema、原始输入、行数、日期、SHA-256、命令与 UTC 时间；
- 所有正式历史原始输入为 `ASSUMED_PIT`，没有把它表述为真实历史发布时间证据。

### 2.2 数据授权边界

本轮只在用户本地对既有 Cboe/CFE/SPX 原始包做不可发布的研究审计。现有原始包说明已明确：
公共可得不等于商业使用或再分发授权。本审计不新增授权主张，不复制或发布原始数据；若后续用途
扩展到商业分发或外部交付，必须先独立确认数据权利。

## 3. 五维审计结果

### 3.1 DATA：原始输入、PIT、F1–F7 与连续性

通过的事实：

- 十个核心现货序列和 29,809 行标准月 VX 归一化记录均无重复 revision key、非正值或未知 vintage；
- 每个已选记录均满足 `available_at <= decision_as_of`；方法版本单一且已记录；
- 3,334 个正式 session 均能选出连续、正值、月份相邻的 F1–F7；V1 的 F1–F6 选择与独立重算零差异；
- V1 严格 30 日公式在可计算日与独立手算零差异；
- 四个已知 SKEW 原始缺口继续诚实为缺失，没有前填或 0 兜底；
- `data_status=OK` 行没有必需输出空值或 UNKNOWN answer；
- 189 个 OK 行的隐藏 `recent_stress=null` 均由三值逻辑中的另一已知 FALSE 条件把最终
  `repair_answer` 确定为 `INACTIVE`，不是把 UNKNOWN 偷换成 FALSE。

阻断事实：

- 162 个 session 的 F1–F7 全部存在，但 `D1>30`，所以 `D_a <= 30 < D_b` 找不到左锚；
- 这些不是原始文件、解析、正值过滤或合约资格缺口，而是 V1 严格公式的定义域缺口；
- 162 个 `VXCM30/basis30_eod` 直接缺口使 `d5_log_vxcm30/d5_basis30_eod` 的 324 行不可用
  （当日 162 行及其 t+5 传播 162 行）；全列另有开头 5 个合法 warm-up null，因此现状总计 329 行；
- 缺口时 `D1-30` 的最大值为 5.7083 日，每个缺口都能由同日正值 F1/F2 形成小幅、有界后向线性候选。

伪缺口检验独立地在本来有严格 F1/F2 夹逼的日期隐藏 F1，改用 F2/F3 后向估计 30 日值：

| 分区 | 样本 | bias（VIX 点） | MAE（VIX 点） | 中位绝对百分比误差 | P95 | 最大误差 | 相关系数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 开发窗 | 296 | 0.0570 | 0.1220 | 0.5611% | 1.5912% | 3.3975% | 0.99959 |
| 确认窗 | 165 | 0.0508 | 0.0992 | 0.4226% | 1.3897% | 2.2057% | 0.99966 |
| 全部 | 461 | 0.0548 | 0.1138 | 0.5002% | 1.4812% | 3.3975% | 0.99962 |

这只证明“小幅同曲线后向估计”值得进入 V2 规格，不把候选值伪装为直接官方 observation。

### 3.2 TENOR：F4–F7 当前事实与业务区分

审计候选只使用同日及此前 F1–F7：

```text
f4_f7_level = mean(F4,F5,F6,F7)                         # VIX points
f4_f7_slope30 = ln(F7/F4) × 30 / (D7-D4)                # 30-day normalized log slope
f4_f7_inversion_share = [I(F4>F5)+I(F5>F6)+I(F6>F7)]/3
front_to_mid_log_ratio = ln(mean(F4:F7)/mean(F1:F2))
```

另算 5/10-session level、slope 和 inversion-share 变化。审计候选分类不属于正式 V2 规格，
只用于检验是否存在可区分业务事实：

- `mid_curve_pressure_state_candidate = QUIET/RISING/PRICED/RECEDING/UNKNOWN`；
- `stress_tenor_scope_candidate = NONE/FRONT/MID/BROAD/UNKNOWN`；
- 映射为审计阶段 `FRONT_LOCALIZED/DIFFUSING/PRICED/RECEDING/NONE`。

结果证明 V1 名称不能当作直接期限事实：

- 403 个 V1 `DIFFUSING` 中，审计候选仅 20.1% 为直接 F4–F7 `DIFFUSING`，25.8% 已
  `PRICED`，50.4% 没有同名中期阶段；
- 212 个 V1 `PERSISTENT` 中 73.6% 对应 `PRICED`，14.2% 已 `RECEDING`；
- V1 `DIFFUSING/PERSISTENT` 之后 5/10 日中期 level 多数下降、slope 修复；这与“当前已经
  扩散/计价后均值回落”一致，但不能被解释为继续恶化预测；
- 开发窗与确认窗的多数 answer 条件方向一致，但若干 phase 的未来 5/10 日方向反转，证明
  phase 不适合充当 F4–F7 事实标签。

结论：F4–F7 level、标准化 slope、inversion breadth 及变化有独立信息，必须先作为直接事实
冻结；不应再由 `Persistence` 高分或任何产品收益替代。

### 3.3 STATE：答案、phase、Repair 与 carry

V1 answer 枚举在所有 OK 行互斥且完整，UNKNOWN 传播未发现违反当前 V1 合同。缺陷在业务含义：

- 132 个 `PRESSURE_BUILDING` 同时包含候选 `FRONT_LOCALIZED=12 / DIFFUSING=17 /
  PRICED=27 / RECEDING=14 / NONE=62`，同一 phase 无法回答压力在哪里；
- 129 个 `BROAD_PERSISTENT_STRESS` 中，候选 56.6% 已计价、27.1% 正在衰减，只有 3.9%
  处于继续扩散；
- 157 个发布 `REPAIR_IN_PROGRESS` 中 61.8% 对应直接中期衰减，但 phase 的滞回使它不等于
  当日 `Repair=CONFIRMED`；
- 83 个当日 `Repair=CONFIRMED` 中，按审计候选的前端、basis、近端和中期结构同时恢复并连续
  确认的只有 8 个（9.64%）；Repair 的确是边际下降轴，不是 carry 重开事实。

结论：V2 必须分别表达压力期限范围、中期压力阶段和 carry 环境；`Repair` 可保留边际含义，
但不得继续被叙事或下游理解为 carry 已恢复。

### 3.4 TIMING：独立原始事件簇

event ledger 先由原始 VIX/VIX9D 与 F1–F7 level/slope/breadth/change 构成，连续 TRUE session
聚类；没有用待验收的 phase 给 phase 自己打标签。V1 信号与原始簇的审计结果：

| 原始事件 | 事件簇 | V1 漏报簇 | V1 信号簇 | 误报簇 | 首次信号中位延迟 |
|---|---:|---:|---:|---:|---:|
| 急性前端压力开始 | 197 | 82 | 101 | 14 | 0 session |
| 前端倒挂开始 | 88 | 15 | 77 | 7 | 0 session |
| 前端向 F4–F7 扩散 | 98 | 40 | 165 | 123 | 0 session |
| 广泛压力持续 | 64 | 30 | 40 | 9 | 0 session |
| 中期限压力衰减 | 160 | 104 | 67 | 23 | 1 session |
| carry 环境恢复 | 128 | 16 | 177 | 85 | 0 session |

补充事实：

- Repair 信号 67 个簇中有 3 个在原始 broad stress 仍在、尚未进入中期衰减时释放，候选过早释放率 4.48%；
- 原始 carry 恢复后，V1 共同稳定接口仍关闭的中位数为 2 个 session，最大为 23 个 session；
- 急性、前端倒挂、中期衰减和 carry 恢复的 leave-one-event-cluster-out 方向稳定；
- “扩散后未来继续上升”和“广泛压力后未来继续上升”方向不稳定，说明这些是当前状态，不是
  自动的趋势延续预测。V2 不得把当前 `DIFFUSING/PRICED` 写成未来收益或继续恶化承诺。

这些数字是审计候选 event ledger 的基准，不是 V2 通过结论。V2 规格冻结后必须用同一原始
事件定义重跑 V1/V2，才能应用“不增加漏报、不更晚、不增加误报”的站内门。

### 3.5 PROBABILITY：流水线完整，问题语义不完整

完整性检查通过：OOF 无重复 key，purge、outcome availability 和 Platt convergence 均零违规；
末端/未知 future predicate 继续删失，`BASE_RATE_ONLY` 没有被包装成预测增量。

最新 252 条完成且已校准 OOF：

| 事件 | Brier Skill | ECE | 当前正式结论 |
|---|---:|---:|---|
| `acute_front_stress_5d` | 7.60% | 5.07% | `CALIBRATED_MODEL` |
| `front_inversion_5d` | 8.23% | 4.22% | `CALIBRATED_MODEL` |
| `broad_persistent_stress_20d` | 20.62% | 9.89% | ECE 失败，诚实回退 `BASE_RATE_ONLY` |
| `fast_repair_5d` | -3.70% | 10.08% | 无增量；当前 session 不适用所以 `NOT_RUN` |

前两个事件的问题和标签仍然清楚。后两个事件的流水线没有造假，但业务问题不足：broad 标签
继承 V1 `Persistence` 原子谓词，fast repair 只预测边际修复；它们不直接回答 F4–F7 扩散、
压力持续或 carry 恢复。

仅做 cohort 可行性、尚未拟合模型的候选：

| 候选事件 | horizon | 全部完成样本（正/负） | 开发窗 | 确认窗 | 结论 |
|---|---:|---:|---:|---:|---|
| `front_stress_diffuses_to_mid_curve_10d` | 10 | 303（217/86） | 148 | 155 | 两窗各自不足 252，不得先承诺 feature-conditioned 模型 |
| `broad_stress_persists_10d` | 10 | 528（226/302） | 312 | 216 | 确认窗不足 252，只能待规格后严格验证或拒绝 |
| `mid_curve_pressure_accelerates_5d` | 5 | 1,624（685/939） | 933 | 691 | 两窗样本门可满足，仍需正式 OOF/校准增量 |
| `carry_environment_recovers_10d` | 10 | 1,941（632/1,309） | 1,161 | 780 | 两窗样本门可满足，仍需正式 OOF/校准增量 |

不能因为候选样本充足就自动纳入正式事件集合；规格必须先确定独立 future predicate、onset、
eligibility 和 censoring，之后仍按原门槛决定 `CALIBRATED_MODEL / BASE_RATE_ONLY / REJECTED`。

## 4. 缺陷台账

### DATA-001

```text
defect_id: DATA-001
severity: P0
layer: DATA
observed symptom: 完整 F1–F7 存在时，162 个 session 的 VXCM30/basis30_eod 仍不可用；它们令 324 个 5 日变化不可用，另有 5 个合法 warm-up null。
reproduction command: .venv/bin/python -m matvix audit-v2 --project-dir .
causal evidence: 所有缺口均 D1>30，F1–F7 连续、正值、正式 vintage，V1 选择与独立重算一致；根因是严格夹逼定义域没有左锚。
business consequence: 周期性 UNKNOWN/PARTIAL、Carry/score/state/probability eligibility 中断，并把单日定义域缺口传播到后续 5-session 特征。
minimal repair: V2 仅在 30<D1<=36、F1/F2 连续正值且 PIT/method 合法时采用同曲线有界线性后向估计；显式标记 reconstructed source kind 和方法版本；其他情况保持不可用。
affected existing files: src/matvix/features/futures_curve.py; src/matvix/features/builder.py; configs/features_v1.yaml（V2 就地替换时改名/升版）; src/matvix/output.py; schemas/daily_output.schema.json; 公式与 PIT 测试。
semantic/version impact: feature/schema/model 相关语义升为 2.0.0；不得改写 V1 冻结产物，不建立 V1/V2 双路径。
station acceptance criterion: 162 个定义域缺口均被可审计方法覆盖或严格降级；开发/确认伪缺口分别满足冻结误差门；direct/reconstructed/unavailable 不混淆；324 个缺陷相关 d5 null 按公式消除且只保留 5 个合法 warm-up null；未来追加不改变过去。
closure evidence: 正式全历史 3,334 行均为七锚；3,172 行 DIRECT_BRACKET_INTERPOLATION、162 行 BOUNDED_BACKWARD_EXTRAPOLATION、0 行 UNAVAILABLE；VXCM30 直接 null 从 162 降为 0，d5_log_vxcm30/d5_basis30_eod 均只余开头 5 个合法 warm-up null；所有 bounded 行 formal-vintage eligible，最大 D1=35.7083；开发/确认伪缺口固定门均通过；210 项测试、Ruff、Mypy、doctor 和 13 个现有正式验收门通过。
status: CLOSED
```

### TENOR-001

```text
defect_id: TENOR-001
severity: P1
layer: TENOR
observed symptom: V1 只含 F1–F6 curve breadth，并以 SPX IV forward vol 混合构造 Persistence；没有直接 F4–F7 当前事实。
reproduction command: .venv/bin/python -m matvix audit-v2 --project-dir .
causal evidence: F1–F7 全历史完整；V1 DIFFUSING 仅 20.1% 对应审计候选直接扩散，PRESSURE_BUILDING 同时覆盖五种不同中期阶段。
business consequence: 用户无法区分前端局部压力、向中期扩散、已经计价和正在衰减；名称容易被误读为趋势或产品信号。
minimal repair: 增加最小 F4–F7 level、30-day normalized slope、inversion share、5/10-session change，并只在这些直接事实之上冻结 tenor scope 与 mid-curve pressure state。
affected existing files: src/matvix/features/futures_curve.py; src/matvix/features/builder.py; src/matvix/state/scores.py; configs/features_v1.yaml; configs/state_v1.yaml; output/schema/tests。
semantic/version impact: feature/state/schema/model 语义升为 2.0.0；删除被替代的旧 Persistence 混合含义，不保留双实现。
station acceptance criterion: 新字段公式、单位、换月、缺失、PIT 可重放；四种期限阶段有不同 F4–F7 事实；开发/确认条件方向不系统反转；危机留一方向稳定或诚实拒绝该字段。
closure evidence: 正式 3,334 行的 F4–F7 level/slope/inversion breadth/front-to-mid ratio 均可用，公式、单位、F1–F7 完整性、5/10-session 变化和方法分段均有测试；直接候选计数为 DIFFUSING=206、PRICED=322、RECEDING=601、FRONT_LOCALIZED=144。开发/确认样本分别为 DIFFUSING 106/100、PRICED 206/116、RECEDING 369/232；前两类 d5/d10 level 中位数均为正且 slope-change 均为负，RECEDING 恰好相反；98/96/160 个相应事件簇的 leave-one-cluster-out 当前方向均稳定。Persistence 与 Repair 轴已改为冻结 F4–F7 事实；212 项测试、Ruff、Mypy、正式全历史重建及 13 个现有验收门通过。
status: CLOSED
```

### STATE-001

```text
defect_id: STATE-001
severity: P1
layer: STATE
observed symptom: Persistence/phase 混合局部、扩散、已计价、衰减；Repair=CONFIRMED 也常被解释为 carry 已恢复。
reproduction command: .venv/bin/python -m matvix audit-v2 --project-dir .
causal evidence: PRESSURE_BUILDING 的 132 行分散到五类直接 tenor 阶段；83 个 Repair=CONFIRMED 中仅 8 个满足审计候选 carry OPEN 连续条件。
business consequence: 当前市场故事和下游稳定接口不能唯一回答压力期限或 carry 是否开放，可能把边际下降过早解释为可承担风险。
minimal repair: 分别冻结 stress_tenor_scope、mid_curve_pressure_state、carry_environment_state；以它们重写 persistence/carry answer 与 phase；Repair 只保留边际修复含义。
affected existing files: src/matvix/state/scores.py; src/matvix/state/ontology.py; src/matvix/state/transitions.py; configs/state_v1.yaml; narrative/output/schema/tests。
semantic/version impact: state/schema/model 语义升为 2.0.0；稳定接口字段名可保留，但含义改变必须在 V2 规格逐项写明。
station acceptance criterion: answer/phase 互斥、完整、确定重放并传播 UNKNOWN；相同直接 tenor 事实不会映射为相互冲突状态；Repair 与 carry OPEN 有独立字段和验收。
implementation evidence: 2,803 个 OK row 的三个 structure 字段和五个当前 answer 均无 UNKNOWN；正式计数为 scope NONE/MID/BROAD/FRONT=1,314/667/525/297，mid QUIET/RISING/PRICED/RECEDING=1,012/599/593/599，carry CLOSED/RECOVERING/OPEN=1,338/800/665。`PRESSURE_BUILDING` 与 calendar phase 已为 0；Repair CONFIRMED 599 行全部不等于 carry SUPPORTIVE，另有 665 行 SUPPORTIVE 且 Repair 未确认，两个含义没有逻辑蕴含。V2 JSON 已要求并校验 `market_story.structure`；213 项测试、Ruff、Mypy、doctor、正式全历史重建与 13 个现有验收门通过。
remaining dependency: 旧通用 phase hysteresis 仍造成 535 个非 acute 的 phase/raw_phase 差异；按冻结规格只能由 TIMING-001 删除，故本 defect 在 TIMING-001 通过前不标 CLOSED。
status: IMPLEMENTED / TIMING_GATE_PENDING
```

### TIMING-001

```text
defect_id: TIMING-001
severity: P1
layer: TIMING
observed symptom: 相对原始事实事件簇，V1 在中期扩散、广泛压力、衰减和 carry 恢复上存在大量漏报/误报，恢复后仍可能继续关闭。
reproduction command: .venv/bin/python -m matvix audit-v2 --project-dir .
causal evidence: 扩散 98 簇漏 40、误报 123；衰减 160 簇漏 104且中位延迟1日；carry恢复128簇漏16、误报85，恢复后继续关闭中位2日、最大23日。
business consequence: 现有 phase/hysteresis 无法证明风险关闭与释放时点忠实于期限事实；churn 下降也可能来自迟钝而非质量改善。
minimal repair: 在 STATE-001 的直接事实与独立 event ledger 上重写最小进入/退出/确认规则；不使用产品损失或收益调阈值。
affected existing files: src/matvix/state/ontology.py; src/matvix/state/transitions.py; configs/state_v1.yaml; station acceptance tests/module。
semantic/version impact: state/model 语义升为 2.0.0；任何 hysteresis 变化必须归属本 defect，不建设通用状态治理框架。
station acceptance criterion: 相对冻结 V1，原始事件簇漏报不增、中位首次预警不晚、误报簇不增；Repair 延迟下降且过早释放不增；churn 改善不能延长关闭。
status: SPEC_FROZEN
```

### PROBABILITY-001

```text
defect_id: PROBABILITY-001
severity: P1
layer: PROBABILITY
observed symptom: 概率流水线正确，但 broad/fast-repair 问题继承模糊 V1 状态，不能直接回答 F4–F7 扩散/持续与 carry 恢复；相应模型无可发布增量。
reproduction command: .venv/bin/python -m matvix audit-v2 --project-dir .
causal evidence: broad 模型 ECE=9.89% 仅 BASE_RATE_ONLY；fast repair Brier Skill=-3.70%、ECE=10.08%；直接候选 cohort 显示 accel/recovery 两窗样本充足，而 diffusion/persistence 确认窗不足252。
business consequence: Dashboard 的历史参考率可能被误解为当前特征增量，也缺少真正中期限和 carry 恢复概率问题。
minimal repair: 保留通过且业务问题清楚的 acute/front-inversion；仅从已冻结直接事实选择最小新事件，逐项写 onset/horizon/future predicate/censoring/predictors；样本或校准不足则 REJECT 或 BASE_RATE_ONLY。
affected existing files: src/matvix/constants.py; src/matvix/probability/targets.py; src/matvix/probability/walk_forward.py; src/matvix/probability/engine.py; configs/probability_v1.yaml; output/schema/tests。
semantic/version impact: probability/schema/model 语义升为 2.0.0；正式事件集合整体替换，不保留 V1/V2 并行开关。
station acceptance criterion: 标签/eligibility/purge/OOF/校准算术可重放；CENSORED 保持严格；FEATURE_CONDITIONAL 继续要求 Brier Skill>=2%、ECE<=7%及样本门；未达标新事件不留半成品字段。
status: SPEC_FROZEN
```

## 5. 非缺陷与明确拒绝

- V1 现有 `BASE_RATE_ONLY` 回退是诚实行为，不是算法缺陷；不得为制造交易而放宽门槛。
- `recent_stress=null` 但最终 Repair 可由已知 FALSE 决定，符合三值逻辑，不新建缺陷。
- 所有历史正式输入是 `ASSUMED_PIT`；本审计验证保守 availability 与追加不变性，但不把它升级为
  `OBSERVED_PIT`。
- 中期状态后的未来均值回落不说明状态错误；状态描述“现在”，概率才回答“未来”。
- 没有任何证据允许把 F4–F7 事实称为 VXZ 盈利信号，也没有读取 VXZ 或其他产品价格。

## 6. 阶段 A 闭环与下一门

阶段 A 已完成：逐 session 账本、机器汇总、五维人工结论和五个 defect_id 已形成。下一步只能先
在 `MATVIX_PRE_DEVELOPMENT_REPORT.md` 冻结 V2 数据、公式、answer/phase/UNKNOWN、事件、Schema
与版本 delta，并以纯文档提交结束阶段 B。该提交之前，不得修改运行配置或任何业务语义代码；
阶段 B 已完成：V2 数据、公式、answer/phase/UNKNOWN、事件、Schema 与版本 delta 已在
`MATVIX_PRE_DEVELOPMENT_REPORT.md` 第 21 节冻结。下一步只允许从 `DATA-001` 开始，按固定顺序
逐 defect 施工；每个 defect 在实现、聚焦测试、完整站内回归和证据更新完成前不得标记 CLOSED。

## 7. 反过度设计熔断后的 scope-to-defect 重映射

`STATE-001` 完成实现、尚未进入 `TIMING-001` 时，按
`git diff --numstat 6ac5b93 -- '*.py'` 统计的累计 Python additions 为 2,002、deletions 为 239，
比 2,000 行熔断线高 2 行。施工已在此点暂停并重新核对范围，结果如下：

| 范围 | Python additions | 直接对应 | 保留理由 |
|---|---:|---|---|
| 阶段 A | 1,319 | 五维逐 session 审计、CLI 入口、聚焦测试 | 唯一允许的业务审计模块；承载 DATA/TENOR/STATE/TIMING/PROBABILITY 全部可复现台账，不是通用治理包 |
| `DATA-001` 提交 | 241 | F1–F7、VXCM30 source kind、有界公式、freshness/acceptance/config/tests | 每项均用于关闭 162/324 缺口或阻止错误 OK |
| `TENOR-001` 提交 | 146 | F4–F7 公式、5/10 日变化、score/narrative/output/config/tests | 每项均发布或验证冻结的直接期限事实 |
| `STATE-001` 当前 worktree | 297 additions / 139 deletions | 三个 structure 字段、answer/raw phase、Schema/acceptance/config/tests | 替换旧混合语义；没有第二状态机或版本分支 |

分提交 additions 相加与最终 diff 因同一行多次替换会相差 1 行；熔断判断采用较保守的最终
2,002 行。相对 `main` 目前只有 3 个真正新增跟踪文件：`MATVIX_V2_AUDIT.md`、唯一审计模块和
其测试；两个 V2 YAML 是删除旧路径后的就地改名。新增文件数为 3，低于 8。

重映射裁决：`PROCEED_WITH_EXISTING_SCOPE`。越线主要来自合同要求的 1,255 行五维审计账本，
不是 renderer、publication、governance、plugin、generic validation、策略或 V1/V2 双路径。
后续 `TIMING-001`、`PROBABILITY-001` 和阶段 D 必须继续扩展现有
`state/transitions.py`、`probability/*`、`acceptance.py` 与既有测试，不新增通用包；阶段 D
通过前不创建经济探针模块。每次提交继续报告累计行数与新增文件，且任何新增单元必须能映射到
当前 defect 的冻结验收准则。
