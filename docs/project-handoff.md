# MatVIX 阶段性交接说明：V1→V3 产品、V4 结论与 E15 active 研究

Status: `ACTIVE`

Snapshot date: `2026-08-28 Asia/Shanghai`

Document role: 项目介绍、证据导航与接手说明；不是新的模型合同、研究授权或交易授权。

## 1. 一页结论

MatVIX 是一个面向 VIX 保险市场的日终气象站。它不预测 SPX 或 SVXY 的价格，也不产生仓位和
订单；它先回答市场保险结构现在是什么天气，再回答若干天气状态在未来 5/10 个交易日发生的
概率。

整个主线可以概括为：

```text
V1：先把传感器、五轴天气、phase 和事件概率跑通
  ↓
V2：修复 30 日 VX 连续性、F4–F7 期限事实、状态语义和时效
  ↓
V3：修复概率校准、Carry 持续时间与状态抖动，冻结可信产品面
  ↓
Severity/V4：尝试从“会不会变坏”升级到“未来冲击有多大、何时穿越阈值”
  ↓
E15：保留最有行动价值的五日首次越界问题，重建可校准、可拒绝的发生概率
  ↓
当前：V3 仍是产品；E15 仅处于 design-only，等待新增 PIT 传感器与独立证据
```

截至本说明：

- 当前产品是 `MATVIX_CBOE_CORE_V3`，release tag 为 `matvix-v3.0.1`；Feature、State、
  Probability 与 daily Schema 的科学版本均为 `3.0.0`。
- V3 历史核心已通过七维站内验收，四个正式条件概率模型通过冻结历史门；Broad 只发布因果
  基准率，不冒充模型。
- V3 的历史策略适配器没有取得综合经济增量，未晋升；V3 本身仍是只读研究气象站。
- “V4”至今不是一个已发布的新产品版本，而是 Severity 研究过程中多个被严格限定的实验名称。
- Severity 预测证据由 `MATVIX_SEVERITY_FIRST_PASSAGE_MODERN_EVAL_001` 冻结。FP0 已证明
  期权价格区间和 Physical-P first-passage 面板可构造；随后冻结的 2016–2023 OOF 已完成，裁决为
  `FIRST_PASSAGE_CANDIDATES_NOT_SUPPORTED`。B1 的非期权结构模型和 C 的期权区间增量均未建立
  相对各自因果基线的增量。
- 后续 `MATVIX_SEVERITY_DECISION_VALUE_UPPER_BOUND_001` 把被拒绝的 economic-probe 四轴 AND
  gate 误称为 V3 permission。它只允许 161/1,258 个 origin，名义 25% cap 的全期平均暴露仅
  3.20%，因此不回答固定小仓位或普通 contango 小仓位的价值问题。旧字节仍是该 gate 内的有效
  条件诊断，但项目级 `FULL_SEVERITY_SCALE_NOT_JUSTIFIED_ON_CURRENT_EVIDENCE` 外推已撤回。
- `MATVIX_SEVERITY_DECISION_VALUE_BASELINE_SENSITIVITY_002` 随后分别测试连续 25% sleeve 与字面
  front-contango 25% sleeve。两者的增长最优神谕仍是 binary E15 veto；但分别有 27/35 与 4/35
  hindsight ordinal maps 优于同暴露 perfect-E15 对照，说明旧 0/35 结论依赖错误基准。预写
  `[1,.5,0,0]` 在两条路径都因 ES 略差而未通过严格 ordinal gate。当前状态是
  `SEVERITY_DECISION_VALUE_INCONCLUSIVE_PENDING_INDEPENDENT_EVIDENCE`，不是 Severity restart。
- `MATVIX_SEVERITY_DECISION_VALUE_BOUNDED_BIDIRECTIONAL_003` 随后补齐 SVXY/VIXY/BIL 三袖账户：
  期限结构只决定方向，未来类别只决定获许可一侧的仓位。固定 backwardation VIXY 反而拖累；
  固定加仓与固定 long map 都没有通过严格风险门。事后同暴露 binary-E15 对照在两条腿上机械
  material，但 long 侧 ES 仅以 0.000241pp 越过容忍线。E15-vs-E30+ 固定 map 相对 full-binary
  增加 1.264pp 年化对数收益，却在移除 2020-02-13 至 2020-03-20 episode 后失去 materiality；
  E30 与 E60 动作相同，不能识别 E60 增量。正式状态是
  `BIDIRECTIONAL_FIXED_ACTION_CAPACITY_NOT_ESTABLISHED`；解释状态只能是
  `BINARY_E15_ACTION_VALUE_PRESENT_E15_VS_E30PLUS_INCREMENT_CRISIS_CONCENTRATED_POST_RESULT`。
  这是期限结构硬门内固定动作的后见诊断，不是优化上界、模型或交易授权。
- V4 的 runner、合同、测试和报告已隔离到 `codex/v4-severity-reset-audit`；E15 checkout 只保留
  结论摘要与 active brief，不再依赖旧执行路径。V3 runtime 最近可验证的 accepted snapshot 是
  `2026-08-26`；既有 Prospective gap 永久保留，目前 Core prediction/outcome 文件均为 0。
- E15 当前状态为 `DESIGN_ONLY / NOT_FROZEN / NOT_EXECUTED`；没有拟合、历史候选选择、产品接入
  或交易授权。
- 全项目没有交易权限。任何天气状态、概率、Severity 区间或历史经济探针都不能直接变成仓位。

## 2. 接手团队必须先理解的边界

### 2.1 气象站不是策略

项目按以下层次分离：

```text
官方市场数据
→ 当前天气事实与状态
→ 未来天气事件概率或 Severity 分布
→ 外部策略如何使用天气
→ 仓位、执行、成本与 P&L
```

V3 覆盖前三层中的“当前状态”和部分“事件概率”。Severity 研究尝试补齐冲击幅度。仓位、订单、
执行和交易仍在项目权限之外。历史 SVXY/SGOV/VXZ probe 只检验一个冻结映射，不能倒过来修天气
定义。

### 2.2 `P` 与 `Q` 不是同一个概率

- `P`：真实世界未来路径的发生概率，例如未来五个收盘中 VIX 是否上涨 30%。
- `Q`：期权价格隐含的风险中性终点状态价格，混合了真实预期与风险偏好。
- European VIX option 只对应 VRO/SOQ 终点，不直接识别五日内任意一天是否穿越阈值。

因此，期权信息最多是预测 Physical-P 的一个有界输入；不得把 RND 尾概率直接标成真实世界
路径概率。

### 2.3 状态、概率、严重度与经济结果是四种证据

- 状态验收回答：当天数据和天气分类是否完整、可重放、无未来函数。
- 概率验收回答：某个明确事件的概率是否优于因果历史基准并得到合理校准。
- Severity 验收回答：能否区分普通波动、强风暴和极端冲击的完整幅度或分布。
- 经济探针回答：一个固定天气到资产的映射在一段历史上发生了什么。

