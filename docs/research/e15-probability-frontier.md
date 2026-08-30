# E15 probability frontier research

Status: `ACTIVE`

Research generation: `E15_PROBABILITY_FRONTIER_R2`

Execution state: `M0_SPECIFICATION_AND_R0_RECEIPT_PREFLIGHT_AUTHORIZED /
NO_NEW_FORECAST_MODEL_FIT / PROSPECTIVE_NOT_STARTED`

Scientific state: `HISTORICAL_H3_SENSOR_RETAINED / REAL_EOD_PRIOR_NOT_ESTABLISHED /
REAL_0920_RECEIPT_NOT_ESTABLISHED / TWO_CLOCK_UPDATE_NOT_ESTABLISHED /
SAME_CLOCK_BEST_NOT_ESTABLISHED / ECONOMIC_INCREMENT_NOT_ESTABLISHED`

Authority: `EXPLORATORY_RESEARCH_ONLY / NO_V3_CHANGE / NO_PRODUCT_POSITION_ORDER_OR_TRADING_AUTHORITY`

## 1. Research object

MatVIX 下一轮 E15 不再寻找一个脱离信息时钟的单点“总冠军”。研究对象是：对同一个已经固定的
E15 终局事件，概率如何随真实、可审计的信息到达而更新。

对每个 XNYS origin session `t`：

```text
pair_id              = t
anchor                = VIX_close[t]
target_start_session  = t+1
target_end_session    = t+5
Y_t                   = 1[max(k=1..5) log(VIX_close[t+k] / VIX_close[t]) >= 0.15]
```

主 target 仍是 log `0.15` first passage，约等于简单涨幅 `16.18%`。literal 15% 只能是预写
敏感性。不同信息时钟必须共享同一个 `pair_id`、anchor、target window、deadline 和 outcome；
09:20 不得重新 anchor 或把 horizon 缩成 `t+2..t+5`。

初始概率前沿只取两个真实 landmark。这里必须区分“时钟前市场中存在的全部信息”、“理想条件
概率”与“模型实际发出的 forecast”。令 `G_E` 与 `G_M` 为模型可审计的嵌套信息集：

```text
G_E(t) = sigma(EOD cutoff 前模型实际使用的 matured history 与 receipts)
G_M(t) = G_E(t) ∨ sigma(EOD cutoff 后、09:20 cutoff 前模型实际使用的新 receipts)

p_E_star(t) = P(Y_t = 1 | G_E(t))   # ideal estimand
p_M_star(t) = P(Y_t = 1 | G_M(t))   # ideal estimand

P_EOD(t)    = actual emitted EOD forecast
P_0920(t)   = actual emitted 09:20 forecast
```

`G_E`/`G_M` 分别只是完整市场信息 `F_EOD`/`F_09:20` 的可审计子集。除非模型确实使用了完整
信息，不得把 ideal estimand 写成对完整市场状态的条件概率；`P_EOD/P_0920` 也不得在验收前冒充
对应的 ideal estimand。

这不是声称市场只在两个时刻更新，而是先裁决最小可识别对象：两个概率节点和一条
`EOD -> 09:20` 更新边。Asia、Europe、08:30 或其他时钟只有在这条边成立，并且各自拥有新增
信息、明确业务用途和完整 receipt 后，才能逐个加入。

## 2. Current working context

### `NORTH_STAR`

建立同一固定 E15 事件上可校准、可拒绝、可审计的概率前沿，并对预写的信息更新器、模型结构与
lead-time trade-off 作不越界的比较。

### `CURRENT_EVIDENCE`

- P0 已证明五日 first-passage、maturity、episode 和历史考卷可以一致重建。
- H3 Q1m 是已执行 H1/H2/H3 候选中唯一 nominated，并在共同历史 cohort 上 strongest observed。
- H3 的增量使用了次日 09:20 信息，因此历史领先不能拆成纯方法优胜；same-clock/global best
  均未建立。
