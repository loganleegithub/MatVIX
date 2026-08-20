# MatVIX 市场叙事与概率引擎开发规格

> 文档状态：IMPLEMENTED / REAL-DATA ACCEPTED
> 规格版本：1.1.0
> 决策日期：2026-08-20
> 产品频率：美国期权交易日日频，官方 EOD 口径
> 本文角色：MatVIX v1 的产品、实现与验收权威；代码和配置变更必须与本文同步

---

## 0. 开工结论

MatVIX 要构建的不是一个“猜涨跌”的预言机，而是一座读取 SPX/VIX 保险市场的量化气象站。每天必须完成两个核心任务：

1. **市场叙事**：解释当前保险市场的 carry、急性重定价、尾部定价、压力扩散与修复状态；
2. **概率判断**：给出未来 5/20 个交易日四类明确定义的状态转移概率，并与同类历史基准率比较。

项目接受以下业主前提：PDF 所述 Sober 系统事实上正在运行。MatVIX 不承担“证明它是否存在”的任务，也不把缺少私有源码当作项目障碍。

与此同时，PDF 没有公开私有公式、参数与组合权重。因此本项目交付的是一套**透明、可复现、可校准的 MatVIX v1 基线**，不是对 Sober 私有算法的冒充。Sober 的产品思想是方向来源；本文冻结的公式、状态与概率模型才是工程实现依据。

开发可以立即开始。不得再把下列问题留给工程师临场猜测：

- M1/M2 的方向与换月；
- 比率还是比率减一；
- “持续压力”与“前端压力”的区别；
- 一个叙事 phase 如何唯一产生；
- 5 日/20 日概率究竟预测什么；
- 什么数才可以叫概率。

本文已经冻结这些定义。

---

## 1. 输入材料、权威顺序与产品边界

### 1.1 输入材料

1. `/Users/logan/Downloads/晴雨表量化引擎.pdf`
2. `/Users/logan/Downloads/Sober VIX Barometer「Data Engine」量化晴雨表：指标拆解、VIX期限结构与双策略映射研究报告.md`
3. 本文档

发生冲突时，工程实现按以下顺序处理：

1. 本文已冻结的 MatVIX v1 定义；
2. 交易所/指数提供方的现行官方方法；
3. 原始 Markdown 的研究建议；
4. PDF 的产品叙事与十五项处理名称。

### 1.2 一句话产品定义

**MatVIX 是一个日频 SPX/VIX 保险市场状态与条件概率引擎：它把期限结构、vol-of-vol、尾部定价、VRP 与技术速度压缩成可解释的市场叙事，并估计未来状态转移的校准概率。**

### 1.3 v1 必须交付

- 官方 EOD 数据的历史与每日更新；
- 十五项原始处理行的明确实现或明确扩展位置；
- `CarryRisk / Shock / TailPrice / Persistence / Repair` 五个量化分数；
- 五个正交当前状态答案、一个 outlook 答案与唯一摘要 phase；
- 驱动、反向证据和“什么会改变判断”；
- 四个 5/20 日概率事件；
- 历史基准率、Logistic 概率模型、样本外预测与校准；
- 每日 JSON/Parquet 输出、历史回放和本地 Dashboard。

### 1.4 v1 不负责

- 下单、券商连接、成交与头寸管理；
- 直接给出 SVXY、VXX、VXZ、QQQ、QLD 或 CAOS 的目标仓位；
- 把 MatVIX 概率解释为 SPX 下跌概率或某产品盈利概率；
- 复现或宣称复现 Sober 的私有参数和历史收益。

MatVIX 是下游策略的状态层。下游可以读取状态，但必须通过稳定接口读取，不能从 Dashboard 文案反向解析交易指令。

---

## 2. 每天必须回答的六个业务问题

| 输出 | 业务问题 | 合法答案 |
|---|---|---|
| `carry_answer` | 前端曲线是否仍支持承担 volatility carry？ | `SUPPORTIVE / MIXED / STRESSED / INVERTED / UNKNOWN` |
| `shock_answer` | 保险价格是否正在发生急性重定价？ | `CALM / BUILDING / HIGH / ACUTE / UNKNOWN` |
| `tail_answer` | 下行尾部相对中心的风险中性定价是否突出？ | `NORMAL / ELEVATED / RICH / EXTREME / UNKNOWN` |
| `persistence_answer` | 压力局限在前端，还是已经向中长期扩散？ | `NORMAL / FRONT_LOCALIZED / DIFFUSING / PERSISTENT / MIXED / UNKNOWN` |
| `repair_answer` | 高压之后是否出现可信的边际修复？ | `INACTIVE / BUILDING / CONFIRMED / UNKNOWN` |
| `outlook_answer` | 未来 5/20 日哪个状态转移相对历史基准最值得关注？ | 事件 ID，或 `NO_STRONG_EDGE / BASE_RATE_ONLY / NOT_APPLICABLE / UNKNOWN` |

前五个答案描述当前市场，outlook 描述未来。0–100 总分只是压缩展示，不得取代分维度解释。

### 2.1 三层语言

叙事必须区分三类内容：

1. **直接观测**：VIX9D/VIX、F1/F2、基差、SKEW、VVIX 等价格或指数事实；
2. **模型估计**：滚动百分位、VRP 代理、五维分数和条件概率；
3. **经济解释**：保险供给环境、抢险、扩散、修复等交易员语言。

“保险买方/卖方”是对均衡价格结构的解释，不是已观察到的 signed order flow。产品可以使用有价值的交易员语言，但句式必须是：

> 当前价格结构与保险需求增强/供给环境占优一致。

不得写成：

> 已确认某类买方正在净买入保险。

---

## 3. 日频时点与最小数据集

本节只保留保证公式和概率可复现所必需的规则。

### 3.1 每日时点

- `session_date=t` 表示被解释的美国期权交易日；
- 现货波动率指数使用 Cboe 官方 EOD；
- VX 期货使用 CFE 标准月合约官方 daily settlement；
- 每日正式快照在下一共同交易日 09:20 America/New_York 生成；
- 只使用 `available_at <= decision_as_of` 的数据；
- 不把后来回填的数据伪装成当时已经可见的数据；
- 缺失值不做前向填充，不把 0 当中性值。

每个原始观察最少保存：

```text
series_id
session_date
value
unit
source
source_symbol
observed_at
available_at
ingested_at
revision_id
methodology_version
vintage_kind
```

`vintage_kind` 仅取 `OBSERVED_PIT / ASSUMED_PIT / PROVIDER_BACKTESTED`：已知真实发布时间用 `OBSERVED_PIT`；只有官方 session、无法恢复精确发布时间时，保守设为下一共同交易日 09:20 ET 并标 `ASSUMED_PIT`；提供方事后回算或上线前重构历史标 `PROVIDER_BACKTESTED`。同一 session 的后续修订追加新的 `revision_id`，不覆盖旧值。逐序列 availability 规则写在一个短 manifest 中，不在业务代码里猜。

`vintage_kind` 的准入不是备注，而是唯一规则：

| vintage | 正式当日状态/百分位 | 正式标签、BaseRate、训练、OOF、校准与验收 | 研究数据集 |
|---|---:|---:|---:|
| `OBSERVED_PIT` | 允许 | 允许 | 允许 |
| `ASSUMED_PIT` | 允许；只能按上述保守 `available_at` 生效 | 允许；artifact 必须标记 `PIT_EVIDENCE=ASSUMED` | 允许 |
| `PROVIDER_BACKTESTED` | 禁止 | 禁止 | 允许，且必须标 `RESEARCH_ONLY` |

任一派生 feature 继承其全部必需输入中最弱的 vintage，强弱顺序为 `OBSERVED_PIT > ASSUMED_PIT > PROVIDER_BACKTESTED`。只要一项必需输入是 `PROVIDER_BACKTESTED`，该行就只能进入研究表：不得进入正式 percentile reference window、未来事件谓词、标签、BaseRate、训练、OOF、Platt、模型验收或 live 模型历史。研究报告可以另做“包含回算值”的敏感性分析，但不得把结果写成正式样本外表现。

代码字段 `formal_vintage_eligible_t` 当且仅当该日相应计算链的全部必需原始输入均为 `OBSERVED_PIT` 或 `ASSUMED_PIT`；任一必需输入缺失时由数据状态处理，任一为 `PROVIDER_BACKTESTED` 时该字段为 `false`。

### 3.2 必需数据

| 数据 | 用途 | v1 口径 |
|---|---|---|
| VIX OHLC | 30 日 IV、ATR、Cash VIX Oscillator | Cboe 官方 EOD |
| VIX9D、VIX3M、VIX6M | 近/中/长 SPX IV 期限结构 | Cboe 官方 EOD |
| VVIX | vol-of-vol 与 shock 速度 | Cboe 官方 EOD |
| SKEW | 核心尾部定价 | Cboe 官方 EOD |
| VX 标准月 F1–F6 | 前端斜率、30 日期货、曲线广度 | CFE 官方 settlement |
| SPX close | EWMA 实现方差预测与 VRP 代理 | 同一交易日官方/授权收盘 |

### 3.3 扩展数据