任何一层通过都不能自动替代下一层。

### 2.4 “V4”命名不能按产品版本理解

仓库历史中出现过 `Legacy V4`、`V4 audit reset`、`P/Q decomposition` 和当前 first-passage
路线。它们都是 V3 之外的 Severity 研究对象，并不表示 V3 已被一个统一的 V4 产品替换。

## 3. 系统总架构

### 3.1 输入与决策时钟

V3 使用：

- Cboe VIX OHLC、VIX9D、VIX3M、VIX6M、VVIX、SKEW、SPX；
- CFE 标准月 VX F1–F7 settlement；
- 本地 hash-bound vendor baseline 与追加的官方 live generation。

产品是日终批处理：origin session 的 EOD 数据，最早用于下一 XNYS session `09:20 ET` 的研究
判断。历史输入标记为 `ASSUMED_PIT`，即有保守 availability 规则和追加不变性证据，但没有
receipt-time 历史供应链证明。

### 3.2 数据流

```text
官方/授权原始字节
→ normalized revision ledgers
→ PIT 选择与完整交易日面板
→ Features
→ 五个 axis scores + 三个直接结构状态
→ raw phase + hysteresis 后 published phase
→ event targets + rolling-origin OOF + causal BaseRate
→ accepted daily JSON + receipt
→ Dashboard /api/snapshot /api/status
→ 独立 Prospective prediction/outcome ledger
```

关键实现入口：

- Feature：[`../src/matvix/features/`](../src/matvix/features/)
- State：[`../src/matvix/state/`](../src/matvix/state/)
- Probability：[`../src/matvix/probability/`](../src/matvix/probability/)
- Pipeline：[`../src/matvix/pipeline.py`](../src/matvix/pipeline.py)
- Publication/runtime：[`../src/matvix/daily_update.py`](../src/matvix/daily_update.py)、
  [`../src/matvix/http_runtime.py`](../src/matvix/http_runtime.py)
- Frozen configs：[`../configs/features_v3.yaml`](../configs/features_v3.yaml)、
  [`../configs/state_v3.yaml`](../configs/state_v3.yaml)、
  [`../configs/probability_v3.yaml`](../configs/probability_v3.yaml)
- Machine contract：[`../schemas/daily_output.schema.json`](../schemas/daily_output.schema.json)

### 3.3 数据诚实原则

- 缺失、不可观测或迟到值保持 `UNKNOWN/PARTIAL`，不前填为正常。
- 所有模型训练只读取 prediction date 之前已经 outcome-available 的样本。
- 五日/十日标签有 20-session purge，避免重叠结果泄漏进训练。
- 失败模型回退为同日因果 BaseRate；回退不计作模型增量。
- snapshot 只有在数据、Schema、概率和 receipt 门通过后才能替换 last-good。

## 4. V1：先做出一个真正的天气仪表盘

### 4.1 最初要解决的问题

V1 的出发点不是预测收益，而是把分散的 VIX 保险市场信息统一成一个可解释、可每日重放的状态
引擎。它第一次把以下对象连成闭环：

- 官方 VIX/CFE/SPX 数据与 point-in-time 选择；
- 五个 0–100 天气轴；
- 一个确定性 market phase；
- 事件特定的历史基准率、rolling-origin OOF 模型与校准；
- versioned daily JSON、Dashboard、接受回执与 last-good runtime。

### 4.2 V1 的五个轴

| 轴 | 交易员问题 | 主要信息 |
|---|---|---|
| Carry Risk | 卖波动率所依赖的期限结构是否正在受损？ | VX 前端斜率、30 日 VX–VIX 基差及五日变化 |
| Shock | 短端保险是否快速重定价？ | VIX9D/VIX、VIX 与 VVIX 的日/五日速度 |
| Tail Price | 尾部保护是否相对昂贵？ | SKEW 水平与变化 |
| Persistence | 压力是否从前端扩散并持续？ | 当时主要依赖 IV forward 与 F1–F6 breadth 的混合表示 |
| Repair | 高压后是否出现同步缓和？ | VIX、近端压力、曲线、VVIX 的五日变化 |

V1 的四个事件问题是：

- `acute_front_stress_5d`；
- `front_inversion_5d`；
- `broad_persistent_stress_20d`；
- `fast_repair_5d`。

固定 Logistic 至少需要 252 个已成熟训练样本、正负各 30、20-session purge；发布前再接受
顺序 Platt 校准和最新 252 OOF 的 Brier Skill/ECE 门。

### 4.3 V1 做对了什么

2026-08-22 的独立业务审计没有发现 V1 在 PIT 选择、三值 UNKNOWN、目标删失、purge、
rolling-origin OOF 或追加不变性上伪造结果。V1 已经是一个合格的软件与因果数据骨架。

### 4.4 V1 为什么仍需要 V2

审计确认五类业务缺陷：

1. `DATA-001`：严格 30 日 `VXCM30` 在 F1 本身已超过 30 天时失去左夹逼锚，162 个直接缺口
   进一步污染五日变化。
2. `TENOR-001`：没有直接发布 F4–F7 level、slope、breadth 和变化，Persistence 名称无法说明
   压力到底局限前端、正在扩散、已经计价还是正在衰减。
3. `STATE-001`：Persistence、phase 和 Repair 混合了不同阶段；边际修复容易被误解为 Carry
   已经重新开放。
4. `TIMING-001`：与原始事件簇相比，中期扩散、衰减和 Carry 恢复有较多漏报、误报或延迟。
5. `PROBABILITY-001`：概率流水线正确，但 broad/repair 的标签没有直接回答新的期限结构问题，
   且部分模型没有可发布增量。

关键认识是：V1 的缺陷主要不是“模型不够复杂”，而是传感器连续性和业务问题定义不够精确。

## 5. V2：把天气事实和状态语义校正

### 5.1 V2 的设计原则

V2 先业务审计、再按 defect 修复、再做站内验收，最后才允许读取产品价格。天气定义不能根据
SVXY/VXZ 收益调整。

### 5.2 V2 的主要修复

#### 数据连续性

- VX 曲线扩展到 F1–F7；
- 只有在 `30 < D1 <= 36`、F1/F2 连续且正式可用时，允许有界同曲线后向线性估计 VXCM30；
- 每个值区分 `DIRECT_BRACKET_INTERPOLATION`、bounded reconstruction 和 unavailable；
- 不把重建值伪装成官方直接 observation。

#### 期限结构事实

增加直接可解释的：

- `f4_f7_level`；
- `f4_f7_slope30`；
- `f4_f7_inversion_share`；
- 五日/十日 level、slope、breadth 变化；
- `front_to_mid_log_ratio`。

#### 状态语义

新增三个直接结构状态：