- H3 pooled 概率尺度掩盖了 2020–2023 与 2024–2026 的 calibration 方向反转；RI252 没有修复
  proper score、slope、WRMS 或 resolution，已关闭。
- 现有事后证据更符合 `PRIOR_DRIFT_DOMINANT / SENSOR_INFORMATION_RETAINED` 的方向，但 prior、
  sensor mapping 与 observation-quality drift 尚未被可重复分离，当前不得把该方向写成正式归因。
- H3 与 overnight repricing 高度同向，却没有排序 09:20 后固定动作损失；它应被称为
  `likelihood-ratio-like discriminative sensor`，不是 literal posterior、Bayes factor 或完整概率模型。
- 历史 prior-close 数据不是实际发出的 EOD probability receipt；Q1m 也没有 MatVIX 当时的
  `received_at` 或 exact tick age。真实两时钟链尚不存在。

完整历史数字和 machine-evidence 导航在
[`../archive/e15-occurrence-2026-08.md`](../archive/e15-occurrence-2026-08.md)。历史结论在本轮只是
输入证据，不是新计划的执行合同。

### `CLOSED_LEAVES`

- H1：daily VIX9D/VIX/VIX3M front curvature；
- H2：daily VWA/VWB + VSTN/VSTF measurement state；
- RI252：causal rolling-intercept calibration repair；
- `VETO_NEW_SHORT_5D`：该资产、时钟、动作和损失定义下的固定 action leaf。

Round 1 的 three-session lag candidate 为 `ZERO_FIT / DEPENDENCY_BLOCKED`，不是对所有 sequential
forecast research 的科学否定。`CLOSED_LEAF` 只约束原信息集、时钟、构造和主张；动作失败只关闭
动作叶子。

### `CURRENT_QUESTION`

> 对同一个 E15 事件，真实 EOD prior 在次日 09:20 收到新增市场信息后，能否形成一条稳定、
> 可校准且在 proper loss 上有增量的更新边；四个预写 estimand 分别对 prior、基本 overnight
> updater、H3 双特征结构和一个 admissible challenger 提供什么证据？

这些 estimand 是路径依赖的 paired contrasts，不是可相加的因果贡献、百分比分解或 Shapley
归因。

### `MINIMAL_SURFACE`

本轮首先只允许：

- 在读取归因结果前把 M0 estimand、规格和终态规则冻结到本文件；
- 规格冻结后，一个 no-new-forecast-fit attribution runner、一个 focused test、一个 ignored output；
- R0 使用一个最小 shadow collector、一个 focused test 和一个 ignored append-only receipt ledger；
- 继续维护本文件作为唯一 active E15 authority。

在 receipt 与语义门通过前，不新增产品 package、API、Schema、Dashboard、adapter、组合器、仓位
接口或交易组件。

## 3. What must be separated

下一轮不得再把以下问题压成一句“H3 是否最好”：

| 问题 | 必须使用的比较 |
|---|---|
| EOD prior 是否成立 | climatology anchor 的 receipt、校准与稳定性；任何 EOD market candidate 另须同钟击败该 anchor |
| 预写的极简 overnight updater 是否有增量 | 09:20 `CARRY` 对 `SIMPLE`；不解释为纯 clock rent |
| H3 结构是否有独立价值 | 同一 09:20 clock 上 `SIMPLE` 对 `H3` |
| 同信息新表示是否优于 H3 | 同一 receipt cohort 上 `H3` 对一个预写 `METHOD` challenger |
| 真正新增信息是否优于 H3 | 同一 receipt cohort 上 `H3` 对一个预写 `NEWINFO` challenger |
| 概率修订是否诚实 | 两个节点各自的概率语义，加上 EOD→09:20 更新边的一致性 |
| 是否产生经济价值 | 另行冻结动作、损失、可选集合、entry/exit clock 与可执行报价 |

排名、概率尺度、跨时钟更新、经济映射和交易执行是不同证据层，任何一层通过都不能替代另一层。