| 数据 | 角色 | 不可得时的行为 |
|---|---|---|
| Cboe SPX/Index/Total Put/Call | activity mix 叙事和 challenger | 不影响核心分数 |
| SDEX、TDEX | 扩展尾部价格 | 仅进入 `tail_extended` |
| VOLI | ATM IV 与全翼 IV 差异研究 | 仅进入 diagnostics |
| 已知事件日历 | 解释“日历风险” | 没有时不生成事件归因 |

扩展数据不得在运行时临时替换核心数据，也不得让同一版本的 headline score 因数据有无而改变权重。

若启用事件日历，v1 只接受 `FOMC / US_CPI / US_NFP / US_FEDERAL_ELECTION / SPX_OPTION_EXPIRY`，每条至少包含 `event_id、event_type、start_at、timezone、known_at`。只有 `known_at<=decision_as_of` 且 `start_at` 位于未来 9 个日历日内的事件可触发日历叙事；多事件按 `start_at,event_id` 排序，phase 只判断是否至少一项成立，叙事最多列前三项。改变该枚举需升级配置版本。

### 3.4 数据状态

运行时只需要三种状态：

- `OK`：核心数据、历史窗口和公式都可计算；
- `PARTIAL`：部分轴可计算，但不能生成完整总分或正式概率；
- `UNKNOWN`：核心快照无法可靠形成。

这不是治理产品；不要为每一种数据异常创建业务状态。具体错误写入 `issues[]` 即可。

`PARTIAL` 时允许展示可计算的观察值和单轴分数，但 `BaselineScore=null`；`market_story.phase/pressure_level/direction` 及六个 answers 取字符串 `UNKNOWN`，四个事件按第 12 节输出 `UNOBSERVABLE + NOT_RUN`，probability 为 `null`。`UNKNOWN` 时所有数值派生字段为 `null`，上述 market-story 枚举为 `UNKNOWN`，证据数组为空，事件同样使用第 12 节状态组合。JSON Schema 必须明确这些字段的可空条件；不得用数值 0 表示未知。

---

## 4. 统一数学约定

### 4.1 比率命名

全文统一：

```text
ratio = A / B
slope = A / B - 1
log_ratio = ln(A / B)
```

- `ratio` 的平坦交叉点是 `1`；
- `slope` 和 `log_ratio` 的平坦交叉点是 `0`；
- 配置和代码不得把 `1.00/1.05` 阈值用于 `ratio_minus_one`。

核心状态尽量使用 `log_ratio` 或明确的原始结构交叉，UI 可展示百分比 slope。

### 4.2 滚动百分位

对任一变量 `x_t`：

```text
reference_window = t 之前最近 756 个官方交易日
minimum_history = 504 个有效交易日
current_t_is_excluded = true
```

百分位采用 mid-rank：