- `stress_tenor_scope = NONE | FRONT | MID | BROAD | UNKNOWN`；
- `mid_curve_pressure_state = QUIET | RISING | PRICED | RECEDING | UNKNOWN`；
- `carry_environment_state = OPEN | RECOVERING | CLOSED | UNKNOWN`。

Repair 被明确限制为“压力正在边际衰减”，不再等同于 Carry OPEN。

#### 概率目录

V2 形成了五个更直接的问题：Acute、Front inversion、Mid-curve acceleration、Broad
persistence 和 Carry recovery。缺少样本或 Skill/ECE 不通过时必须发布 BaseRate。

### 5.3 V2 的结果

站内 DATA、TENOR、STATE/TIMING、PROBABILITY INTEGRITY 均通过；但 Probability Model 总门失败：

- Acute、Front、Mid-curve acceleration 通过；
- Broad 只有 191 个可验证 calibrated OOF，证据不足；
- Carry recovery Brier Skill `-6.67%`、ECE `21.73%`，失败。

冻结经济探针中，V2 相对 V1 的 Long 和 Combined 有改善，但 Short 为 `MIXED`；Combined 虽相对
V1 改善，绝对终值仍低于初始资金。最终裁决为：

```text
NOT_READY
NO_COMPREHENSIVE_INCREMENT
NO_PROMOTION
```

V2 没有作为独立 ready 产品晋升，但它修复的数据、期限事实和状态语义成为 V3 的基础。

## 6. V3：把“可解释状态”升级为“可发布的精选概率”

### 6.1 V3 不是全面重写

V3 保留 V2 已通过的数据、期限结构和状态骨架，只处理仍然阻断气象站的概率与稳定性缺陷：

- 概率校准可能因自由 Platt slope 发生形状反转；
- Carry 恢复概率没有表达一次关闭已经持续多久；
- Broad direct 10D 模型没有稳定增量；
- calm-carry fragility 候选可能有业务价值，但正式样本不足；
- risk-on phase 之间有不必要的单日抖动。

### 6.2 V3 的逐步裁决

#### 第一步：统一概率语义与单调校准

V3 保留固定 Logistic，但用 causal BaseRate 和 slope 固定为 1 的 rolling intercept 校准替换自由
Platt slope。这样校准只修正发生率，不允许把原模型排序翻转。

#### 第二步：关闭 Broad 条件模型

Broad direct-10D 的四种固定诊断都没有达到 2% Brier Skill 门。V3 没有继续换模型，而是把它
冻结为 `BASE_RATE_ONLY_EXEMPT`：它提供同类历史发生率，但明确没有 feature-conditioned 增量。

#### 第三步：Carry duration 候选先失败，再做唯一受控修复

第一版 Carry duration 模型有 `+34.6690%` Brier Skill，但 ECE `7.4132%` 超过 7% 门，仍判 FAIL。
结果后诊断发现线性增长的 spell age 在长关闭期产生饱和问题。合同只授权一次替换：

```text
bounded_log1p_carry_spell_age, cap = 20 sessions
```

不扫描 cap、不改门、不读产品价格。唯一重建得到 Brier Skill `36.1709%`、ECE `5.0964%`，通过，
但证据等级仍是 `HISTORICAL_RESEARCH_SUPPORT`。

#### 第四步：Fragility 被正式拒绝

`calm_carry_breaks_5d` 候选只有 114 条 completed published OOF，未达到冻结的 252 门。正负类数量
足够不能替代总样本门。它被移出正式事件、Schema、Dashboard 和 runtime；候选数值只保留为
`UNQUALIFIED_RESEARCH_SCORE` 的审计证据。

#### 第五步：减少 risk-on 微抖动

V3 只对三类 risk-on 转移增加连续三日确认；risk-off 和 acute 进入不延迟。最终验收确认没有非法
转移或 risk-off 延迟。

### 6.3 V3 冻结产品面

正式 event 目录：

| event | horizon | 发布类型 | 历史 252 OOF 验收 |
|---|---:|---|---|
| `acute_front_stress_5d` | 5 | Feature-conditional | Skill `7.1313%`，ECE `3.1736%`，PASS |
| `front_inversion_5d` | 5 | Feature-conditional | Skill `10.7097%`，ECE `3.0033%`，PASS |
| `mid_curve_pressure_accelerates_5d` | 5 | Feature-conditional | Skill `11.7853%`，ECE `5.0768%`，PASS |
| `broad_stress_persists_10d` | 10 | Causal BaseRate only | Reference PASS；无模型 PASS 主张 |
| `carry_environment_recovers_10d` | 10 | Feature-conditional | Skill `36.1709%`，ECE `5.0964%`，PASS |

四个条件模型的发布门都是最新 252 个成熟 OOF、正负各至少 20、Brier Skill `>=2%`、ECE `<=7%`。
失去资格时 daily product 回退 causal BaseRate；OOF ledger 仍保存 candidate，便于区分模型与发布
policy。

### 6.4 V3 七维验收

历史 Stage D 独立要求：

```text
DATA=PASS
TENOR=PASS
STATE_TIMING=PASS
PROBABILITY_INTEGRITY=PASS
PROBABILITY_MODEL=PASS
BASE_RATE_REFERENCE=PASS
FRAGILITY_BOUNDARY=PASS
```

这证明 V3 历史核心内部完整、一致且可重建，不证明 prospective 稳定，也不证明某个交易策略盈利。

### 6.5 V3 历史经济探针为什么没有晋升

唯一冻结 adapter 用不合格 Fragility shadow 只允许 `SVXY → SGOV` 减仓。797 个 signal sessions 上：

- Short 的净值和 MaxDD 有改善；
- Long 完全不变；
- Combined 的 MaxDD 从 `-20.9681%` 变为 `-21.7004%`，失败；
- 43 个 veto 没有命中最差 20 个 SVXY session；
- 净改善主要来自减少切换成本，不是提前识别极端风险。

因此：

```text
ECONOMIC_VERDICT=NO_COMPREHENSIVE_INCREMENT
ADAPTER-002=REJECTED_BY_FROZEN_HISTORICAL_PROBE
PRODUCTION_PROMOTION=FALSE
```

该失败只拒绝 adapter，不推翻 V3 天气站的状态与概率验收。

### 6.6 V3 发布身份

- Product/model id：`MATVIX_CBOE_CORE_V3`
- Python package：`3.0.1`
- Scientific surface：Feature/State/Probability/Schema `3.0.0`
- Release tag：`matvix-v3.0.1`
- Final freeze tag：`matvix-v3-final-freeze-2026-08-24`
- Product mode：`READ_ONLY_RESEARCH_WEATHER_STATION`
- Historical core：`ACCEPTED`
- Prospective confirmation：`PENDING`
- Trading authority：`NONE`