## 4. Two real clocks

### 4.1 EOD node

第一条可审计 EOD anchor 使用 prospectively emitted dynamic climatology，并准确命名为
`EOD_CLIMATOLOGY_PRIOR`，不是 EOD market posterior。它只使用在 EOD cutoff 前已经成熟的历史
outcome，在该时钟真实发出并保存；不得次日回填。

EOD 的精确 cutoff 不在文档中凭经验臆定。R0 必须先观测官方 anchor 与必要输入的实际发布时间和
receipt latency，再在首次 collection 前冻结 cutoff。若不能形成稳定 receipt 语义，状态为
`EOD_CLOCK_UNBOUND`，正式两时钟评分不得启动。

未来的 EOD slow-vulnerability candidate 是一条独立支线。它必须用真正新增的 causal/PIT 信息在
EOD 同钟击败 climatology；若替换 `P_EOD`，任何原 H3 update coefficient 都不能自动平移，必须作为
新的 updater 重新接受 OOF 和 prospective 评估。

### 4.2 09:20 node

09:20 ET cutoff 只允许使用 `local_byte_received_at <= 09:20:00 America/New_York` 的记录。minute bar 的
exchange timestamp、历史 availability 假设或后来下载成功都不能替代 receipt。服务规则唯一固定为：

- `P_EOD` 或 target identity 无效时，所有 forecast 一起 `ABSTAIN`；
- `P_EOD` 有效但任一 09:20 update 输入无效时，所有 update policy 都原样输出 `P_EOD` 并标记
  `CARRY_DATA`；不得让某个 candidate 选择性 abstain；
- genuine-update common cohort 只作次级机制诊断，正式服务分数覆盖上述统一全服务策略。

所有 09:20 forecast 共享同一个 `P_EOD`、pair、outcome、receipt cohort 和服务策略：

| Forecast | 定义 | 作用 |
|---|---|---|
| `P_CARRY` | `P_EOD` 原样带到 09:20 | 严格零更新基线 |
| `P_SIMPLE` | `P_EOD` 加一个冻结的 F1 overnight repricing update | 估计指定极简 updater 的增量，不识别纯 clock rent |
| `P_H3` | `P_EOD` 加冻结的 F1 repricing 与 F1/F2 curve repricing | 识别 H3 双特征结构增量 |
| `P_METHOD` | 使用与 H3 相同 PIT bytes 的新表示 | 检验 same-information method increment |
| `P_NEWINFO` | 含 H3 无法确定的新增 PIT receipt bytes | 检验 new-information increment |

历史 H3 的 raw coordinates 为：

```text
z1 = log(mid_F1_09:20 / prior_settle_F1)
z2 = log(mid_F1_09:20 / mid_F2_09:20)
     - log(prior_settle_F1 / prior_settle_F2)
```

历史 walk-forward 每个 origin 使用当时训练折的 `mean/scale/beta`，不能把 raw `z1/z2` 直接乘一个
全期 beta。M0 在 genuine rows 上的 canonical emitted score 固定为：

```text
s_H3_emit = logit(h3_probability) - logit(b0_probability)

s_H3_replay = beta1*((z1-mean1)/scale1)
            + beta2*((z2-mean2)/scale2)
```

M0 必须用 ledger/artifact 中逐 origin 的 scaler 与 coefficient 重算并通过预写数值容差；字段不足时
标记 `H3_ESTIMATOR_PATH_UNRECONSTRUCTABLE`，不得用全期近似替代。`s_H3_emit` 是
discriminative log-odds update score。只有新的单一 prospective model identity、prior、cohort 和
概率门共同成立，`logit(P_H3) = logit(P_EOD) + s_H3` 才能获得 09:20 probability 身份；这里未来的
`s_H3` 必须是 M1/M2 冻结的单一 scaler/coefficient identity，不是历史逐折 score 的直接拼接。