\[
p_t(x)=
\frac{\#\{x_s<x_t\}+0.5\#\{x_s=x_t\}}{N}.
\]

先固定这 756 个 session，再过滤无效值；不得为了凑够 756 个有效值继续向更早历史扫描。输出范围 `[0,1]`。合法极端值不 winsorize。`p(-x)` 表示先将同一窗口序列取负，再按相同规则计算。方法版本不同的序列不得在同一个 percentile 窗口中无标记拼接。

### 4.3 变化量

- `d5_x = x_t-x_{t-5}`，适用于可正可负的量；
- `d1_log_x = ln(x_t/x_{t-1})`；
- `d5_log_x = ln(x_t/x_{t-5})`；
- 非正值不计算对数；
- `t-5` 指前五个交易日，不是五个日历日。

代码和 Parquet 只使用以下 canonical snake-case 字段，不创建大小写或希腊字母别名：

```text
d1_log_vix
d5_log_vix
d5_log_vvix
d5_log_vxcm30
d5_front_slope30
d5_basis30_eod
d5_near_stress
d5_skew
d5_sdex
d5_log_tdex
d5_fvol_30_93
d5_fvol_93_184
d5_baseline_score
```

---

## 5. 核心公式字典

### 5.1 标准月 VX F1/F2

只选择 CFE 标准月 VX，排除周合约和后复权连续合约。

在交易日 `t` 的 EOD settlement 之后：

```text
eligible = 标准月合约，且 final_settlement_timestamp > 当前 settlement_as_of
F1 = eligible 中最早到期合约
F2 = 第二早到期合约
...
F6 = 第六早到期合约
```

原始前端斜率：

\[
TS12=\frac{F_2}{F_1}-1.
\]

30 日期限标准化斜率：

\[
FrontSlope30=
\ln\left(\frac{F_2}{F_1}\right)
\frac{30}{D_2-D_1},
\]

其中 `vx_settlement_event_time` 取该合约官方 daily settlement 对应的事件时点。v1 在原始数据不带时间时固定映射为该 session 的 `15:00 America/Chicago`；若交易所方法日后变化，更新 methodology version 而不是静默改时间。精确定义：

\[
D_i=\frac{final\_settlement\_timestamp_i-vx\_settlement\_event\_time}{86400}.
\]

- `TS12 > 0`：contango；
- `TS12 < 0`：backwardation；
- `FrontSlope30` 用于跨到期位置比较；
- `TS12` 用于自然结构解释。

### 5.2 严格 30 日历日期货价格与现货基差

从标准月 VX 合约中选择真正包围 30 日的 `a,b`：

```text
D_a <= 30 < D_b
```

定义：

\[
w_a=\frac{D_b-30}{D_b-D_a},
\qquad
w_b=\frac{30-D_a}{D_b-D_a},
\]

\[
VXCM30=w_aF_a+w_bF_b.
\]

临近月度结算时，`a,b` 可能是 F2/F3，不能永远假定为 F1/F2。找不到合法夹逼合约时不外推。

现货—期货基差：

\[
Basis30EOD=\frac{VXCM30}{VIX_{official\_EOD}}-1.
\]

代码字段为 `basis30_eod`。它把 CFE settlement reference 与 Cboe official EOD 组成一个稳定的日频参考基差，并不声称两者是同一秒的同步报价；因此它不参与急性 hard confirmation。`Basis30EOD` 不是已经实现的 roll yield，也不等于 S&P VIX Short-Term Futures Index 日收益。

叙事必须同时观察：

```text
d5_log_vxcm30
d5_log_vix
d5_basis30_eod
```

因为基差上升可能来自 VIX 下跌，也可能来自远期价格上升；两者的市场故事不同。

### 5.3 SPX 隐含波动率期限结构

核心比率：

\[
Ratio_{9,30}=\frac{VIX9D}{VIX},
\qquad
NearStress=\ln\left(\frac{VIX9D}{VIX}\right),
\]

\[
Ratio_{30,93}=\frac{VIX}{VIX3M},
\qquad
MediumFront=\ln\left(\frac{VIX}{VIX3M}\right).
\]

解释：

- `VIX9D > VIX` 是短期限保险相对 30 日期限抬价；
- `VIX > VIX3M` 是压力前端化；
- `VIX/VIX3M` 高不等于压力已经持久扩散。

持续性必须使用方差时间分解。目标期限的年分数固定为 `9/365、30/365、93/365、184/365`：

\[
q_T=(VIX_T/100)^2,
\]

\[
FV_{a,b}=\frac{T_bq_b-T_aq_a}{T_b-T_a}.
\]

v1 必须计算：

```text
fvar_9_30
fvar_30_93
fvar_93_184
fvol_9_30 = sqrt(fvar_9_30) * 100
fvol_30_93 = sqrt(fvar_30_93) * 100
fvol_93_184 = sqrt(fvar_93_184) * 100
```

`fvar_*` 只保存年化方差原值；Persistence、Repair、状态和概率 predictors 统一读取 `fvol_*` 及其 level difference，不混用方差变化。

若任一远期方差为负，不取绝对值、不截断为零；该区间记为不可计算并显示原因。当日 `Persistence / Repair / BaselineScore=null`，`persistence_answer / repair_answer / phase=UNKNOWN`，四个事件使用 `UNOBSERVABLE + NOT_RUN` 且 probability 为 `null`，整体 `data_status=PARTIAL`；不得删除该项后重归一其余权重。

### 5.4 Futures 曲线广度

核心版本固定使用连续的 F1–F6，`m=6`：

\[
CurveInversionShare=
\frac{\sum_{i=1}^{m-1}I(F_i>F_{i+1})}{m-1},
\qquad m=6.
\]

F1–F6 任一缺失或中间跳洞时该字段不可计算，不以 4/5 个合约临时重定义。它回答前端倒挂是单点现象，还是已经沿期货曲线扩散。

### 5.5 Cash VIX Oscillator 与技术速度

技术指标统一作用于 VIX，而不是任意切换标的。

Wilder ATR14：

\[
TR_t=\max(H_t-L_t,|H_t-C_{t-1}|,|L_t-C_{t-1}|),
\]

首个 ATR 为前 14 个 TR 的算术平均，之后：

\[
ATR14_t=\frac{13\cdot ATR14_{t-1}+TR_t}{14}.
\]

EMA：

\[
EMA_n(t)=\frac{2}{n+1}C_t+\left(1-\frac{2}{n+1}\right)EMA_n(t-1).
\]

EMA 的第一个有效值使用前 `n` 个有效收盘的算术平均；此前为 warm-up。MACD 的快慢 EMA 分别按自身窗口初始化，Signal 在 9 个有效 MACD 后用其算术平均初始化。

Cash VIX Oscillator 冻结为：

\[
CashVIXOsc=\frac{VIX-EMA20(VIX)}{ATR14(VIX)}.
\]

同时计算：

```text
vix_atrp14 = ATR14 / VIX
vix_ema5_minus_20 = EMA5 / EMA20 - 1
vix_rsi14
vix_stochastic_k14
vix_stochastic_d3
vix_macd_12_26
vix_macd_signal_9
vix_macd_histogram
```

RSI 使用 Wilder 14；当平均跌幅为 0 时 RSI=100，当平均涨幅和跌幅都为 0 时 RSI=50。Stochastic 的 14 日高低区间为 0 时 `%K=50`。MACD 使用 EMA 12/26/9。

精确定义：

\[
Gain_t=\max(C_t-C_{t-1},0),\qquad
Loss_t=\max(C_{t-1}-C_t,0),
\]

\[
RSI14=100-\frac{100}{1+Wilder14(Gain)/Wilder14(Loss)},
\]

\[
\%K14=100\frac{C_t-\min(L_{t-13:t})}
{\max(H_{t-13:t})-\min(L_{t-13:t})},
\qquad
\%D3=SMA_3(\%K14),
\]

\[
MACD=EMA12-EMA26,\qquad
Signal=EMA9(MACD),\qquad
Histogram=MACD-Signal.
\]

若 `ATR14=0`，`CashVIXOsc=0`；不得除以一个人为 epsilon 产生巨大伪信号。

这些技术量用于速度、确认、反向证据和概率 challenger，不与期限结构逐项平权投票。

### 5.6 VVIX、SKEW 与扩展尾部指标

- VVIX 使用 level percentile、`d5_log_vvix`；
- 不使用 `VVIX/VIX` 作为 v1 特征，因为分母下降会机械抬高比率；
- SKEW 是风险中性尾部定价指标，不是物理崩盘概率；
- SDEX/TDEX 如取得授权数据，独立展示，不与 SKEW 拼成同一序列；
- `VIX/VOLI` 仅为 ATM 与全翼方法差异的实验代理，不进入 headline。

核心尾部分数只依赖可稳定获得的 Cboe SKEW。扩展尾部分数另行命名，不能覆盖核心版本。

### 5.7 Put/Call Activity Mix

至少拆分：

```text
pcr_spx_volume
pcr_index_volume
pcr_equity_volume
pcr_total_volume
```

\[
PCR=\frac{PutVolume}{CallVolume}.
\]

Put/Call 是成交活动构成，不是 signed demand。高 PCR 只能作为“保护/看跌活动占比上升”的证据；不得据此断言主动买入或机构/零售身份。

### 5.8 Ex-ante VRP 代理

SPX 日对数收益：

\[
r_t=\ln(SPX_t/SPX_{t-1}).
\]

EWMA 日方差：

\[
\hat\sigma_t^2=0.94\hat\sigma_{t-1}^2+0.06r_t^2.
\]

收益只由两个相邻官方 session 的有效 SPX close 构成；缺一个 session 时不得把跨两日收益当成单日收益。用最早连续 252 个日收益的去均值样本方差初始化（`ddof=1`），在第 252 个收益对应的 session 首次输出 seed；下一有效相邻 session 才用其新收益进入递推。数据缺口日及跨缺口首日的 VRP 为 null，并报告数据问题，不对 model state 做静默填充。年化预测：

\[
RVForecast_t=252\hat\sigma_t^2.
\]

VRP 代理：

\[
VRP^{EWMA}_t=(VIX_t/100)^2-RVForecast_t.
\]

它是“隐含方差减 EWMA 预期实现方差”的估计，不是可直接观察的真实 VRP。未来 21 日实现方差只能作为 outcome，禁止进入当日特征。

---

## 6. 原始十五项处理行在 v1 的唯一映射

| PDF 处理行 | v1 冻结实现 | 产品角色 |
|---|---|---|
| M1:M2 VIX Futures | `TS12`、`FrontSlope30` | Carry 核心 |
| VX30:VIX Roll Yield | `VXCM30`、`Basis30EOD`；不称实现 roll yield | Carry 核心 |
| VIX9D:VIX Crossover | `Ratio_9_30`、`NearStress` | Shock 核心 |
| VIX:VIX3M Medium | `Ratio_30_93`、`MediumFront`；持续性另用 forward variance | 期限定位 |
| Cash VIX Oscillator | `(VIX-EMA20)/ATR14` | Shock/Repair 核心 |
| VIX / VOLI / VVIX | VVIX 核心；VOLI 诊断；拒绝 VVIX/VIX | Shock/扩展 |
| SDEX / TDEX / SKEW | SKEW 核心；SDEX/TDEX 扩展 | TailPrice |
| Put / Call Ratios | 分口径 volume PCR | activity mix |
| Volatility Risk Premium | `VRP_EWMA94` | Carry compensation context |
| Standard Deviations | 滚动百分位/标准化层 | 变换，不独立投票 |
| ATR | VIX Wilder ATR14、ATRP14 | 速度/不稳定度 |
| EMA | VIX EMA5、EMA20 | 趋势确认 |
| RSI | VIX Wilder RSI14 | 诊断/反证 |
| Stochastic Oscillators | VIX 14/3 | 诊断/反证 |
| Convergence / Divergence | VIX MACD 12/26/9；跨市场背离留作扩展 | 趋势确认 |

任何新公式都必须用新的 feature version，不得在同名字段下替换。

---

## 7. 五个量化分数

下列权重是 `MATVIX_CBOE_CORE_V1` 的透明 baseline，不是 Sober 私有参数，也不宣称最优。它们的价值在于先形成一个稳定、可解释、可被概率模型检验的坐标系。

所有 `p()` 都按第 4.2 节计算。

### 7.1 CarryRisk

\[
CarryRisk=100[0.45p(-FrontSlope30)
+0.35p(-Basis30EOD)
+0.20p(-d5\_front\_slope30)].
\]

CarryRisk 越高，前端 carry 环境越受损。

VRP 不进入 CarryRisk，以避免把“保险价格很贵”误写成“承担风险很安全”。另行输出：

```text
vrp_percentile = p(VRP_EWMA94)
carry_compensation = THIN(<0.35) / NORMAL / RICH(>=0.75)
```

### 7.2 Shock

\[
Shock=100[
0.30p(NearStress)
+0.20p(d1\_log\_vix)
+0.20p(d5\_log\_vix)
+0.15p(d5\_log\_vvix)
+0.15p(VVIX)].
\]

自然结构确认数：

```text
front_confirmation_count =
    I(VIX9D > VIX)
  + I(F1 > F2)
  + I(p(CashVIXOsc) >= 0.90)
```

急性硬确认：

```text
hard_acute = Shock >= 85 AND front_confirmation_count >= 2
```

### 7.3 TailPrice

核心版本：

\[
TailPrice=100[0.70p(SKEW)+0.30p(d5\_skew)].
\]

核心版本表示由 SKEW 刻画的下行尾部相对中心之风险中性定价与变化速度，不是实际保护成交价格，也不是崩盘概率。

取得 SDEX/TDEX 后可另算：

\[
TailAcceleration=
0.50p(d5\_log\_tdex)
+0.25p(d5\_sdex)
+0.25p(d5\_skew),
\]

\[
TailExtended=100[
0.30p(SKEW)+0.25p(SDEX)+0.30p(TDEX)+0.15TailAcceleration],
\]

`TailAcceleration` 与 `TailExtended/100` 均严格位于 `[0,1]`。只有 SKEW、SDEX、TDEX 同日完整且方法版本已知时才计算；否则 `TailExtended=null`，不重归一。它只能作为 challenger，不能在同一个 model ID 下替换 `TailPrice`。

### 7.4 Persistence

\[
Persistence=100[
0.40p(fvol\_30\_93)
+0.30p(fvol\_93\_184)
+0.20p(d5\_fvol\_30\_93)
+0.10CurveInversionShare].
\]

它衡量压力是否向中长期期限和期货曲线扩散，而不是用 `VIX/VIX3M` 的高低代替持续性。

### 7.5 Repair

\[
Repair=100[
0.30p(-d5\_log\_vix)
+0.25p(-d5\_near\_stress)
+0.20p(d5\_front\_slope30)
+0.15p(-d5\_log\_vvix)
+0.10p(-d5\_fvol\_30\_93)].
\]

Repair 越高，边际修复证据越强。它不从总压力分中直接扣除，因为“风险仍高但正在修复”与“风险已经低”不是一回事。

### 7.6 BaselineScore

\[
BaselineScore=
0.30CarryRisk
+0.30Shock
+0.20TailPrice
+0.20Persistence.
\]

展示强度带：

| 分数 | `pressure_level` |
|---:|---|
| `[0,35)` | `LOW` |
| `[35,55)` | `WATCH` |
| `[55,70)` | `ELEVATED` |
| `[70,85)` | `HIGH` |
| `[85,100]` | `EXTREME` |

方向：

```text
d5_baseline_score >= +7.5  -> RISING
d5_baseline_score <= -7.5  -> FALLING
otherwise               -> STABLE
```

BaselineScore 是当前风险定价强度，不是未来事件概率。

若 BaselineScore 不可计算，`pressure_level=UNKNOWN`、`direction=UNKNOWN`。若当天分数可计算但尚无 `t-5` 有效分数，只将 `direction=UNKNOWN`，不影响当天 pressure level。

---

## 8. 正交市场答案与唯一 phase

### 8.1 Carry

按 `INVERTED > STRESSED > SUPPORTIVE > MIXED` 的优先级匹配：

| 答案 | 精确条件 |
|---|---|
| `SUPPORTIVE` | CarryRisk < 35，且 FrontSlope30 > 0，Basis30EOD > 0 |
| `MIXED` | 不满足其他条件且 CarryRisk < 65 |
| `STRESSED` | CarryRisk >= 65，但 FrontSlope30 >= 0 |
| `INVERTED` | FrontSlope30 < 0 |
| `UNKNOWN` | 必需输入不可算 |

### 8.2 Shock

按 `ACUTE > HIGH > BUILDING > CALM` 的优先级匹配：

| 答案 | 精确条件 |
|---|---|
| `CALM` | Shock < 40 |
| `BUILDING` | 40 <= Shock < 65 |
| `HIGH` | Shock >= 65 且不满足 ACUTE；包括 Shock>=85 但结构确认不足 |
| `ACUTE` | Shock >= 85 且 `front_confirmation_count >= 2` |
| `UNKNOWN` | 必需输入不可算 |

若 Shock >=85 但结构确认少于两个，仍为 `HIGH`，并输出“价格速度极端，但结构确认不足”。

### 8.3 TailPrice

按 `EXTREME > RICH > ELEVATED > NORMAL` 的优先级匹配：

| 答案 | 精确条件 |
|---|---|
| `NORMAL` | TailPrice < 60 |
| `ELEVATED` | 60 <= TailPrice < 75 |
| `RICH` | 75 <= TailPrice < 90 |
| `EXTREME` | TailPrice >= 90 |
| `UNKNOWN` | 必需输入不可算 |

### 8.4 Persistence

按 `PERSISTENT > DIFFUSING > FRONT_LOCALIZED > NORMAL > MIXED` 的优先级匹配：

| 答案 | 精确条件 |
|---|---|
| `NORMAL` | Persistence < 55 且 Shock < 65 |
| `FRONT_LOCALIZED` | Shock >= 65 且 Persistence < 50 |
| `DIFFUSING` | Persistence >= 55；`d5_fvol_30_93 > 0`；且 `p(d5_fvol_30_93) >= 0.70` |
| `PERSISTENT` | `persistent_now=true` |
| `MIXED` | 以上均不满足 |
| `UNKNOWN` | 必需输入不可算 |

统一原子谓词：

```text
persistent_day_t = Persistence_t >= 75 AND BaselineScore_t >= 65
persistent_now_t = sum_{s=t-4}^t I(persistent_day_s) >= 3
```

窗口包含当日，共五个官方交易 session。窗口谓词使用三值逻辑：先记已知 `TRUE` 数量为 `T`、未知数量为 `U`；若 `T>=3` 则结果为 `TRUE`，若 `T+U<3` 则为 `FALSE`，否则为 `UNKNOWN`。缺失日不得当成 `FALSE`。

### 8.5 Repair

先定义：

```text
stress_day_s = BaselineScore_s >= 70 OR hard_acute_s = true
recent_stress_t = any_{s=t-9}^t stress_day_s

repair_confirmed =
    recent_stress
AND Repair_t >= 70 AND Repair_t-1 >= 70
AND Shock_t < Shock_t-1
AND p(d5_fvol_30_93)_t < 0.60
AND hard_acute_t = false
```

`recent_stress` 窗口包含当日，共十个官方交易 session：任一已知日为 `TRUE` 即为 `TRUE`；十日全部已知且均为 `FALSE` 才为 `FALSE`；其余为 `UNKNOWN`。所有 `AND/OR` 复合谓词采用相同三值逻辑，能由已知值确定时就确定，否则传播 `UNKNOWN`。`persistent_now` 或 `repair_confirmed` 为 `UNKNOWN` 时，相应 answer 取 `UNKNOWN`，不得默认为未发生。

| 答案 | 精确条件 |
|---|---|
| `CONFIRMED` | `repair_confirmed=true` |
| `BUILDING` | `recent_stress=true` 且 Repair>=60，但未满足 CONFIRMED |
| `INACTIVE` | 不满足以上条件 |
| `UNKNOWN` | Repair 必需输入不可算 |

Repair 是独立方向轴。市场可以同时是 `persistence_answer=PERSISTENT` 与 `repair_answer=CONFIRMED`；这表示“风险仍广，但边际修复证据占优”。

### 8.6 摘要 phase 优先级

按下表自上而下匹配，得到唯一 `phase`：

| 优先级 | `phase` | 进入谓词 |
|---:|---|---|
| 1 | `UNKNOWN` | 数据状态不是 OK |
| 2 | `ACUTE_FRONT_STRESS` | `hard_acute=true` |
| 3 | `REPAIR_IN_PROGRESS` | Repair=`CONFIRMED` 且无 hard acute |
| 4 | `BROAD_PERSISTENT_STRESS` | `persistent_now=true` |
| 5 | `CALENDAR_LOCALIZED_PREMIUM` | 截止 `decision_as_of` 已知、将在未来 9 个日历日内开始的事件；NearStress>0；Shock>=65；Persistence<50 |
| 6 | `PRESSURE_BUILDING` | Shock>=60 且 BaselineScore>=60 |
| 7 | `TAIL_RICH_QUIET_CURVE` | CarryRisk<45；Shock<55；Persistence<55；TailPrice>=75 |
| 8 | `CARRY_SUPPORTIVE_LOW_STRESS` | CarryRisk<35；Shock<40；Persistence<45；TailPrice<65 |
| 9 | `MIXED_TRANSITION` | 以上均不满足 |

没有事件日历时，永远不生成 `CALENDAR_LOCALIZED_PREMIUM`；前端局部压力仍由 `persistence_answer=FRONT_LOCALIZED` 表达。

### 8.7 最小滞回

- `ACUTE_FRONT_STRESS`、`REPAIR_IN_PROGRESS` 与 `BROAD_PERSISTENT_STRESS` 的谓词自身已经包含结构/多日确认，满足当日立即进入；
- 数据状态不是 OK 时当日进入 `UNKNOWN`；它永远优先于 acute 的退出规则；
- 仅在数据状态为 OK 且上一发布 phase 为 acute 时，退出 acute 才要求 `hard_acute=false` 且 Shock<75 连续两日；
- `PERSISTENT` 的定义本身采用最近 5 日 3 日确认；
- 其余 phase 候选连续两日才切换；
- 未确认期间保留当前 phase，并输出 `candidate_phase` 和 `candidate_streak`。

唯一状态转移算法：

```text
raw_phase_t = 按第 8.6 节优先级求值

if raw_phase_t == UNKNOWN:
    publish UNKNOWN
    clear candidate
elif previous_published_phase 不存在或为 UNKNOWN:
    publish raw_phase_t                 # bootstrap / 数据恢复
    clear candidate
elif previous_published_phase == ACUTE_FRONT_STRESS:
    if raw_phase_t == ACUTE_FRONT_STRESS:
        publish ACUTE_FRONT_STRESS
        clear candidate
    elif hard_acute_t == false AND Shock_t < 75:
        candidate_phase = raw_phase_t
        candidate_streak = previous_candidate_streak + 1
        if candidate_streak >= 2: publish raw_phase_t; clear candidate
        else: publish ACUTE_FRONT_STRESS
    else:
        publish ACUTE_FRONT_STRESS
        clear candidate
elif raw_phase_t in {ACUTE_FRONT_STRESS, REPAIR_IN_PROGRESS, BROAD_PERSISTENT_STRESS}:
    publish raw_phase_t                 # 谓词已经自带确认
    clear candidate
else:
    candidate_streak = previous_streak + 1 if raw_phase_t == previous_candidate else 1
    candidate_phase = raw_phase_t
    if candidate_streak >= 2: publish raw_phase_t; clear candidate
    else: publish previous_published_phase
```

acute 释放期间，公开的 `candidate_phase/candidate_streak` 就是候选 raw phase 与 release streak，不另造第二套计数器。两个确认日必须是连续的 data-status OK session；任一日重新满足 hard acute 会清零。

状态 bootstrap：全历史第一个可计算日直接发布当日 raw phase；进入 UNKNOWN 时清空 candidate streak；数据恢复后的第一个 OK 日同样直接发布当日 raw phase。`replay --session D` 必须加载已验证的 `D-1` 状态 checkpoint，或从最早可用日顺序重放到 D，不能用 D 的孤立一行猜前态。

这是为了让叙事稳定，不是为了把简单模型写成复杂状态治理。

---

## 9. 市场叙事生成器

叙事核心必须确定性生成。可以使用 LLM 润色，但 LLM 只能改写句子，不能改变数值、状态、驱动、反向证据和概率。

### 9.1 单轴句库

| 条件 | 基础叙事 |
|---|---|
| Carry=`SUPPORTIVE` | 前端曲线与基差仍支持 carry 环境。 |
| Carry=`MIXED` | 前端曲线与基差给出混合信号，carry 条件并不清晰。 |
| Carry=`STRESSED` | 前端 carry 结构正在受损，承担波动率卖方风险的环境变差。 |
| Carry=`INVERTED` | 前端 VIX 期货已经倒挂，carry 环境明显受损。 |
| Carry=`UNKNOWN` | 当前无法形成完整的 carry 判断。 |
| Shock=`CALM` | 短期限保险价格暂未出现异常加速。 |
| Shock=`BUILDING` | 短期限保险定价开始升温，但尚未构成急性压力。 |
| Shock=`HIGH` | 短期限保险正在快速重定价，前端压力较高。 |
| Shock=`ACUTE` | 多个前端结构同时确认急性压力。 |
| Shock=`UNKNOWN` | 当前无法形成完整的急性重定价判断。 |
| Tail=`NORMAL` | 下行尾部相对中心的风险中性定价处于自身正常区间。 |
| Tail=`ELEVATED` | 下行尾部相对中心的风险中性定价开始突出。 |
| Tail=`RICH` | 下行尾部相对中心的风险中性定价偏贵，即使现货波动率尚未极端也需关注。 |
| Tail=`EXTREME` | 下行尾部相对中心的风险中性定价处于自身历史极端区间。 |
| Tail=`UNKNOWN` | 当前无法形成完整的尾部定价判断。 |
| Persistence=`NORMAL` | 中长期期限尚未显示压力扩散。 |
| Persistence=`FRONT_LOCALIZED` | 压力主要集中在前端，尚未确认向中期限扩散。 |
| Persistence=`DIFFUSING` | 中期限 forward volatility 正在上升，压力出现扩散证据。 |
| Persistence=`PERSISTENT` | 中期限压力已连续维持，当前更接近持续性高压环境。 |
| Persistence=`MIXED` | 期限广度证据相互冲突，暂不能归为局部或持续扩散。 |
| Persistence=`UNKNOWN` | 当前无法形成完整的期限广度判断。 |
| Repair=`INACTIVE` | 当前没有足够的同步修复证据。 |
| Repair=`BUILDING` | 多项边际修复信号正在形成，但尚未完成确认。 |
| Repair=`CONFIRMED` | 多项边际修复证据占优，但这不代表绝对风险已经回到低位。 |
| Repair=`UNKNOWN` | 当前无法形成完整的修复判断。 |

摘要 headline 固定映射：

| phase | `phase_headline` |
|---|---|
| `UNKNOWN` | 今日核心数据不足，暂不形成完整市场天气。 |
| `ACUTE_FRONT_STRESS` | 前端保险市场进入急性压力。 |
| `REPAIR_IN_PROGRESS` | 高压后的修复阶段仍在进行。 |
| `BROAD_PERSISTENT_STRESS` | 压力已扩散并形成持续性高压。 |
| `CALENDAR_LOCALIZED_PREMIUM` | 保险溢价集中在已知日历窗口附近。 |
| `PRESSURE_BUILDING` | 保险市场压力正在累积。 |
| `TAIL_RICH_QUIET_CURVE` | 表面曲线平静，但下行尾部风险中性定价偏贵。 |
| `CARRY_SUPPORTIVE_LOW_STRESS` | 前端 carry 条件健康，短端压力较低。 |
| `MIXED_TRANSITION` | 市场证据分化，处于过渡状态。 |

### 9.2 Driver 与反向证据

Driver 只从 CarryRisk、Shock、TailPrice、Persistence 四个风险轴中选，不从 Repair 组件中选。每个风险特征的贡献为：

\[
Contribution_j=
AxisWeight_j\times WithinAxisWeight_j\times(p_j-0.5).
\]

其中 `p_j` 已统一成“越高越危险”；例如 FrontSlope 使用 `p(-FrontSlope30)`，NearStress 使用 `p(NearStress)`：

```text
drivers = risk_percentile >= 0.75 的最多三项，按 Contribution 降序
counter_evidence = risk_percentile <= 0.35 的最多两项，按 Contribution 升序
repair_evidence = Repair 组成项中 repair_percentile >= 0.75 的最多三项
structural_triggers = 当日成立的自然交叉与 hard_acute 条件
```

核心证据词典：

| evidence_id | 高风险/高修复分位的确定性含义 |
|---|---|
| `carry.front_slope` | 前端 VX 曲线相对自身历史明显平坦或倒挂 |
| `carry.basis30_eod` | 官方 EOD 参考基差明显压缩或转负 |
| `carry.slope_change_5d` | 前端曲线在五日内明显恶化 |
| `shock.near_stress` | VIX9D 相对 VIX 明显抬升 |
| `shock.vix_change_1d` | VIX 单日重定价速度偏高 |
| `shock.vix_change_5d` | VIX 五日累计重定价速度偏高 |
| `shock.vvix_change_5d` | vol-of-vol 在五日内明显加速 |
| `shock.vvix_level` | VIX 期权隐含波动率处于高位 |
| `tail.skew_level` | 下行尾部相对中心的风险中性定价更突出 |
| `tail.skew_change_5d` | SKEW 五日变化偏强 |
| `persistence.fvol_30_93` | 30–93 日 forward volatility 处于高位 |
| `persistence.fvol_93_184` | 93–184 日 forward volatility 处于高位 |
| `persistence.fvol_change_5d` | 中期限 forward volatility 正在扩散 |
| `persistence.curve_breadth` | VX 倒挂已覆盖更多连续期限段 |
| `repair.vix` | VIX 五日边际回落 |
| `repair.near_stress` | VIX9D/VIX 前端压力回落 |
| `repair.front_slope` | VX 前端曲线边际恢复 |
| `repair.vvix` | vol-of-vol 边际回落 |
| `repair.fvol_30_93` | 中期限 forward volatility 边际回落 |

低风险分位使用同一含义的反向句式，例如“前端曲线仍陡峭”“中期限 forward volatility 尚未抬升”。不得根据 feature 名临时生成新的因果解释。

每项必须包含：

```json
{
  "feature": "near_stress",
  "raw_value": 0.041,
  "percentile": 0.91,
  "meaning": "VIX9D 相对 VIX 明显偏高"
}
```

如果四个风险轴最高分与最低分相差至少 40 分，追加：

> 当前证据分化明显，单一方向叙事不足。

### 9.3 “什么会改变判断”

按当前 phase 固定生成 1–3 条反转条件：

- unknown：`data_status=OK` 后按历史前态顺序重算；
- acute：`hard_acute=false` 且 Shock<75 连续两日；
- repair in progress：`hard_acute=true`，或 Repair<60 连续两日；
- broad persistent：`persistent_now=false`，或 `repair_answer=CONFIRMED`；
- calendar localized：事件窗口结束、NearStress<=0，或 Persistence>=55；
- pressure building：Shock<55 且 FrontSlope30>0 连续两日；
- tail-rich quiet：TailPrice<70，或 Shock>=65，或 Persistence>=55；
- carry supportive：FrontSlope30<0，或 Shock>=65；
- mixed transition：任一非 mixed 的 raw phase 连续两日成立。

### 9.4 每日段落模板

```text
{phase_headline}
{carry_sentence}
{shock_sentence} {persistence_sentence}
{tail_sentence} {repair_sentence}
{evidence_sentence}
{outlook_sentence}
```

数组为空时不填充假证据：

```text
drivers 为空 -> “当前没有单项风险贡献超过 75% 历史分位。”
counter_evidence 为空 -> 省略反向证据从句。
所有事件不适用 -> “当前四类转移问题均不适用于已有状态。”
只有历史基准率、没有合格特征模型 -> “当前仅有同类历史发生率，特征尚未提供可信增量判断。”
数据或历史不足 -> “当前没有可发布的状态转移概率判断。”
最大 uplift < 10 个百分点 -> “当前四类转移概率均未明显偏离各自历史基准。”
否则 -> “相对历史基准提升最明显的是 {event_id}。”
```

---

## 10. 四个概率事件

概率引擎预测的是**明确状态转移**，不是抽象的“市场会不会危险”。每个事件独立建模，概率不要求相加为 1。

所有未来状态都按未来当日的冻结 v1 规则计算；标签不能借用未来窗口之后的信息。

所有事件先应用同一个可观察性条件：

```text
global_model_observable_t(event) =
    data_status_t == OK
AND formal_vintage_eligible_t == true
AND 该事件固定 predictors 全部可用
```

每节再定义一个三值 `event_onset_t(event)=TRUE/FALSE/UNKNOWN`。当日状态唯一映射为：

```text
global_model_observable = false OR event_onset = UNKNOWN -> UNOBSERVABLE
global_model_observable = true  AND event_onset = FALSE   -> NOT_APPLICABLE
global_model_observable = true  AND event_onset = TRUE    -> ELIGIBLE
```

`global_model_eligible_t(event)` 是最后一行的简称。先判可观察性，再判 onset；缺输入或回算 vintage 不得被解释为“不适用”。

BaseRate、Logistic、OOF、Platt 与 Brier 必须使用完全相同的 event-specific eligible cohort。

### 10.1 `acute_front_stress_5d`

业务问题：未来五日是否出现新的急性前端压力？

```text
Y=1，当且仅当在 t+1 ... t+5 任一交易日 u：

Shock_u >= 85
AND
I(VIX9D_u > VIX_u)
+ I(F1_u > F2_u)
+ I(p(CashVIXOsc_u) >= 0.90)
>= 2
```

Onset：

```text
event_onset_t = hard_acute_t = false
```

当前已经急性压力时返回 `NOT_APPLICABLE`，不是 0%。

### 10.2 `front_inversion_5d`

业务问题：未来五日前端 VX futures 是否由 contango 转为倒挂？

```text
Y=1，当且仅当在 t+1 ... t+5 任一 EOD：
FrontSlope30_u < 0
```

Onset：

```text
event_onset_t = FrontSlope30_t >= 0
```

当前已倒挂时返回 `NOT_APPLICABLE`。

### 10.3 `broad_persistent_stress_20d`

业务问题：未来二十日是否形成持续的中期限压力？

```text
Y=1，当且仅当在 t+1 ... t+20 中，
存在任一连续 5 交易日窗口，使：

sum I(Persistence_u >= 75 AND BaselineScore_u >= 65) >= 3
```

Onset：

```text
event_onset_t = persistent_now_t = false
```

它判断持续压力是否形成，不预测 SPX 必然下跌。

### 10.4 `fast_repair_5d`

业务问题：当前压力是否会在未来五日出现可信的边际修复？

```text
Y=1，当且仅当在 t+1 ... t+5 任一交易日 u：
repair_confirmed_u = true
```

`repair_confirmed` 始终引用第 8.5 节同一个原子谓词，标签不得另写一套较宽松的“修复”规则。

Onset：

```text
event_onset_t =
repair_answer_t != CONFIRMED
AND (
  BaselineScore_t >= 65
  OR phase_t in {
    PRESSURE_BUILDING,
    ACUTE_FRONT_STRESS,
    BROAD_PERSISTENT_STRESS
  }
)
```

平静市场返回 `NOT_APPLICABLE`，不能显示“修复概率 0%”。

### 10.5 标签窗口

- 5 日标签必须拥有完整的 `t+1...t+5`；
- 20 日标签必须拥有完整的 `t+1...t+20`；
- 样本末端窗口不完整，或窗口内任一事件谓词必需字段不可计算时，均为 `CENSORED`，不进入训练；
- 窗口内任一必需输入的 vintage 为 `PROVIDER_BACKTESTED` 时同样为 `CENSORED`，不能用可计算性绕过正式 vintage 准入；
- 只有完整观察整个窗口且从未满足事件谓词时，标签才是 0；
- 多个事件可以同时为 1；
- `NOT_APPLICABLE` 不等于负例。

为保持正负例同口径，即使事件提前触发，`outcome_available_at` 也固定为 horizon 最后一个交易日 EOD 快照在下一共同交易日 09:20 ET 可用之时；不得因正例提前发生而提前送入训练。

---

## 11. 概率模型与校准

### 11.1 条件历史基准率

每个事件先计算可解释的 climatology。令 `N=min(756, t 之前 outcome 已完成的 eligible 样本数)`，`Positive_N` 为其中正例数：

\[
BaseRate_t=\frac{Positive_N+1}{N+2}.
\]

使用 Beta(1,1) 平滑。少于 252 个 eligible 样本时不输出概率。

### 11.2 Logistic baseline

每个事件独立使用 L2 Logistic Regression：

```text
implementation = scikit-learn==1.7.2
penalty = L2
C = 1.0
solver = lbfgs
fit_intercept = true
dual = false
class_weight = None
warm_start = false
tol = 1e-8
max_iter = 1500
random_state = 0
maximum_training_samples = 最近 1500 个 eligible 样本
minimum_training_samples = 252
minimum_positive = 30
minimum_negative = 30
```

`minimum_training_samples=252` 是概率版本 `1.1.0` 的事前可用性约束，不是按模型表现挑选的超参数。完整 Cboe Core 正式历史中，`fast_repair_5d` 只形成 614 个已完成 eligible 样本；若使用 756，该事件在现有真实历史上不可能产生任何 Logistic OOF，因而与“四个事件均须形成 OOF 和校准状态”的完成条件冲突。252 对应至少一个完整交易年的 event-specific 样本，同时仍要求至少 30 个正例、30 个负例、L2 正则、20 日 purge、顺序 Platt 以及独立的 252 条 calibrated OOF 发布验收。该调整只决定模型何时可以开始接受检验，不能放宽 BrierSkill/ECE 发布门；未增益的模型仍必须回退 `BASE_RATE_ONLY`。

调用 `sklearn.linear_model.LogisticRegression` 时显式传入以上参数；特征列严格按下表顺序输入，不另做标准化。`lbfgs` 下截距不受 L2 惩罚。若未收敛则当日特征模型不可发布，不得悄悄换 solver。依赖版本或 solver 改变属于 `probability_version` 变更；golden OOF probability 允许的绝对误差为 `1e-8`。不使用 class weight，因为目标是校准概率，不是只追求分类召回率。

固定输入：

定义一个不增加二次 percentile warm-up 的有界变化量：

\[
ScoreChange5Scaled=
clip\left(\frac{d5\_baseline\_score+100}{200},0,1\right).
\]

| 事件 | 输入，全部缩放到 `[0,1]` |
|---|---|
| acute_front_stress_5d | CarryRisk/100、Shock/100、TailPrice/100、Persistence/100、`ScoreChange5Scaled`、front_confirmation_count/3 |
| front_inversion_5d | `p(-FrontSlope30)`、`p(-d5_front_slope30)`、`p(-Basis30EOD)`、Shock/100 |
| broad_persistent_stress_20d | Persistence/100、Shock/100、TailPrice/100、`p(d5_fvol_30_93)`、`p(fvol_93_184)`、`ScoreChange5Scaled` |
| fast_repair_5d | Repair/100、`1-ScoreChange5Scaled`、`p(-d5_near_stress)`、`p(d5_front_slope30)`、Shock/100、Persistence/100 |

第一版不把十五项原子量全部塞进模型。这样既减少重复投票，也让“为何概率变化”可以解释。

### 11.3 Walk-forward 预测

- 所有验证预测必须由 rolling-origin walk-forward 产生；
- 对预测日 `t`，训练样本日期必须不晚于 `t-20`，且各自 outcome 已完整结束；
- 训练集从最早样本扩张，达到 1500 个 eligible 样本后只保留最近 1500 个；
- 这 20 个交易日的隔离同时覆盖最长标签 horizon，避免标签窗口交叠穿越；
- 保存每条真正样本外预测，形成 OOF probability ledger。

### 11.4 概率校准

1. 先生成未经校准的 Logistic OOF 概率；
2. 对每个预测日 `t`，只用 `prediction_date<t` 且 `outcome_available_at<=decision_as_of_t` 的最近 504 个 eligible OOF 预测拟合 Platt calibration；
3. 校准样本至少包含 20 个正例和 20 个负例；
4. Platt 输入固定为基础 Logistic 的 `decision_function z`，输出为 `sigmoid(a*z+b)`；从 `a=1,b=0` 开始，以 L-BFGS-B 最小化 `mean(binary_log_loss)+1e-6*(a^2+b^2)`，参数为 `maxiter=1000, ftol=1e-12, gtol=1e-8`，不设参数边界；未收敛则不得发布 feature-conditioned probability；优化后概率裁剪到 `[1e-6,1-1e-6]`；
5. 将该日校准后的概率追加到 ledger；它不得反过来进入自身 calibrator；
6. 只有凑齐最近 252 个按上述方式顺序生成、且 outcome 已完成的 calibrated OOF 样本，且其中至少有 20 个正例和 20 个负例，才运行发布验收；与每个样本当时可见的 rolling BaseRate benchmark 比较 Brier Score；
7. 定义 `BrierSkill=1-Brier_model/Brier_base`；ECE 先按 `(calibrated_probability, prediction_date)` 稳定升序，再依次切为 `51,51,50,50,50` 个样本，计算 `ECE=sum_k (n_k/252)*abs(mean(p_k)-mean(y_k))`；要求 BrierSkill>=0.02 且 ECE<=0.07；并列概率不得使用不稳定排序或按唯一值另分箱；
8. 达标则 `model_status=CALIBRATED_MODEL`；
9. 不达标、Logistic/Platt 样本不足或优化未收敛，但 BaseRate 已有至少 252 个 eligible 样本时，使用 `BASE_RATE_ONLY`。此时展示的是 event-specific eligible cohort 的历史参考发生率，不是当前特征提供的增量预测；连 BaseRate 的 252 个样本也不足时才是 `INSUFFICIENT_HISTORY`。

这不是附加治理，而是让 Dashboard 上的百分比真正具有概率含义。

### 11.5 Challenger

只有 baseline 运行稳定后才研究：

- Elastic Net Logistic；
- monotonic gradient boosting；
- 加入 PCR、SDEX/TDEX、VOLI 与技术 diagnostics；
- 状态条件化模型。

Challenger 必须在相同 walk-forward 路径上改善 Brier Score 和校准，才可建立新 model version。不得只凭 ROC-AUC 替换 baseline。

---

## 12. 概率的业务表达

三个状态字段必须分开：

```text
data_status  = OK | PARTIAL | UNKNOWN
event_status = ELIGIBLE | NOT_APPLICABLE | UNOBSERVABLE
model_status = CALIBRATED_MODEL | BASE_RATE_ONLY | INSUFFICIENT_HISTORY | NOT_RUN
```

历史 target ledger 另有 `label_status=OBSERVED_0|OBSERVED_1|CENSORED|NOT_APPLICABLE`。`CENSORED` 是事后标签状态，不是当日预测状态。

`probability_judgment` 以四个 event ID 为 map key；每个 value **恰好**包含以下八个字段，不再重复 `event`，也不增加与 `event_status` 重复的 `eligible`：

```text
event_status, model_status, probability_kind, probability,
base_rate, uplift, valid_through_session, interpretation
```

唯一合法组合如下；表中的“值”表示非 null 的当日计算值，“期限日”表示由交易日历求出的 horizon 最后一个 session：

| event_status | model_status | probability_kind | probability | base_rate | uplift | valid_through_session | interpretation |
|---|---|---|---|---|---|---|---|
| `ELIGIBLE` | `CALIBRATED_MODEL` | `FEATURE_CONDITIONAL` | 模型值 | 当日基准值 | 两者之差 | 期限日 | 固定概率比较句 |
| `ELIGIBLE` | `BASE_RATE_ONLY` | `HISTORICAL_REFERENCE` | 等于基准值 | 当日基准值 | `0.0` | 期限日 | `当前只使用同类历史发生率，特征模型未提供增量判断` |
| `ELIGIBLE` | `INSUFFICIENT_HISTORY` | `null` | `null` | `null` | `null` | `null` | `正式历史样本不足，当前不发布概率` |
| `ELIGIBLE` | `NOT_RUN` | `null` | `null` | `null` | `null` | `null` | `概率作业尚未成功完成` |
| `NOT_APPLICABLE` | `NOT_RUN` | `null` | `null` | `null` | `null` | `null` | `当前状态已存在或该转移问题不适用` |
| `UNOBSERVABLE` | `NOT_RUN` | `null` | `null` | `null` | `null` | `null` | `当前输入不足，无法观察该问题` |

不得输出表外组合。`INSUFFICIENT_HISTORY` 只表示 event 当日适用但不足 252 个正式 eligible 完成样本；已经有 BaseRate、但特征模型样本/OOF/校准不足或未通过增益门时，使用 `BASE_RATE_ONLY`。`NOT_RUN` 只用于不适用、不可观察或概率作业没有成功完成，不用于伪装模型表现不达标。

表达规则：

- 同时显示模型概率和同类历史基准率；
- `uplift = probability - base_rate`，使用百分点解释；
- 不只说“概率高”，要说“当前 X%，同类历史基准 Y%，高出 Z 个百分点”；
- `NOT_APPLICABLE` 与 `UNOBSERVABLE` 的 probability 为 `null`；
- `BASE_RATE_ONLY` 时 `probability=base_rate`、`uplift=0`、`probability_kind=HISTORICAL_REFERENCE`，并明确写“当前只使用同类历史发生率，特征模型未提供增量判断”；
- `CALIBRATED_MODEL` 时 `probability_kind=FEATURE_CONDITIONAL`；
- `INSUFFICIENT_HISTORY/NOT_RUN` 的 probability 为 `null`，其余字段严格按上表；
- 概率不映射为交易指令。

事件释义固定为：

| event | UI 问句 |
|---|---|
| `acute_front_stress_5d` | 未来五日是否出现新的急性前端压力？ |
| `front_inversion_5d` | 未来五日前端 VX 曲线是否由 contango 转为倒挂？ |
| `broad_persistent_stress_20d` | 未来二十日是否形成持续的中期限压力？ |
| `fast_repair_5d` | 当前高压是否会在未来五日形成可信修复？ |

`uplift>=0.10` 使用“明显高于历史基准”；`0<uplift<0.10` 使用“略高于历史基准”；`uplift=0` 使用“仅显示历史基准”；`uplift<0` 使用“低于历史基准”。

`outlook_answer` 的确定规则：

```text
data_status != OK -> UNKNOWN
没有 event_status=ELIGIBLE，且至少一个 UNOBSERVABLE -> UNKNOWN
四个事件全部 NOT_APPLICABLE -> NOT_APPLICABLE
存在 ELIGIBLE 且 CALIBRATED_MODEL -> 从这些事件中选择 uplift 最大者：
    若最大 uplift >= 0.10 -> 输出该 event_id
    否则 -> NO_STRONG_EDGE
不存在 CALIBRATED_MODEL，但至少有 ELIGIBLE 且 BASE_RATE_ONLY -> BASE_RATE_ONLY
其余情况（ELIGIBLE 事件全为 INSUFFICIENT_HISTORY/NOT_RUN）-> UNKNOWN
```

最大 uplift 并列时，按第 10 节事件顺序选择，保证同一输入产生同一答案。

---

## 13. 每日输出合同

```json
{
  "schema_version": "1.0.0",
  "model_id": "MATVIX_CBOE_CORE_V1",
  "feature_version": "1.0.0",
  "state_version": "1.0.0",
  "probability_version": "1.0.0",
  "input_manifest_hash": "sha256:...",
  "session_date": "YYYY-MM-DD",
  "decision_as_of": "ISO-8601",
  "data_status": "OK",
  "market_story": {
    "headline": "string",
    "phase": "MIXED_TRANSITION",
    "candidate_phase": null,
    "candidate_streak": 0,
    "pressure_level": "WATCH",
    "direction": "STABLE",
    "baseline_score": 43.2,
    "answers": {
      "carry": "MIXED",
      "shock": "BUILDING",
      "tail": "ELEVATED",
      "persistence": "MIXED",
      "repair": "INACTIVE",
      "outlook": "NO_STRONG_EDGE"
    },
    "scores": {
      "carry_risk": 38.1,
      "shock": 51.6,
      "tail_price": 64.3,
      "persistence": 31.0,
      "repair": 45.0
    },
    "drivers": [],
    "counter_evidence": [],
    "repair_evidence": [],
    "structural_triggers": [],
    "what_changes_the_view": [],
    "narrative": "string"
  },
  "probability_judgment": {
    "acute_front_stress_5d": {
      "event_status": "ELIGIBLE",
      "model_status": "CALIBRATED_MODEL",
      "probability_kind": "FEATURE_CONDITIONAL",
      "probability": 0.42,
      "base_rate": 0.18,
      "uplift": 0.24,
      "valid_through_session": "YYYY-MM-DD",
      "interpretation": "当前42%，同类历史基准18%，高出24个百分点"
    },
    "front_inversion_5d": {
      "event_status": "NOT_APPLICABLE",
      "model_status": "NOT_RUN",
      "probability_kind": null,
      "probability": null,
      "base_rate": null,
      "uplift": null,
      "valid_through_session": null,
      "interpretation": "当前状态已存在或该转移问题不适用"
    },
    "broad_persistent_stress_20d": {
      "event_status": "ELIGIBLE",
      "model_status": "BASE_RATE_ONLY",
      "probability_kind": "HISTORICAL_REFERENCE",
      "probability": 0.12,
      "base_rate": 0.12,
      "uplift": 0.0,
      "valid_through_session": "YYYY-MM-DD",
      "interpretation": "当前只使用同类历史发生率，特征模型未提供增量判断"
    },
    "fast_repair_5d": {
      "event_status": "UNOBSERVABLE",
      "model_status": "NOT_RUN",
      "probability_kind": null,
      "probability": null,
      "base_rate": null,
      "uplift": null,
      "valid_through_session": null,
      "interpretation": "当前输入不足，无法观察该问题"
    }
  },
  "observations": {},
  "diagnostics": {},
  "issues": []
}
```

上例数值仅用于说明 schema。实际输出必须来自当日数据。

四个事件对象必须始终存在并包含同样的八个字段；不适用或不可观察时使用显式 `null`，不得省略字段、填 0 或返回空对象。

字段映射固定为：`answers.carry/shock/tail/persistence/repair/outlook` 分别对应第 2 节六个 `*_answer`；`scores.carry_risk/shock/tail_price/persistence/repair` 分别对应第 7 节五个分数。不得另造第二套命名。

`input_manifest_hash` 对当日按 `series_id,session_date,revision_id` 排序后的核心输入清单计算 SHA-256；它只用于保证重放使用同一批数值，不扩展成单独治理系统。

### 13.1 下游稳定接口

下游策略只允许读取：

```text
session_date
decision_as_of
data_status
market_story.phase
market_story.pressure_level
market_story.direction
market_story.baseline_score
market_story.answers
market_story.scores
probability_judgment[event].probability
probability_judgment[event].event_status
probability_judgment[event].model_status
probability_judgment[event].probability_kind
```

`narrative` 是人类解释，不是机器交易合同。下游若需要 feature-conditioned probability，必须同时检查 `event_status=ELIGIBLE`、`model_status=CALIBRATED_MODEL` 和 `probability_kind=FEATURE_CONDITIONAL`；`HISTORICAL_REFERENCE` 只是一条基准信息。

---

## 14. Dashboard 必须回答什么

首页不应堆十五个小指标。必须按交易员的决策顺序展示：

1. **一句话天气**：当前 phase、压力强度和方向；
2. **五个当前状态答案**：Carry、Shock、Tail、Persistence、Repair；
3. **曲线图**：VIX9D/VIX/VIX3M/VIX6M 与 VX F1–F6；
4. **为什么**：三条主要驱动、两条反向证据；
5. **概率判断**：四个事件的当前概率、基准率和 uplift；
6. **什么会改变判断**：最关键的进入/退出条件；
7. **历史变化**：过去 1/5/20 日分数、phase 与概率路径；
8. **诊断抽屉**：十五项原始量、技术指标和扩展数据。

UI 规则：

- Score 与 Probability 必须视觉上分开；
- 所有概率旁边同时显示 horizon、事件定义和 base rate；
- `NOT_APPLICABLE` 显示“当前状态已存在/条件不适用”，不能显示 0%；
- `BASE_RATE_ONLY` 与 `CALIBRATED_MODEL` 显示不同标签；
- 当前数据不足时保留可见观察值，但不编造 headline score。

---

## 15. 最小工程架构

建议使用 Python 包；除第 11.2 节已冻结的 `scikit-learn==1.7.2` 外，其余依赖由工程师验证兼容性后锁定。不得在未升级 `probability_version` 与重跑 golden OOF 的情况下替换该模型版本。

```text
MatVIX/
├── pyproject.toml
├── README.md
├── configs/
│   ├── features_v1.yaml
│   ├── state_v1.yaml
│   └── probability_v1.yaml
├── schemas/
│   └── daily_output.schema.json
├── src/matvix/
│   ├── data/
│   │   ├── contracts.py
│   │   ├── cboe.py
│   │   ├── cfe.py
│   │   └── point_in_time.py
│   ├── features/
│   │   ├── futures_curve.py
│   │   ├── iv_curve.py
│   │   ├── tail.py
│   │   ├── vrp.py
│   │   └── technical.py
│   ├── state/
│   │   ├── scores.py
│   │   ├── ontology.py
│   │   └── transitions.py
│   ├── probability/
│   │   ├── targets.py
│   │   ├── baseline.py
│   │   ├── walk_forward.py
│   │   └── calibration.py
│   ├── narrative/
│   │   ├── drivers.py
│   │   └── templates.py
│   ├── output.py
│   ├── cli.py
│   └── dashboard.py
└── tests/
    ├── unit/
    ├── integration/
    ├── golden/
    └── no_lookahead/
```

建议 CLI：

```text
matvix build-snapshot --session YYYY-MM-DD
matvix backfill --start YYYY-MM-DD --end YYYY-MM-DD
matvix train-probabilities --as-of YYYY-MM-DD
matvix replay --session YYYY-MM-DD
matvix serve
```

本地 Dashboard 可采用 Streamlit/Plotly；核心验收对象是计算与叙事，不是前端框架。

---

## 16. 实施顺序与开工闸门

### 阶段 A：数据与公式

交付：

- 核心原始序列与 VX 合约元数据；
- 第 5 节全部公式；
- feature Parquet；
- 每项公式的 golden test；
- 任意历史日可重算。

完成条件：

- contango/backwardation 符号正确；
- 到期周 F1/F2 与 30 日夹逼合约正确；
- ratio 与 slope 阈值不混用；
- 未来数据变化不改变过去 feature。

### 阶段 B：市场叙事引擎

交付：

- 五个分数；
- 五个当前状态答案、唯一 phase 与最小滞回；
- drivers、counter-evidence、change conditions；
- 确定性 narrative；
- 每日 JSON 和 Dashboard 当前状态页。

完成条件：

- 同一输入与配置产生相同叙事；
- phase 优先级无重叠歧义；
- 叙事中的每个事实可指向具体 feature；
- “前端压力”“扩散”“修复”不会被同一个比率混为一谈。

### 阶段 C：概率判断

交付：

- 四个 target label 序列与 eligibility；
- rolling BaseRate；
- 四个 Logistic baseline；
- walk-forward OOF ledger；
- Platt calibration 与 Brier 对比；
- 三值 `event_status` 与四值 `model_status` 均按第 12 节输出；
- 每个 event 的首个 label、BaseRate、Logistic 与 calibrated probability 可用日期及形成原因；
- Dashboard 概率页。

完成条件：

- 标签逐日可重算且窗口边界明确；
- OOF 预测不包含未来 outcome；
- 样本不足或模型不增益时诚实回退 BaseRate；
- 展示的每个百分比都有事件、horizon、基准率和模型状态。

### 阶段 D：历史解释与本地交付

交付：

- 历史 timeline；
- 典型环境回放，不把事件回放冒充样本外成绩；
- 一键运行说明；
- 数据覆盖与概率样本量报告；
- 本地 Dashboard。

完成条件：

- 新工程师按 README 可从原始数据重建输出；
- 用户可选择任意日期查看当时叙事和概率；
- API、Parquet 与 Dashboard 数值一致。

---

## 17. 必须测试的业务事实

测试应围绕业务语义，不需要建设庞大的治理框架。

### 17.1 公式与曲线

- `F2>F1` 必须是 contango；`F1>F2` 必须是 backwardation；
- 结算日后已到期合约不能继续成为 F1；
- 严格 30 日插值允许使用 F2/F3；
- `VIX9D/VIX` ratio 的交叉点为 1，log ratio 的交叉点为 0；
- VIX3M 不是第三个月 VX 期货；
- 负 forward variance 不得被静默修补；
- `Basis30EOD` 变化能够分解到 VIX 与 VXCM30。

### 17.2 状态与叙事

- 急性前端压力可以与中期限尚未扩散同时成立；
- 持续压力与正在修复可以同时被观察，但摘要 phase 按优先级唯一；
- 高 TailPrice、低 Shock 能生成 tail-rich quiet 叙事；
- Driver/反证排序与实际 percentile 一致；
- narrative 不能凭空增加订单流、交易方向或概率。

### 17.3 概率

- `NOT_APPLICABLE` 不得进入负例；
- `PROVIDER_BACKTESTED` 行不得进入正式 percentile、标签、训练、OOF、校准或验收；
- `persistent_now` 与 `recent_stress` 的窗口必须包含当日，缺失按三值阈值逻辑处理；
- 5/20 日末端不完整样本必须删失；
- walk-forward 的训练端不能看到当前预测的 outcome；
- BaseRate 只用当时已完成的 eligible 样本；
- 模型不优于 BaseRate 时自动回退；
- ECE 的稳定排序、`51/51/50/50/50` 分箱与手算 golden value 一致；
- 概率、base rate、uplift 的算术关系正确；
- 每个事件 JSON 只能出现第 12 节真值表允许的八字段组合；
- 未来数据被修改时，过去已生成的 OOF prediction 不变。

---

## 18. Definition of Done

MatVIX v1 完成，必须同时满足：

1. 核心 EOD 数据能历史重建并每日更新；
2. 第 5–8 节公式、分数、五个当前状态答案与 phase 已按本文实现；
3. 每日叙事能回答六个业务问题，并给出驱动、反证与改变条件；
4. 四个概率事件有完整标签、BaseRate、Logistic OOF、校准和模型状态；
5. Dashboard 同时展示当前状态与未来概率，且两者语义不混淆；
6. 任意历史日可以回放，API/Parquet/UI 数值一致；
7. 公式、换月、状态、叙事、概率与 no-lookahead 测试通过；
8. 不可得的扩展数据被诚实标为扩展项，但不妨碍 Cboe Core v1 运行。

以下不构成完成：

- 只有漂亮 Dashboard，没有可重算的 feature 与概率 ledger；
- 只有 0–100 分，没有市场叙事；
- 只有模型 score，却称为概率；
- 用固定示例数填满概率卡片；
- 把 `VIX/VIX3M` 高直接写成“压力必然持续”；
- 把当前状态概率映射成未经定义的交易指令。

---

## 19. 权威方法起点

- Cboe VIX Methodology：<https://cdn.cboe.com/resources/indices/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf>
- Cboe SPX Target Term Volatility Indices：<https://cdn.cboe.com/api/global/us_indices/governance/Volatility_Index_Methodology_Selected_SPX_Target_Expected_Volatility_Term_Indices.pdf>
- Cboe VIX Futures：<https://www.cboe.com/tradable-products/vix/vix-futures/>
- S&P VIX Futures Indices Methodology：<https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-vix-futures-indices.pdf>
- Cboe Broad-Based/VVIX Methodology：<https://cdn.cboe.com/api/global/us_indices/governance/Volatility_Index_Methodology_Selected_Broad_Based_Index_Equity_and_ETF_Volatility_Indices.pdf>
- Cboe SKEW White Paper：<https://cdn.cboe.com/resources/indices/documents/SKEWwhitepaperjan2011.pdf>
- Cboe Daily Options Statistics：<https://www.cboe.com/us/options/market_statistics/daily/>
- Federal Reserve VRP research：<https://www.federalreserve.gov/pubs/feds/2011/201145/index.html>

---

## 20. 给工程团队的最终裁决

本规格允许高级工程师直接开工，不再需要先发明产品定义。

实现优先级必须保持：

```text
业务量化指标
  -> 五维当前市场答案
  -> 当前市场叙事
  -> 明确定义的 5/20 日事件
  -> 条件基准率与校准概率
  -> Dashboard
```

必要的可复现性服务于这条业务链，不能反过来吞掉项目。MatVIX 的成败最终取决于：它是否能用期权保险市场自己的价格语言，稳定解释“现在发生了什么”，并对“接下来哪种状态转移更可能发生”给出有基准、有校准、可被检验的概率判断。