完整 identity 见 [`../MATVIX_V3_RELEASE_MANIFEST.json`](../MATVIX_V3_RELEASE_MANIFEST.json)。

## 7. 交易员通过 V3 能看到什么

### 7.1 先看数据是否可用

`data_status` 是第一道门：

- `OK`：必需事实完整，可以读取天气判断；
- `PARTIAL`：部分轴或状态不完整，不能把缺失当作正常；
- 其他 blocked/unknown 状态：保留 last-good，不形成完整新判断。

同时读取 `session_date`、`decision_as_of`、版本和 `input_manifest_hash`，确认这是哪个交易日、哪个
模型、用哪批输入生成的事实。

### 7.2 五个核心天气轴

| V3 轴 | 实际回答 | 典型交易员解读 |
|---|---|---|
| `carry_risk` | 前端斜率、VXCM30–VIX 基差和变化是否支持 Carry | Carry 结构是否健康，而不是“今天能否做空 VIX” |
| `shock` | VIX9D/VIX、VIX/VVIX 是否快速升温 | 短端保险是否出现急性抢购 |
| `tail_price` | SKEW 尾部定价处于自身历史什么位置 | 尾部保护相对中心是否偏贵 |
| `persistence` | F4–F7 是否上升、倒挂并向远期扩散 | 压力是短暂前端冲击还是中期持续天气 |
| `repair` | 高压后是否出现同步边际衰减 | 正在修复；不等于 Carry 已经重新开放 |

每轴给出 0–100 score、原始值、历史 percentile、component contributions、drivers 和
counter-evidence。交易员可以看到结论由什么推动、又被什么反驳，而不是只得到一个红绿灯。

### 7.3 三个结构字段

- `stress_tenor_scope`：`NONE/FRONT/MID/BROAD/UNKNOWN`；
- `mid_curve_pressure_state`：`QUIET/RISING/PRICED/RECEDING/UNKNOWN`；
- `carry_environment_state`：`OPEN/RECOVERING/CLOSED/UNKNOWN`。

这三个字段直接回答“压力在哪里”“中期压力处于什么阶段”“Carry 环境是否开放”。

### 7.4 发布 phase

phase 是五轴与结构状态经过有限滞回后的统一天气标签：

- `ACUTE_FRONT_STRESS`；
- `FRONT_LOCALIZED_STRESS`；
- `PRESSURE_DIFFUSING`；
- `BROAD_PERSISTENT_STRESS`；
- `REPAIR_IN_PROGRESS`；
- `TAIL_RICH_QUIET_CURVE`；
- `CARRY_SUPPORTIVE_LOW_STRESS`；
- `MIXED_TRANSITION`；
- `UNKNOWN`。

Dashboard 同时解释 `headline`、完整 narrative、`what_changes_the_view`、主要 drivers、反向证据和
修复证据。

### 7.5 概率字段

每个适用事件给出：

- `event_status` 与 `model_status`；
- `probability_kind`：条件模型还是历史参考；
- `raw_probability`、校准后 `probability`；
- 同日 `base_rate` 与 `uplift`；
- 校准样本/正负数量和方法；
- `valid_through_session`；
- 交易员可读 interpretation。

必须先看 `model_status`。`CALIBRATED_MODEL` 是当前合格条件模型；`BASE_RATE_ONLY` 只是历史参考；
`NOT_RUN/NOT_APPLICABLE/INSUFFICIENT_HISTORY` 都不能被读成零风险。

### 7.6 一个真实 point-in-time 示例

当前本地最新 accepted snapshot `2026-08-26` 展示了数据格式，而不是交易建议：

- `data_status=OK`；
- phase=`MIXED_TRANSITION`；
- Carry=`SUPPORTIVE`，Shock=`CALM`，Tail=`NORMAL`，Persistence=`NORMAL`，Repair=`INACTIVE`；
- structure=`NONE / QUIET / OPEN`；
- Acute 5D `9.2%`，其 causal BaseRate `12.9%`；
- Front inversion 5D `3.3%`，BaseRate `9.4%`；
- Mid-curve acceleration 5D `51.2%`，BaseRate `45.6%`；
- Broad 与 Carry recovery 因当前状态不适用而 `NOT_RUN`，不是 0%。

机器消费者应读取 accepted JSON `/api/snapshot`，不得从 narrative 文本解析交易信号。

## 8. V3 的缺陷和局限

### 8.1 它主要回答状态转移，不回答完整冲击幅度

V3 可以说“前端急性压力未来五日的概率”“中期压力是否加速”，但不能稳定回答未来五日 VIX 最大
上涨是 10%、30% 还是 60%，也不给出完整路径分布。这是 Severity/V4 研究启动的根本原因。

### 8.2 它是日终产品，不是盘中预警器

V3 用上一交易日 EOD 信息，在下一 session 09:20 ET 后形成正式判断。盘中 VIX 快速跳升、报价
深度变化和实时 dealer positioning 不在当前输入面。

### 8.3 历史 PIT 仍是研究代理

历史数据通过 availability、revision 与 append-invariance 检查，但没有 receipt timestamp、sequence
和完整 GAP ledger。因此不能把 `ASSUMED_PIT` 写成正式实时历史可得性证明。

### 8.4 Broad 没有条件模型

`broad_stress_persists_10d` 只发布因果 BaseRate。它保留业务问题和历史参照，但不能说明今天的
特征使 Broad persistence 高于或低于同类历史。

### 8.5 Fragility 没有获得模型资格

`calm_carry_breaks_5d` 只有 114/252 published OOF，正式拒绝保持有效。历史 adapter 也未在极端
SVXY 日前提供增量。不得把 shadow score 恢复进产品、Schema 或策略。

### 8.6 历史验收不等于独立前向确认

四个模型在冻结历史 OOF 上通过，但模型开发和历史检验共享有限市场历史。Prospective Core 必须
依靠 activation 后的自然 prediction/outcome；旧 session 不能回填。

### 8.7 Prospective 功效很慢

重叠 5/10 日标签和事件簇意味着日行不是独立考试。既有 power design 估计：达到最低完整性门通常
需要约 4–6 年；真实 Skill 若只有 2%，要获得 80% power 甚至可能需要数十年至数百年。合理的正式
结论允许 `INCONCLUSIVE`，不能为了及时得到绿灯而降低门槛。

### 8.8 它不包含可执行期权经济

V3 使用指数与期货结算事实，但没有正式 option bid/ask/size、receipt-time、冲击成本、容量、Greeks
或订单生命周期。概率正确也不等于某个期权组合可交易。

### 8.9 数据与制度会漂移

主要历史从 2013 年开始，VIX 产品、交易参与者和宏观环境会变化。V3 使用 rolling BaseRate、OOF
和当前资格回退减轻漂移，但不能保证历史关系永久稳定。

## 9. 为什么从 V3 走向 Severity/V4

V3 的主问题是 occurrence/transition：天气会不会从当前状态转成另一状态。交易员进一步需要知道：