每次冻结评估在 `P_METHOD` 与 `P_NEWINFO` 中至多接纳一个 challenger，并在看结果前写明类别；
不能把旧输入的新表示解释为新增市场信息。若没有 admissible challenger，该列留空；不得为了形成
“模型赛马”而增加 calibrator、lag、H3 变体或无假设特征篮子。

## 5. Honest revision edge

节点分别校准仍不足以证明它们构成诚实的信息更新。若 `G_E` 是 `G_M` 的子信息集，两个节点又
都是真正对应这些冻结信息集的条件概率，则必须近似满足：

```text
E[p_M_star - p_E_star | G_E] = 0
```

理想概率可以因新信息上调或下调；tower property 约束的是 `p_M_star - p_E_star`。对实际 forecast
只能检查 `P_0920 - P_EOD` 是否显示可预测违反；该条件不作用于 log-odds score `s_H3`。有限样本
未发现可预测 revision
时只能写 `NO_DETECTED_PREDICTABLE_REVISION_WITHIN_FROZEN_INFORMATION_SET`，不能宣称完整市场
martingale 已证明。

更新边的预写诊断至少包括：

- 同一 common cohort 上的 paired Brier 与 log loss；
- 全服务策略：`P_EOD`/target 无效时全体 abstain，只有 update 输入无效时全体 carry `P_EOD`；
- 按固定 `P_EOD` 区间和少量冻结 EOD 状态检查 mean revision；
- 按 `P_EOD` 与 revision 正负/幅度检查具体 `P_0920` candidate 的 conditional calibration；
- reliability、resolution 与概率排序，防止整体 intercept shift 冒充信息增量；
- 20/84-session block 与 positive-episode equal-weight sensitivity；
- 制度段、roll、DTE、spread、age、gap 和 source-quality 稳定性。

这是有限样本下的一步 coherence 诊断，不足以证明完整 martingale probability process。两个节点和
这条边全部得到支持时，最高只称 `REAL_TWO_CLOCK_UPDATE_NOMINATED`。

## 6. Observed update and method contrasts

令 `L` 表示越低越好的 proper loss，并对 Brier loss 与 log loss 分别计算。统一规定左侧 loss 减
右侧 loss 为正，表示右侧 forecast 更好：

```text
TOTAL_EDGE                  = L(P_CARRY)  - L(P_H3)
SIMPLE_OVERNIGHT_INCREMENT = L(P_CARRY)  - L(P_SIMPLE)
H3_STRUCTURE_INCREMENT     = L(P_SIMPLE) - L(P_H3)
CHALLENGER_OVER_H3         = L(P_H3)     - L(P_X)
```

- `P_X` 是本次结果不可见时预先接纳的 `P_METHOD` 或 `P_NEWINFO`，二者身份不能事后切换；
- `SIMPLE_OVERNIGHT_INCREMENT > 0` 只说明这个指定的简单 updater 有增量，不识别“等待一晚”所含
  全部信息的纯 clock rent；
- `H3_STRUCTURE_INCREMENT > 0` 才说明第二条 curve-repricing 坐标有同时钟增量；
- `CHALLENGER_OVER_H3 > 0` 才能在冻结候选集合和所属类别内提名 challenger；
- `H3 > CARRY` 但不胜 `SIMPLE` 的终态是 `SIMPLE_OVERNIGHT_INCREMENT_ONLY`，不是 H3 方法胜出；
- 历史 OOF 上的新胜者最多是 `HISTORICAL_NOMINATION_ONLY`，不能借同一考卷建立 best。

这些 contrast 的数值依赖候选路径和函数类；不得解释为 prior、时间、signal 或方法的因果份额。

## 7. Prior drift and sensor drift

M0 的 `p_prior` 固定为现有 ledger 中的 `B0_DYNAMIC_CLIMATOLOGY`，不是 B1，也不是新 EOD market
candidate。主归因 cohort 固定为 B0/H3 genuine-common origins，使 prior 与 sensor estimand 使用相同
case mix。all-origin/all-service B0 只作外部 prior 与 coverage 描述；missing、warm-up、carry 构成的
时期变化单列 `COVERAGE_DRIFT`，不得进入 prior-vs-sensor pattern label。M0 不重拟合 H3，只分别描述：

### Prior drift

- `mean(Y - p_prior)`、calibration intercept/slope、固定概率箱 gap；
- Brier reliability/resolution、事件率和 episode concentration；
- 2020–2023、2024–2026 及预写制度段的方向与幅度。

### Sensor and observation drift

- `z1/z2` 与 `s_H3_emit` 的分布、coverage 和 conditional relation to `Y - p_prior`；
- 现有 ledger 上 `H3-vs-prior` 的条件 score gain；`H3-vs-simple` 只有在 M1 冻结并生成
  `P_SIMPLE` 后才允许计算；
- 按固定 prior 区间检查 sensor mapping，避免 prior mix 变化冒充 sensor drift；
- 现有字段中的 roll、DTE、spread、gap、DST/holiday 与 source 变化；
- 明确区分市场关系漂移和 measurement/receipt-quality drift。

固定制度段的描述性分解可以使用：

```text
logit P(Y=1) = alpha_r + lambda_r*logit(p_prior) + gamma_r*s_H3_emit
```

`alpha_r/lambda_r`、`gamma_r`、prior-bin 内的 paired loss gain 与 sensor 分布必须联合阅读。
`logit(p_prior)` 与 `s_H3_emit` 相关，case mix 和系数可以相互补偿，因此任何单一回归系数都不能唯一
识别 drift 来源。该回归只作描述，不产生替代概率或新的 calibration candidate。

历史 `mean/scale/beta`、training cutoff/window 与 coefficient norm 的时期变化必须另列为
`ESTIMATOR_PATH_DRIFT`。无法排除 expanding walk-forward estimator 本身造成 score/mapping 变化时，
observable pattern 必须回退 `MIXED_OR_UNIDENTIFIED`。

M0 输出三个独立字段，不能把 limitation 混入互斥 label：

```text
observable_pattern =
    EVIDENCE_MOST_CONSISTENT_WITH_PRIOR_DRIFT |
    EVIDENCE_MOST_CONSISTENT_WITH_SENSOR_MAPPING_DRIFT |
    MIXED_OR_UNIDENTIFIED

estimator_path =
    STABLE_WITHIN_FROZEN_DIAGNOSTIC |
    DRIFT_DETECTED |
    UNRECONSTRUCTABLE

observation_drift_identifiability = UNIDENTIFIED_HISTORICALLY
```

只有当两种 block 设计下的相关 shift 区间方向一致、prior-bin 内 paired gain 和 sensor 分布共同支持，
且相互竞争的可观测解释没有同等证据时，才能使用前两个 observable label；否则必须
`MIXED_OR_UNIDENTIFIED`。若 estimator path 为 `DRIFT_DETECTED/UNRECONSTRUCTABLE`，sensor-mapping
label 不可使用。历史缺少真实 receipt/exact age/depth，因此 observation field 固定为
`UNIDENTIFIED_HISTORICALLY`，不能称其 dominant 或 absent。

这些是 `POST_HOC_DESCRIPTIVE_ONLY` 统计归因，不是因果识别，也不能用来重新校准 H3。

## 8. Mainline stages

### M0 — legacy no-new-forecast-fit attribution

目的：利用已有冻结 H3/B0/B1 ledgers，描述当前失准与哪种可观测 pattern 更一致，并明确历史
observation quality 无法识别的部分。

第一步只允许把以下内容冻结进本节，尚不读取新归因输出：输入列与 identity、`p_prior=B0`、回归
规格、genuine-common 主 cohort、all-service coverage 描述、逐 origin estimator replay、固定 prior
bins、制度段、20/84-session block、draw/seed、estimand、区间和 tie rule。冻结后才允许只读联结、
描述性 regression、effect decomposition 与 block/episode uncertainty。