> 如果风暴真的发生，是普通大风、强风暴还是极端台风？在五天中的第几天首次穿越危险阈值？

Severity 因此把核心目标定义为：

```text
Y_t = max_{k=1..5} log(VIX_close[t+k] / VIX_close[t])
```

并使用固定物理阈值 `15% / 30% / 60%`。早期研究只在 Acute origin 上考察冲击幅度；后续为避免
条件样本过少和对象漂移，改成全 session 的完整四等级分布与 first-passage 面板。

Severity 始终与 V3 隔离：失败不能修改 V3，成功前也不能交给策略、仓位或 SmatVIX。

## 10. Severity/V4 如何一步步走到现在

### 10.1 第一轮：压缩天气轴的连续幅度回归

| 实验 | 表示/模型 | Full MSE Skill | Full Spearman | 裁决 |
|---|---|---:|---:|---|
| Challenger 001 | 六个压缩天气轴 / Ridge | `-0.036883` | `0.327032` | 整体未胜基线，后半段有部分排序信息 |
| Challenger 002 | 同一表示 / shallow HGB | `-0.151490` | `0.225347` | 换一个浅非线性模型不能修表示 |
| Legacy V4 | 十个 raw weather features / scaled Ridge | `-0.471461` | `0.223710` | 稳定幅度预测未建立 |

冻结 OOF 有 1,861 个 prediction dates、242 个 realized severity rows，但只有 39 个独立事件簇。
Challenger 001 后半段一度较好，说明可能存在 regime-specific 排序信息；它不足以支持稳定全期模型。

### 10.2 第二轮：Distributional P0 与单一 Q80

研究尝试从均值回归转向完整分布/尾部分位数，但 no-fit power sensitivity 显示在当时冻结假设下
样本需求极长；随后 all-origin Q80 preflight 把对象压成一个上行幅度上限。

这些结果只说明特定设计不经济，不证明 Severity 不可建模。Q80 对风险上限有用，却不能回答四级
风暴分布，因此后来被降为 sidecar，而不是主线目标。

### 10.3 第三轮：Reset V4 四等级 OOF

Reset audit 在 3,331 个全 session 五日 outcome 上冻结四个候选：cumulative logistic 与 shallow
HGB，各自使用 expanding 或 trailing-756 memory。主指标为相对因果类别气候基线的 RPS Skill。

四个候选在 Full 和 2023–2025 窗口都没有胜出。最好的 expanding HGB：

- Full RPS Skill `-0.0188`，95% moving-block interval `[-0.0356,-0.0025]`；
- recent Skill `-0.0149`，interval `[-0.0385,0.0010]`。

这关闭了“现有十个 weather fields + 两类模型 + 两种 memory”这一组主张，不是信息论上证明所有
Severity 都不可能。

### 10.4 第四轮：Aggregate P/Q decomposition

为寻找更物理的机制，研究把 `VIX²` 分成 Physical variance forecast 与 aggregate residual。
数据 P0 通过，但固定 HAR-RV 的 2023–2025 QLIKE Skill 为 `-0.0042`，区间很宽；最终 P/Q Severity
候选 Full RPS Skill `-0.0050`、recent `0.0027`，均不能稳定胜基线，裁决为
`SEVERITY_PQ_NOT_SUPPORTED`。

它拒绝的是 `SPY-RV/HAR + aggregate VIX²−P` 这一个构造，不是所有期权信息。

### 10.5 第五轮：直接 VIX option RND

研究转向更接近目标阈值的 VIX option surface。

#### P0 数据与目标对齐

- 自主取得并解析 2016–2023 的 96 个 OptionsDX VIX EOD 月文件，共约 312 MB、1,790,480 行；
- 与官方 Cboe 2023-08-25 sample 做 1,438/1,438 contract-key 交叉核对；
- 1,893/2,012 origin 找到目标第五日之后 1–10 XNYS session 内的合格 VRO maturity；
- verdict=`P0_DATA_TARGET_ALIGNMENT_SUFFICIENT`；
- 无 RND、无 target join、无模型。

#### P1 RND construction

- 用 paired call/put parity 估计 discount/forward；
- 把 call mid 和 parity-transformed put mid 投影为非负、单调、凸的 call curve；
- 由离散 slope change 构造 terminal Q mass，有限 strike 边界质量保持显式；
- 1,893/1,893 primary surface 构造成功；
- verdict=`P1_RND_CONSTRUCTION_SUPPORTED`；
- 仍未读取 Severity outcome。

#### P2 第一次目标关联

冻结后才计算三项 tail：

```text
q15, q30, q60 = Q_t(VIX_T >= VIX_t × exp(0.15/0.30/0.60))
```

1,876 个有效关联得到 macro AUC `0.537653`，但 95% block interval
`[0.457277,0.612052]` 跨 0.5；E60 只有 13 个正 origin。裁决为
`P2_TARGET_ASSOCIATION_NOT_SUPPORTED`，冻结的 P3 从未拟合。

### 10.6 第六轮：不把 P2 失败归因于分类器，而是找根因

结果后 no-fit 诊断建立了六条边界：

1. quote-consistent tail 不是点识别；
2. terminal Q marginal 不是五日 path maximum；
3. 对齐 exact VRO/SOQ 没有救回排序；
4. Q-to-P rank mapping 在年份间反转；
5. E60 的 13 行只有 5 个独立 shock episodes；
6. variable maturity 是混杂项，没有形成救援 cohort。

最关键的数量级：

| tail | point median | interval median | width/point |
|---|---:|---:|---:|
| q15 | `0.1848` | `[0.0932,0.3022]` | `1.07×` |
| q30 | `0.0766` | `[0.0294,0.1476]` | `1.47×` |
| q60 | `0.0144` | `[0.0020,0.0383]` | `2.24×` |

直接把 mid tail 当作精确概率，会把报价宽度和有限 strike support 伪装成信息。这个诊断决定了
下一路线必须使用区间和 first-passage，而不是再换一个分类器。

### 10.7 第七轮：Physical first-passage FP0

当前 frozen FP0 只做数据、partial identification 和目标面板审计：

- `M0` 最近合格 maturity：1,893 个 origin，1,876 个有完整三阈值 bounds；
- `M1` 第二近 maturity：1,792 个 origin，1,772 个有完整 bounds；
- 六个 maturity/threshold point feature 全部 `POINT_REJECTED`；
- bounds 仍是合法测量，不能叫 Physical-P；
- 2,012/2,012 个五日路径完整，calendar/category/first-crossing/at-risk 违规均为 0；
- E15/E30/E60 为 407/136/13 个正 origin，对应 85/39/5 个重叠窗口 episode；
- model fits、OOF predictions、forecasts 全部为 0。

终局：

```text
FP0_BOUND_AND_PANEL_SUPPORTED
```