禁止：重新拟合 H3、选择窗口、试 calibrator、用 outcome 选择新特征或改变历史裁决。

历史 ledger 不存在的 receipt、exact age、depth 或 size 字段必须保持 `UNKNOWN/UNAVAILABLE`，不得用
minute timestamp、后续时期字段或市场常识回填。

终态：上述 pattern label 与 observation limitation 的组合，并附 `POST_HOC_DESCRIPTIVE_ONLY`。

### R0 — real-clock receipt feasibility

与 M0 并行。主线 core 只排查并取得有权使用的 EOD anchor/forecast receipt 与 09:20 F1/F2 source
bytes。R0 明确授权一个 read-only shadow collector；它不得提交订单、修改 V3 或发布 E15 产品。
最小施工面固定为：

```text
analysis/e15_probability_frontier_receipt_preflight.py
tests/test_e15_probability_frontier_receipt_preflight.py
data/raw/live/e15_probability_frontier_receipts/       # ignored raw/receipt ledger
outputs/e15_probability_frontier_receipt_preflight/    # ignored report
```

每个外部 observation 与内部 prediction 必须区分以下时间，不得共用一个含糊的 `timestamp`：

```text
source_event_at          exchange event/bar-end time
source_published_at      supplier publication time, if supplied; otherwise UNKNOWN
local_byte_received_at   local UTC wall-clock captured before parsing
prediction_computed_at   computation completed locally
prediction_emitted_at    immutable forecast record appended locally
```

collector 还必须保存 local receive sequence、poll/stream cadence、duplicate/out-of-order disposition、
disconnect/reconnect/GAP、raw-byte identity，以及采集前后本机时钟同步来源、检查时间和 offset evidence。
`received_at` 在本研究中专指 `local_byte_received_at`；外部 source timestamp 不能替代它。

R0 core 验证：

- `source_event_at/source_published_at/local_byte_received_at`；
- instrument、expiry、DTE、roll mapping；
- F1/F2 bid/ask、gap、stale/late 与 source disconnect；
- EOD anchor receipt 与内部 `prediction_emitted_at`；
- source identity、取得时间、coverage 和权利/不可再分发边界；
- `pair_id`、target maturity、prediction immutability 与 outcome binding 可行性。

F3/F4、displayed size、完整 sequence/depth/trade 只属于需要这些字段的 `P_METHOD/P_NEWINFO` 支线，
不得因它们缺失阻断 CARRY/SIMPLE/H3 core。

R0 分成两个无 outcome 的 shadow window：

1. `R0A_SHAKEDOWN`：取得实际字节、核对 Schema/日历/rights，并据实冻结 validation window、最小
   coverage、最大 clock offset、receipt latency/staleness、允许 gap、contract-mapping tolerance、
   poll/stream cadence、duplicate/out-of-order 和 downtime/reconnect policy；
2. `R0B_VALIDATION`：只在随后新的 shadow sessions 上一次性应用这些数值门，不允许看结果后修改。

只有 R0B 通过预写门，才能得到 `REAL_CLOCK_RECEIPT_FEASIBLE`。产品页、搜索摘要或在同一
shakedown window 上拟合并验收门都不足以得到通过裁决。

### M1A — legacy assumed-PIT mechanics and nomination

前置条件：M0 specification 完成。该阶段明确使用历史 `ASSUMED_PIT/PRIOR_CLOSE_PROXY/Q1m`，不声称
历史真实 receipt。候选最多为 `CARRY / SIMPLE / H3 / one P_X`，其中 `P_X` 的 METHOD 或 NEWINFO
类别必须预先写明。

历史 walk-forward 只用于 mechanics、effect size 和 nomination。训练只使用当前 proxy clock 前已
成熟 outcome；五日重叠采用 paired blocks 与 episode sensitivity。看过的 2016–2026 数据不能成为
干净 holdout，也不能建立真实两时钟证据。

### M1B — live receipt shadow dry-run