这只证明下一项实验需要的输入与考卷可以诚实构造。它没有证明期权 bounds 有预测增量，也没有
授权第一 fit。

### 10.8 第八轮：2016–2023 modern first-passage 冻结 OOF

治理审计先移除了不属于本次科学问题的前置门：2010–2015 公开期权源没有进入 primary cohort、
训练、通过门或救援路径；持续追加的整份 `states.parquet` 也没有被错误地按旧文件字节冻结，合同
只绑定 2016–2023 所需列的 canonical logical projection。

冻结合同随后完成 6,209 次因果滚动拟合，生成 2,489 条 cohort-origin OOF 记录（1,258 个唯一
origin 日期）：PHYSICAL 为 1,258/1,258，OPTION_COMMON 为 1,231/1,258（97.85%）。训练只使用
`target_end_session < origin_date` 的 526–756 个成熟 origin，时钟违规、重复 key、非有限 loss
和概率约束违规均为 0。同一运行第二次生成完全相同的 ledger SHA-256
`9c7510d43ae8fc616d92338c9c94345dbeb886c070adb2641ba2640f810eaedf`。

冻结结果：

| 比较 | FP IBS Skill | 95% paired interval | day-5 category RPS Skill |
|---|---:|---:|---:|
| PHYSICAL B1 > B0 | `-0.022223` | `[-0.045123, 0.001302]` | `-0.031326` |
| COMMON C > B1 | `-0.019639` | `[-0.037927, -0.005061]` | `-0.027737` |
| COMMON C > B0 | `-0.036686` | `[-0.067711, -0.007158]` | `-0.052036` |

裁决为：

```text
FIRST_PASSAGE_CANDIDATES_NOT_SUPPORTED
```

B1 与 C 的损失都集中在更常见的 E15/E30；E60 单元虽略有改善，但评分期只有 7 个正 origin、
3 个重叠窗口 episode，不能支撑整体 Severity。B1 在两个固定时期均为负、五年中四年为负；C
相对 B1 在两个时期和五个年度全部为负，且五个非空 interval-width/maturity-gap 分层全部为负。
部分模型系数呈现 contango/backwardation 的直觉方向，C 的 aggregate calibration 也有局部改善，
但在本合同的 pooled-hazard 映射和 paired OOF proper score 下没有转化成稳定增量。结果排除了
“缺少 2010–2015 数据”或“单一年份拖累”作为本次失败解释，但不能区分变量本身没有额外信息，
还是这一个冻结映射没有提取出信息。

## 11. 当前真实状态

### 11.1 产品状态

- V3 仍是唯一 current product surface。
- 本地 `runtime-status` 最近显示 `last_good_session=2026-08-26`，该 session 所有核心 Cboe/CFE
  source 在当次运行中为 `FRESH`，snapshot 和 receipt 已发布。
- 这只是 2026-08-28 检查到的最近本地证据，不是对当前交易日实时 freshness 的持续认证。

### 11.2 Prospective 状态

Prospective 001 的 writer、receipt binding、resolver、Dashboard 状态和 durability fault matrix
已经通过 P1–P5，并创建 activation tag。

但当前实际 Core 证据为：

```text
predictions = 0
outcomes = 0
2026-08-21/24/25/26 receipts = EVIDENCE_CAPTURE_GAP
capture_error = TRACKED_WORKTREE_DIRTY
```

这些 gap 按合同永久不可回填。原因不是行情或模型失败，而是 activation 后在同一 checkout 进行
Severity 研究，tracked worktree dirty，recorder 按设计拒绝把不清洁代码身份写成正式 prospective
prediction。

### 11.3 Git/工作树状态

研究线已经按职责拆开：

```text
E15 active branch = codex/e15-actionable-occurrence
E15 base          = main@b084151ee84ced81b24a2a1975b8143c43ec1224
V4 evidence branch = codex/v4-severity-reset-audit
V4 closure commit  = 59c5df623c1aa9e7d43316bc5aa3f148658fca72
```

V4 分支保留完整历史 runner、focused tests、合同和小型报告；E15 分支不再包含或链接这些可执行
路径。历史 raw/derived 数据已从 E15 checkout 清理；这些字节不是 E15 输入，也不构成当前研究
权威。

工作树状态仍应在每次执行前实时读取，不能把本节当作持续 freshness 证明。与本次拆分无关的
V3/Prospective 用户改动不得被 reset、clean 或顺手并入 E15 提交。

### 11.4 Active research authority

当前研究方向只由
[`research/e15-actionable-occurrence-research.md`](research/e15-actionable-occurrence-research.md)
约束。它是 `DESIGN_ONLY / NOT_FROZEN / NOT_EXECUTED`，不是 V4 的延续执行授权。

V4 分支冻结的 2016–2023 modern-cohort B0/B1/C 历史 OOF 已执行完毕，裁决为
`FIRST_PASSAGE_CANDIDATES_NOT_SUPPORTED`。2010–2015 旧制度期权源没有进入 primary cohort、
训练、通过门或施工前置条件，也不是解释负结果所需的缺口。授权止于研究 OOF；本结果不支持把
B1/C 接入 V3、消费者、仓位或交易。

旧 upper-bound 001 与 baseline sensitivity 002 已降为 point-in-time 条件证据：001 gate 内
`SEVERITY_RESEARCH_OPTION_REMAINS`、`[1,0,0,0]=binary E15` 和 0/35 ordinal 结果仍保留，但它
不是 V3 仓位规则，也没有当前项目级架构权威。002 在连续 sleeve 和字面 contango sleeve 上
发现后见 map 增量，却没有让预写 ordinal action 通过严格 gate。003 的同暴露 binary-E15 对照
在事后机械门上 material，但固定加仓和固定 long map 仍未通过严格门；E15-vs-E30+ 增量集中于
2020 crisis，而且 E60 增量不可识别。这些是 E15 设计的历史约束，不是本分支的依赖文件。
当前没有拟合、消费者、仓位或交易授权；下一次候选必须同时有新 causal PIT 信息、预写行动和
真正独立的 OOF、未见 holdout 或 prospective 评价。

## 12. 给接手团队的审查顺序

### 第一步：保护现场

1. 记录 `git status --short --branch`、HEAD/main/origin/main 和所有 worktree；
2. 分别检查 E15 active branch 与 V4 evidence branch，不跨分支批量 stage；
3. 分别标记“冻结 V3 产品”“Prospective runtime”“V4 历史证据”“E15 active design”；
4. 对本地受限数据只记录 manifest/hash，不复制到 Git 或外部分发。

### 第二步：验证 V3 产品身份

按 [`../README.md`](../README.md) 与
[`../MATVIX_V3_RELEASE_MANIFEST.json`](../MATVIX_V3_RELEASE_MANIFEST.json) 验证：