前置条件：R0B 通过，且 M1A 已冻结模型生成方式。M1B 只用新的实时 receipts 检验 pair identity、
cutoff、contract mapping、统一 carry/abstain 服务规则和 forecast reproducibility，不使用未成熟
outcome 作选择或调参。

M1A/M1B 必须在 M2 前写清每个可部署 forecast 的唯一身份：training cutoff、训练样本、scaler、
coefficient、penalty、feature order、clipping、fallback 和 software version。legacy fold-specific OOF
coefficient 不能直接冒充 prospective coefficient；正式 cohort 开始前只能进行一次预写的
full-matured-history fit，随后冻结到正式 look。

### M2 — prospective freeze and collection

前置条件：至少 `CARRY / SIMPLE / H3` 通过 M1B live shadow dry-run，且 numeric gates、最小有意义
增量、training cutoff、cohort、统一服务规则、candidate class 与正式 look 已在 prospective outcome
不可见时冻结。

每个 pair 同时保存两个节点、所有 09:20 forecast、data status 和不可修改的 outcome binding。
在成熟 origin/positive-episode 门达到前只输出 `INSUFFICIENT_INFORMATION`。

### M3 — prospective two-clock adjudication

M3 使用依赖图，不把不同证据误写成一条线性 gate：

```text
CLOCK_TARGET_RECEIPT_IDENTITY
├── service/loss branch
│   ├── SIMPLE vs CARRY
│   ├── H3 vs SIMPLE and CARRY
│   └── frozen P_X vs H3
└── literal-semantics branch
    ├── EOD_CLIMATOLOGY_PRIOR semantics
    ├── each 09:20 candidate's own semantics
    └── revision diagnostic for each literal EOD/09:20 pair
```

- identity/receipt 失败时，所有正式比较停止；
- EOD calibration 失败时，service/loss branch 仍可报告 ordinal sensor increment，但禁止
  prior/posterior、martingale 或 literal frontier 语言；
- `SIMPLE` 不胜 `CARRY` 不阻断 `H3-vs-SIMPLE` 和 `H3-vs-CARRY` 的预写比较；
- `0920_PROBABILITY_SEMANTICS` 必须对 SIMPLE、H3 和被接纳的 `P_X` 分别报告；
- revision diagnostic 只针对同时获得 literal semantics 的 `P_EOD` 与具体 `P_0920`，不能对结果后挑出的
  winner 单独补做；
- 至少一个 09:20 candidate 同时通过自身 probability semantics、相对 CARRY 的 loss increment、
  revision diagnostic 和预写 stability，才允许 `REAL_TWO_CLOCK_UPDATE_NOMINATED`。

不得用一个分支的结果修复另一个分支，ordinal increment 也不能冒充 literal probability。

### M4 — frontier expansion

只有 M3 支持 `REAL_TWO_CLOCK_UPDATE_NOMINATED` 后，才允许把一个 Asia、Europe、08:30 event 或其他
landmark 加入概率前沿。新节点必须证明独立 receipt、新信息和业务用途；每次只增加一个节点并
重新检查相邻更新边。

### M5 — economic and action frontier

只有概率候选先通过自己的 clock-specific 门，交易员再冻结资产、方向、决策时钟、entry/exit、
规模、基准动作、损失函数、bid/ask/size、费用、滑点和容量，才允许评估经济增量。

规范化 cost-loss、proper-score 改善或“更早预警”都不是可执行 P&L。旧
`VETO_NEW_SHORT_5D` 不因新概率研究自动重开；任何新动作失败也只关闭该动作叶子。

## 9. Parallel research branches

并行支线必须在启动前声明自己属于新增 causal/PIT bytes 还是 same-information method，并各自先过
相应 data/source 或 representation P0；两类证据不得互换：

| Priority | Branch | First bounded question | Admission to main exam |
|---|---|---|---|
| P0 | `EOD_SLOW_VULNERABILITY` | shock/recovery 与系统脆弱性能否改善 EOD climatology | EOD 同钟历史 nomination 后 prospective |
| P0 | `GLOBAL_TRIGGER_CONFIRMATION` | 同步 ES/VX 与跨市场 breadth 是否确认 overnight trigger | `P_NEWINFO`；receipt-complete 09:20 challenger |
| P0 | `SCHEDULED_EVENT_MEASUREMENT` | 官方 event surprise 与 expiry-aligned ultra-short surface 是否新增信息 | `P_NEWINFO`；固定 event class 与 post-release clock |
| P1 | `TARGET_NATIVE_ASSIMILATION` | residual barrier、remaining uncertainty、DTE/roll 表示是否胜 H3 | 若只用既有 bytes，则为 `P_METHOD` |
| P2 | `CONTINUOUS_AUXILIARY_OR_ANALOG` | 连续最大幅度是否帮助表示 E15 | `P_METHOD`；另行授权，最终仍以 held-out binary E15 裁决 |
| P2 | `LOB_RESILIENCY` | 冲击后的 depth/spread/order-flow 恢复是否有信息 | `P_NEWINFO`；需要真实 LOB/trade/sequence receipt |
| P3 | `CROSS_MARKET_ECOLOGY` | 其他市场的同类 barrier state 能否迁移 | `P_NEWINFO`；whole-market/global-episode holdout 后 prospective |
| P3 | `LLM_EVENT_PARSER` | receipt-safe 公告能否形成冻结结构化 event input | `P_NEWINFO`；输入无效时按统一规则 carry |

TabPFN、Chronos、encoder、ensemble、evidence bus、GNN、Hawkes 和生成式路径当前不启动。算法本身不是
新增市场信息；至少两个独立 prospective sensor 通过前，不建组合层。

## 10. Decision states and stop rules

允许的主要终态：

```text
CLOCK_OR_TARGET_IDENTITY_FAIL
REAL_CLOCK_RECEIPT_NOT_ESTABLISHED
EOD_PRIOR_UNSTABLE
0920_ORDINAL_SENSOR_ONLY
REVISION_DIAGNOSTIC_NOT_SUPPORTED
NO_DETECTED_PREDICTABLE_REVISION_WITHIN_FROZEN_INFORMATION_SET
SIMPLE_OVERNIGHT_INCREMENT_ONLY
H3_STRUCTURE_INCREMENT_ESTABLISHED
METHOD_CHALLENGER_NOMINATED
NEW_INFORMATION_CHALLENGER_NOMINATED
REAL_TWO_CLOCK_UPDATE_NOMINATED
PROSPECTIVE_INSUFFICIENT_INFORMATION
```

- receipt/PIT/identity 失败：零正式评分；
- EOD prior 失败：禁止使用 literal prior/posterior/martingale 语言，但可保留 sensor 排序诊断；
- H3 不胜 `SIMPLE`：关闭 H3 双特征结构主张，不关闭指定的 SIMPLE updater；
- `P_X` 失败：只关闭该 method 或 new-information 叶子，不追加模型；
- calibration 再次出现制度方向反转：最多保留 `ORDINAL_SENSOR_ONLY`；
- historical pass：最多 nomination；prospective pass 也不等于 global uniqueness、产品或交易权限；
- 任何动作失败只关闭该动作叶子，不改写概率证据。

## 11. Evidence and authority boundary

本计划可以回答真实两时钟更新、指定 SIMPLE updater 的增量、H3 同钟结构增量、与各类 drift 最
一致的可观测 pattern，以及一个明确 method 或 new-information challenger 的问题。它不能识别纯
clock rent、drift 的唯一因果来源、H3 是否 literal Bayes factor、全球唯一/最佳方法、市场因果机制、
完整多节点 trajectory、经济 alpha、可执行动作或产品 readiness。

V3 product、Schema、发布值和 Prospective 001 cohort 保持冻结且独立。E15 R2 的 receipt/prospective
证据必须使用自己的 authority；不得把 V3 Prospective 001 冒充 E15 prospective 已启动。