- tag、config、Schema、requirements.lock；
- authorized vendor/live manifest；
- history/target/OOF/artifact contract；
- `accept-real` 与 `accept-v3-station`；
- latest accepted snapshot/receipt；
- Dashboard `/api/status` 与 `/api/snapshot`；
- `trading_authorized=false`。

### 第三步：独立审查历史结论

早期详细文档已从 current tree 清理，但仍可从 Git 读取：

```bash
git show f5c604b:MATVIX_V2_AUDIT.md      # V1 缺陷审计初态
git show a2a8a58:MATVIX_V2_AUDIT.md      # V2 最终裁决
git show 9888352:MATVIX_V3_AUDIT.md      # V3 详细施工与最终历史裁决
```

不要把历史文件恢复成第二套 active authority；Git history 已足够保存其证据角色。

### 第四步：分开审查 V4 证据与 E15 当前对象

V4 的精确 runner、tests、合同和报告只从冻结的本地分支读取：

```bash
git show --stat 59c5df623c1aa9e7d43316bc5aa3f148658fca72
git show 59c5df623c1aa9e7d43316bc5aa3f148658fca72:docs/archive/severity-2026-08.md
```

不要把这些文件复制回 E15。E15 只核对
[`research/e15-actionable-occurrence-research.md`](research/e15-actionable-occurrence-research.md)，
并检查其状态仍是 `DESIGN_ONLY / NOT_FROZEN / NOT_EXECUTED`。

### 第五步：审查已完成的 modern-cohort 评估

当前合同已冻结三种可归因比较：

```text
B0：纯 Physical-P 气候/历史路径基线
B1：不含期权的 Physical-P occurrence-severity / first-passage 模型
C ：B1 + M0/M1 option-bound geometry
```

只有 `C > B1` 才能说明期权 bounds 有增量；`B1 > B0` 但 `C ≯ B1` 才可能只说明
Physical-P 模型有用。真实结果是 B1 与 C 两项都没有通过：

```text
B1 > B0  FP IBS Skill = -0.022223
C  > B1  FP IBS Skill = -0.019639
verdict = FIRST_PASSAGE_CANDIDATES_NOT_SUPPORTED
```

完整预注册诊断保存在 V4 closure commit 的
`outputs/severity_first_passage_evaluation/report.md`。
这是真实统计负结果，不得通过同合同内换模型、阈值、cohort 或 gate 修理，也不得继续向仓位层
施工。若提出新的科学假设，必须先说明它提供了什么此前不存在的信息，而不是追加算法家族。

modern scored cohort 的 E60 只有 3 个重叠窗口 episode，不适合单独训练一个“极端分类器”。
后续若考虑 conditional continuous excess/path distribution，它只能是新的研究假设；MatSHIX 的
threshold-anchored occurrence-severity 结构或 ETF-P 结果也不能转移成 VIX option-Q 证据。

### 第六步：审查 perfect-information 上限与信息归因

旧 2019–2023 实验使用真实 SVXY/BIL adjusted-open 路径、25% cap、5 bp 单边成本和漂移后每日
再平衡，但在交易层先套用了被拒绝的 economic-probe 四轴 AND gate。该 gate 不是 V3 rule：它
只留下 161/1,258 个 origin，把 25% cap 变成 3.20% 平均暴露，并把完整 cohort 的 E15/E30/E60
交集从 249/80/7 压到 32/8/0。其 `[1,0,0,0]=binary E15`、0/35 ordinal map 和 gate 内 E60=0
仍是条件子样本事实，不能外推到固定 sleeve 或普通 contango sleeve。

修正后的 `POST_RESULT_BASELINE_SENSITIVITY` 不覆盖旧字节，也不冒充新 holdout。它并列计算：

```text
A：所有价格可执行 origin 每日恢复到 25% SVXY / 75% BIL
B：data_status=OK 且 front_slope30>0 时 25% SVXY，否则 BIL
```

主要结果为：

| baseline | eligible | base final / ann. log / MDD | fixed ordinal vs binary | hindsight ordinal maps |
|---|---:|---|---|---:|
| A continuous | 1,258 | $14,177.71 / 6.98% / -20.81% | +1.396 pp growth，ES -0.004 pp，FAIL | 27 / 35 |
| B front contango | 1,088 | $13,604.95 / 6.16% / -12.99% | +0.806 pp growth，ES -0.029 pp，FAIL | 4 / 35 |

两条路径的 growth-best map 都仍是 `[1,0,0,0]`，说明最大历史增长来自完美 E15 veto；但 A 的
`[1,1,.25,0]` 与 B 的 `[1,1,.5,0]` 等 hindsight map 能在同暴露 binary-E15 对照上通过同一
material hurdle，说明完整尺度的数学上限不是 0。不能把这些后见 map 当策略，也不能用 A/B NAV
选择“赢家”。正确项目状态是：

```text
UPPER_BOUND_001_POINT_IN_TIME_CONDITIONAL_DIAGNOSTIC
BUSINESS_EXTRAPOLATION_WITHDRAWN
SEVERITY_DECISION_VALUE_INCONCLUSIVE_PENDING_INDEPENDENT_EVIDENCE
```

随后执行的 `POST_RESULT_BOUNDED_BIDIRECTIONAL_CAPACITY` 不再把仓位限制为只能减仓。它冻结
VIXY 为唯一 long-vol 腿，使用 SVXY/VIXY/BIL 三袖账户和 50%/25% 上限；期限结构只决定方向，
完美未来类别只决定获许可一侧的仓位。固定链是：F0 双向固定、F1 只减 short、F2 在 E0 加
short、F3 在 backwardation 按 E15/E30/E60 增加 VIXY。

关键结果不能压成一句“通过/失败”：

| comparison | annual log delta | MDD delta | ES delta | 解释 |
|---|---:|---:|---:|---|
| F2 short-add vs F1 reduce-only | +20.461pp | -0.628pp | -0.526pp | 增长与 return/DD 大增，但严格风险非劣门失败 |
| F3 bidirectional vs F2 | +8.215pp | +3.325pp | +0.062pp | 同时改变 adverse long 与 135 个 backwardation-E0 动作，不能当作纯 long-add 效果 |
| F3 vs same-long-exposure constant | +7.665pp | +0.300pp | -0.071pp | ES 比固定容忍线多差 0.021pp，严格门失败 |
| binary short vs constant short | +28.352pp | +17.300pp | +0.623pp | 事后机械门 material；48/48 相关 episode、5/5 年度 mute 仍 material |
| binary long vs constant long | +7.206pp | +0.300pp | -0.0498pp | 机械门 material，但 ES 只以 0.000241pp 越线，阈值极敏感 |
| F3 E15-vs-E30+ long vs binary long | +0.459pp | 0.000pp | -0.022pp | long 腿尺度增量未建立 |
| F3 full E15-vs-E30+ vs full binary | +1.264pp | +0.909pp | -0.023pp | 51/52 相关 episode、4/5 年度 mute 通过；移除 COVID episode 后不再 material |

因此正式固定动作裁决仍是 `BIDIRECTIONAL_FIXED_ACTION_CAPACITY_NOT_ESTABLISHED`，但不能把它
误读成“所有加仓或 long-vol 都没有价值”，也不能倒过来宣称固定 add/long 已成立。更精确的解释是
`BINARY_E15_ACTION_VALUE_PRESENT_E15_VS_E30PLUS_INCREMENT_CRISIS_CONCENTRATED_POST_RESULT`：
主要事后容量来自知道 E0/E15 是否发生；E15-vs-E30+ 只有较小、危机集中的固定-map 增量。期限
结构硬门还排除了 65/80 个 E30+ 与 6/7 个 E60 contango origins 的 long 动作，所以这不是完整
双向动作空间或信息论上界。所有 NAV 都来自不可能的未来标签，不能当作可实现收益。

不要在同一历史上继续挑 map、cap、产品或算法。若要重启一次研究，问题应围绕真实可预测的
action-aware occurrence 信息，而不是追逐神谕式路径；仍必须有真正新增的 causal PIT 信息、
一个预先写明且会改变实际行动的候选，以及独立 OOF、未见 holdout 或 prospective 证据。

## 13. 明确不要重复的弯路

- 不要在相同十个 weather features 上无限追加模型家族；该固定对象已有负 OOF 证据。
- 不要把一个后半段较好的结果包装成全期稳定模型。
- 不要用 Q80、单一均值或仓位上限冒充完整 Severity。
- 不要把 terminal RND point tail 称为 five-day path probability。
- 不要因为 P1 curve construction 通过就跳过 target association 或 OOF skill。
- 不要把 13 个 E60 重叠 origin 当作 13 个独立极端事件。
- 不要用 Strategy P&L 调天气阈值或模型选择。
- 不要用 BaseRate fallback 的绿色 publication 掩盖 candidate model 失效。
- 不要回填 prospective gap，也不要在 dirty research checkout 上继续积累正式 Core 证据。
- 不要为假想消费者新增 API、adapter、schema 或 trading surface；V3 产品面必须保持冻结。

## 14. 关键文件导航

| 对象 | 文件 |
|---|---|
| 项目运行入口 | [`../README.md`](../README.md) |
| 仓库宪法 | [`../AGENTS.md`](../AGENTS.md) |
| 文档索引 | [`README.md`](README.md) |
| V3 release identity | [`../MATVIX_V3_RELEASE_MANIFEST.json`](../MATVIX_V3_RELEASE_MANIFEST.json) |
| V3 feature config | [`../configs/features_v3.yaml`](../configs/features_v3.yaml) |
| V3 state config | [`../configs/state_v3.yaml`](../configs/state_v3.yaml) |
| V3 probability config | [`../configs/probability_v3.yaml`](../configs/probability_v3.yaml) |
| Daily machine schema | [`../schemas/daily_output.schema.json`](../schemas/daily_output.schema.json) |
| Prospective protocol | [`../MATVIX_PROSPECTIVE_001_CONTRACT.md`](../MATVIX_PROSPECTIVE_001_CONTRACT.md) |
| Prospective acceptance | [`../MATVIX_PROSPECTIVE_001_ACCEPTANCE.md`](../MATVIX_PROSPECTIVE_001_ACCEPTANCE.md) |
| Active actionable E15 brief | [`research/e15-actionable-occurrence-research.md`](research/e15-actionable-occurrence-research.md) |
| Historical V4/Severity closure | branch `codex/v4-severity-reset-audit`, commit `59c5df623c1aa9e7d43316bc5aa3f148658fca72` |

## 15. 最终定位

MatVIX 已经完成的不是“一个能自动赚钱的 VIX 策略”，而是一个相对成熟的、可审计的日终市场
天气基础设施：数据、状态、概率、解释、发布、回退和 evidence capture 都有明确边界。

V3 的真正价值是：

- 把保险市场的 Carry、Shock、Tail、Persistence、Repair 放在一个一致的 causal clock 上；
- 让交易员看到当前压力的位置、阶段、反证和可能的状态转移；
- 对不合格模型诚实回退，而不是为了每天给信号制造确定性；
- 给下一代 E15 occurrence 研究提供稳定、隔离的产品基线。

V3 的核心不足也很清楚：它还不能稳定描述未来冲击的完整幅度与 first-passage 路径。Severity/V4
已经排除了多条看似合理但没有增量的路线。最新 modern-cohort OOF 进一步证明：即使移除
2010–2015 旧数据门、采用 target-native first-passage hazard，并只用 honest option price bounds，
冻结的 B1/C 候选仍未建立相对因果 climatology 的增量。

Perfect-label 工作进一步把“事后动作信息有价值”和“当前模型或行动可用”分开。单向 sensitivity
发现 binary E15 veto 与一些后见 map 的容量。三袖实验没有证明只减仓的系统必然不完整：固定
add 与固定 long map 均未通过严格风险门。它更窄地表明，同暴露 binary-E15 对照在事后机械门上
material，而 backwardation 本身不足以支持固定 VIXY 持仓；long 腿 E15-vs-E30+ 增量没有通过，
组合增量 1.264pp 又集中于 2020 crisis，E60 增量不可识别。故正式固定动作门是
`BIDIRECTIONAL_FIXED_ACTION_CAPACITY_NOT_ESTABLISHED`，较窄的解释是
`BINARY_E15_ACTION_VALUE_PRESENT_E15_VS_E30PLUS_INCREMENT_CRISIS_CONCENTRATED_POST_RESULT`。
两者都不是优化上界、模型或仓位许可证。

2026-08-28 的当前架构决定已经把完整 Severity scale 移出 active alpha roadmap；E30、E60、
conditional quantiles 和完整路径分布只保留为历史证据。唯一 active 的 post-V3 forecast object
是现有五日 E15 first passage 的校准 occurrence probability。天气对象仍覆盖所有有效 origin，
但主动作检验只在期限结构仍为 contango、short-vol 许可尚未撤销时进行；EOD prior 与 09:20 ET
overnight posterior 分开评分。详细边界见
[`research/e15-actionable-occurrence-research.md`](research/e15-actionable-occurrence-research.md)。

接手团队最重要的不是立刻再换模型或把天气结果接入仓位，而是先保护当前负证据、恢复 V3
runtime 与 research checkout 的身份隔离、确认不可回填的 prospective gaps。VIX 期现结构目前
仍可作为可解释的方向和状态信息；真正缺失的是可校准、可独立验证、足以改变有界加仓或减仓
动作的 E15 occurrence 信息。在出现明确的新 PIT 信息并通过冻结历史筛查和 prospective 评价
之前，任何事后上限都不能被升级为 alpha、仓位预算或交易权限。
