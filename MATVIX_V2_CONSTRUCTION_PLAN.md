# MatVIX V2 气象站业务审计与施工合同

> 状态：FROZEN FOR NEXT SESSION
> 合同版本：1.0
> 冻结日期：2026-08-22
> 代码基线：`f57e7f5efe2480b7f8a170b4c094459698fc4993`
> 执行方式：下一独立 Codex session 直接审计、施工和本地复核
> 核心顺序：业务审计 → 分项修复 → 气象站自身验收 → 固定经济探针

---

## 0. 本合同解决什么

上一轮工作整体作废。不得恢复 Research Shadow、独立验收包、Reliability/V3 策略层、ChatGPT bootstrap 或围绕 HTML 发布稳健性建设的代码。唯一保留的业务线索是：V1 的严格 30 日 `VXCM30` 在月度换月附近可能存在数据/计算连续性缺陷。该线索必须在干净 V1 上重新复现，旧代码和旧报告不能作为证据。

下一轮只回答四个问题：

1. V1 的数据、期限事实、状态语义、时效和概率究竟有哪些业务缺陷？
2. 每个缺陷的最小正确修复是什么？
3. 修复后的 V2 是否在气象站自身事实层通过验收？
4. 在不优化交易适配器的情况下，V2 是否相对 V1 产生固定经济增量？

本合同是下一轮 V2 增量工作的执行权威。未被 V2 明确修改的 V1 定义继续服从 `MATVIX_PRE_DEVELOPMENT_REPORT.md`、现有配置、Schema 和代码；发生冲突时按以下顺序处理：

1. 人类在本合同之后给出的明确决定；
2. 本合同；
3. 经审计后正式冻结的 V2 规格修订；
4. `MATVIX_PRE_DEVELOPMENT_REPORT.md` 的未修改 V1 定义；
5. 当前正式代码、配置与 Schema。

### 0.1 版本边界

气象站产品版本只允许：

```text
MATVIX_CBOE_CORE_V1
→ MATVIX_CBOE_CORE_V2
```

不建设、不发布、不保留可运行的气象站 `V1.1`。数据修复是 V2 的第一个缺陷修复提交，不是中间产品版本。

当前仓库已有的 Python package `1.1.0` 和 `probability_version=1.1.0` 属于正式 V1 内部版本标识，不等于被禁止的“气象站 V1.1”。审计前不得删除、重命名或改写这些冻结基线。

V2 施工时采用就地升级：

- `MODEL_ID=MATVIX_CBOE_CORE_V2`；
- 所有含义发生改变的 feature/state/probability/schema 版本升为 `2.0.0`；
- V2 正式完成时 Python package 版本升为 `2.0.0`；
- V1 通过 Git 基线和开工时生成的只读历史产物保存；
- 不在 V2 代码中保留 `_v1/_v2` 双实现、兼容开关或平行运行框架；
- 固定经济探针只比较冻结 V1 产物与正式 V2 产物。

### 0.2 明确不做

- 不交给 ChatGPT Pro，不使用外部浏览器布置开发任务；
- 不设计仓位梯度、止损、滞回、期望效用或产品 Edge；
- 不加入 IAU、BOXX、BIL、SPY 或其他资产；
- 不搜索交易阈值，不根据产品收益修改天气定义；
- 不建设通用研究平台、发布安全框架或报告对象防御层；
- 不把 `BASE_RATE_ONLY` 包装成预测增量；
- 不修改 Dashboard 视觉设计；V2 通过后只做必要的 Schema 兼容；
- 不进入生产推广、自动下单或头寸管理。

---

## 1. 新 session 开工协议

新 session 必须先逐字阅读本文件，再执行以下检查：

```bash
cd /Users/logan/MatVIX
git status --short --branch
git fetch --prune origin
git branch -avv --no-abbrev
git worktree list --porcelain
git rev-parse HEAD
git rev-parse refs/remotes/origin/main
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src/matvix
.venv/bin/python -m matvix doctor --project-dir .
```

开工条件：

- `main` 干净，且本地、tracking、远端 `main` 相同；
- 代码基线至少包含本合同，且本合同之前的代码父基线为 `f57e7f5`；
- 正式 V1 测试和 doctor 通过；
- 不存在旧 research/reliability/economic acceptance 运行路径。

随后创建一个开发分支：

```bash
git switch -c codex/matvix-v2
```

严禁读取或恢复 `/Users/logan/MatVIX_cleanup_quarantine/` 中的旧代码、报告和分支 bundle。该目录只用于灾难恢复，不是研究输入。

如果基线不满足上述条件，先停止并修复基线；不得一边清理一边开发 V2。

---

## 2. 证据隔离与数据分区

### 2.1 三层证据必须分开

```text
气象站输入与事实
→ 气象站状态/概率
→ 固定产品映射与 P&L
```

业务审计、修复和站内验收阶段禁止读取 `SVXY/SGOV/VXZ` 价格。产品价格只允许在气象站所有必需门通过并冻结 V2 后进入进程。

### 2.2 时间分区

- 全历史审计：从首个满足相应原始输入条件的正式 session 到最新完整 session；
- 阈值开发窗：截至 `2021-12-31`；
- 状态确认窗：从 `2022-01-03` 到最新完整 session；
- 概率继续使用逐日 rolling-origin、event-specific eligibility、20-session purge 和顺序校准；
- 全历史另做危机/压力事件簇留一，不用重叠交易日冒充独立样本；
- 固定经济探针是 price-blind weather design 之后的历史外部验证，但不得宣称真实前瞻业绩。

不得因为确认窗结果不好而回到产品收益层调整天气阈值。需要修改阈值时，必须重新打开对应业务缺陷并重新冻结规格。

### 2.3 V1 冻结产物

修改代码前，使用正式 V1 顺序重建并保存：

```text
outputs/v2_baseline/v1_features.parquet
outputs/v2_baseline/v1_states.parquet
outputs/v2_baseline/v1_targets.parquet
outputs/v2_baseline/v1_oof.parquet
outputs/v2_baseline/v1_manifest.json
```

`v1_manifest.json` 至少记录：代码 SHA、配置 digest、Schema digest、原始输入 manifest/hash、每张表的行数/日期边界/SHA-256、运行命令和 UTC 时间。以上均为本地忽略产物，不新增 V1 运行代码。

---

## 3. 阶段 A：完整业务审计

阶段 A 不修代码含义、不生成策略收益、不产出 HTML。只允许增加一个最小审计入口，优先复用现有 builder/state/probability 结果。

本地输出限制为：

```text
outputs/v2_audit/business_audit_daily.parquet
outputs/v2_audit/business_audit_summary.json
MATVIX_V2_AUDIT.md
```

`business_audit_daily.parquet` 是逐 session 证据账本；`business_audit_summary.json` 是机器汇总；`MATVIX_V2_AUDIT.md` 是唯一需要提交的人工缺陷结论。

### 3.1 数据完整审计

必须检查：

1. VIX/VIX9D/VIX3M/VIX6M/VVIX/SKEW/SPX 和 VX 标准月合约的 session 覆盖、重复、非正值、方法版本与 vintage；
2. 每日 F1–F7 是否连续可选，缺失发生在原始文件、解析、合约资格还是公式层；
3. `VXCM30` 合法 30 日夹逼合约、月度换月、89/165 等旧线索是否能在干净 V1 独立复现；旧数字不是预期答案；
4. 原始缺口对 `VXCM30`、`basis30_eod`、5日变化、百分位、状态和概率 eligibility 的传播范围；
5. `data_status=OK/PARTIAL/UNKNOWN` 与全部必需字段是否一致；
6. `recent_stress`、`persistent_now`、`repair_confirmed` 等三值字段在 OK 行缺失时的合同归属；
7. `available_at <= decision_as_of`、历史 revision 选择与 `formal_vintage_eligible`；
8. 未来追加数据是否改变过去已接受的特征、状态或 OOF 结果。

数据缺失的修复优先级固定为：

```text
恢复/纠正官方原始数据或解析
→ 修复错误的合约选择/公式
→ 明确标记不可用
→ 最后才评估可审计重建
```

任何重建值不得伪装成直接官方 observation；没有明确方法版本、误差验证和准入合同，就只能是研究诊断，不能把 `PARTIAL` 升为 `OK`。

### 3.2 期限事实完整审计

V1 的 `Persistence` 混合 SPX IV forward vol 与 F1–F6 inversion breadth，但没有直接回答 F4–F7 当前发生什么。审计必须从原始 F1–F7 计算候选事实，先检验业务区分能力，再决定最小正式字段：

- 前端与中期限各自的 level/slope；
- F4–F7 inversion breadth；
- 中期限曲线 5日/10日变化；
- front-to-mid stress propagation；
- 压力是 `FRONT_LOCALIZED / DIFFUSING / PRICED / RECEDING` 中的哪一种。

候选公式不得围绕 VXZ 指数收益设计，也不得把 F4–F7 直接称为 VXZ 盈利信号。正式公式必须满足：跨换月含义稳定、单位清楚、缺失行为清楚、可用当前及此前数据重放。

审计需要给出各现有 `persistence_answer` 和 phase 对以下未来天气事实的 5日/10日条件分布：中期限 slope 变化、inversion breadth 变化、F4–F7 level 变化、压力扩散/衰减。重点查明 `PRESSURE_BUILDING` 是否混合了局部紧张、扩散、充分计价和衰减。

### 3.3 状态语义完整审计

逐 session 和逐事件簇检查：

- 五个 answer 是否互斥、完整并正确传播 UNKNOWN；
- `Persistence` 是否真的区分前端局部与中期限扩散；
- `Repair` 是否只代表边际下降，还是被错误解释为 carry 已恢复；
- `REPAIR_IN_PROGRESS`、`BROAD_PERSISTENT_STRESS` 与 `PRESSURE_BUILDING` 的进入/退出时点；
- phase 滞回是否造成过早释放、过慢释放或无业务意义的 churn；
- 相同状态在开发窗和确认窗是否仍对应同方向的原始期限事实。

审计可以提出但不得预先强制实现的 V2 事实字段：

```text
stress_tenor_scope = NONE | FRONT | MID | BROAD | UNKNOWN
mid_curve_pressure_state = QUIET | RISING | PRICED | RECEDING | UNKNOWN
carry_environment_state = OPEN | CLOSED | RECOVERING | UNKNOWN
```

每个新增字段必须消除一个已编号歧义；否则不增加。

### 3.4 时效完整审计

先冻结由原始价格/曲线事实构成的 event ledger，不能用待验收的 phase 自己给自己做标签。至少覆盖：

- 急性前端压力开始；
- 前端倒挂开始；
- 前端压力向 F4–F7 扩散；
- 广泛压力持续；
- 中期限压力见顶/衰减；
- carry 环境恢复。

事件以连续窗口聚类。每类报告：

```text
事件簇数量
首次预警提前量/延迟
漏报数量与严重度
每个真事件对应的误报簇
风险关闭持续时间
Repair 确认延迟
过早释放率
恢复后继续关闭的 session 数
leave-one-event-cluster-out 方向稳定性
```

交易产品损失不进入时效标签。

### 3.5 概率完整审计

对全部已发布事件逐项检查：

- 业务问题、onset、horizon、future predicate 和 label censoring；
- event-specific observable/eligible cohort；
- predictors 截止时间、训练窗、20-session purge 和 outcome availability；
- label/base-rate/raw OOF/calibrated OOF 首次可用时间；
- coverage、base rate、Brier、Brier Skill、ECE、reliability 和年度/危机分层；
- `CALIBRATED_MODEL/BASE_RATE_ONLY/INSUFFICIENT_HISTORY/NOT_RUN` 是否诚实；
- 当前事件是否缺少“中期限扩散、持续、衰减、carry 恢复”等真正业务问题。

候选新事件只能来自审计确认的缺口，例如：

```text
front_stress_diffuses_to_mid_curve_10d
broad_stress_persists_10d
mid_curve_pressure_accelerates_5d
fast_repair_5d
carry_environment_recovers_10d
```

不要求全部实现。缺少独立标签、样本或校准增量的事件必须拒绝或保持 `BASE_RATE_ONLY`，不能为了 Long probe 产生交易而放宽。

---

## 4. 阶段 B：冻结缺陷台账与 V2 规格

`MATVIX_V2_AUDIT.md` 中每个缺陷必须包含：

```text
defect_id
severity = P0 | P1 | P2
layer = DATA | TENOR | STATE | TIMING | PROBABILITY
observed symptom
reproduction command
causal evidence
business consequence
minimal repair
affected existing files
semantic/version impact
station acceptance criterion
status
```

优先级：

- `P0`：PIT/数据/未来函数/错误 OK/公式错误，阻断后续；
- `P1`：期限事实、状态语义、时效、概率缺陷，阻断 V2；
- `P2`：叙事或展示问题，只能在 P0/P1 关闭后处理。

没有 defect ID 不得改代码。审计完成后、第一行语义代码修改前，必须先更新 `MATVIX_PRE_DEVELOPMENT_REPORT.md`，冻结：

- V2 必需数据与 F1–F7 规则；
- 新增/删除的期限事实及公式；
- answer/phase/滞回/UNKNOWN 语义；
- 事件、标签、predictors 与概率版本；
- Schema、model/feature/state/probability 版本；
- 每项缺陷的站内验收准则。

规格提交必须只含文档，不修改运行配置或实现。配置与对应代码必须在同一个缺陷修复提交中保持一致。

---

## 5. 阶段 C：按缺陷分别最小修复

施工顺序固定：

1. DATA/PIT；
2. F1–F7 期限事实；
3. 状态语义与时效；
4. 概率事件与校准；
5. 必要的输出 Schema/叙事/Dashboard 兼容。

每个缺陷一个提交，提交信息包含 defect ID。每次只允许：

```text
复现失败测试
→ 最小实现
→ 聚焦测试
→ 完整站内回归
→ 更新缺陷状态和证据
```

实现优先扩展现有文件：

- 数据/PIT：`src/matvix/data/`、`features/futures_curve.py`、`features/builder.py`；
- 状态：`state/scores.py`、`state/ontology.py`、`state/transitions.py`；
- 概率：`constants.py`、`probability/targets.py`、`probability/walk_forward.py`、`probability/engine.py`；
- 输出：`output.py`、`schemas/daily_output.schema.json`；
- 配置：以 V2 配置替换 V1 配置，不保留双路径。

只允许新增一个站内业务审计模块和一个最终经济探针模块；不得新增 renderer、publication、governance、plugin 或 generic validation package。

反过度设计熔断：在固定经济探针之前，若累计新增非生成代码与测试超过 2,000 行，或新增超过 8 个跟踪文件，立即停止施工并重新做 scope-to-defect 映射。行数不是质量目标，但越线必须证明每个新增单元对应哪个当前缺陷。

---

## 6. 阶段 D：完整气象站自身验收

站内验收禁止使用产品收益。输出：

```text
outputs/v2_station_acceptance/daily_ledger.parquet
outputs/v2_station_acceptance/summary.json
outputs/v2_station_acceptance/report.md
```

不生成总分或“全部绿色”的营销徽章。五个维度分别给出 `PASS / FAIL / INSUFFICIENT_EVIDENCE`。

### 6.1 数据门

必须同时满足：

- 所有 `data_status=OK` 行的 V2 必需字段非空且 vintage 合法；
- 任一必需字段不可用时严格降级，不以 0、前填或可选字段兜底；
- F1–F7 选择、换月、30 日夹逼、比率方向有独立 golden/手算例；
- 直接、派生、重建和不可用来源不会混淆；
- 修改未来数据不改变过去 PIT 特征/状态/OOF；
- 已编号数据缺陷全部关闭。

### 6.2 期限事实门

必须同时满足：

- 新字段公式、单位、换月和缺失行为确定且可重放；
- `FRONT_LOCALIZED/DIFFUSING/PRICED/RECEDING` 对应不同的 F4–F7 当前事实；
- 开发窗与确认窗的条件 5日/10日中期限事实方向一致；
- DIFFUSING 不得只是 `Persistence` 高分或 VXZ 收益的同义词；
- 危机留一结果不出现系统性方向反转；证据不足时明确 `INSUFFICIENT_EVIDENCE`。

### 6.3 状态与时效门

必须同时满足：

- answer/phase 互斥、完整、可确定重放并传播 UNKNOWN；
- 相对 V1，原始天气事件簇漏报不增加；
- 中位首次预警不更晚；
- 误报簇不增加；
- Repair 中位延迟下降，且过早释放率不增加；
- churn 下降不能以延迟识别或长时间关闭风险为代价。

若收益机会与风险时效发生权衡，状态门为 `FAIL` 或 `INSUFFICIENT_EVIDENCE`，不能用综合分数抵消。

### 6.4 概率门

必须同时满足：

- 所有事件标签、eligibility、purge、OOF、校准和 publication 算术可重放；
- 末端不完整、未知 future predicate、非法 vintage 继续为 `CENSORED`；
- 任何发布 `FEATURE_CONDITIONAL` 的事件仍要求 Brier Skill `>=2%`、ECE `<=7%` 和既有样本门；
- 未达标事件诚实回退 `BASE_RATE_ONLY`，但不得计作概率增量；
- 新事件未通过时从正式事件集合拒绝，不留半成品字段。

### 6.5 进入经济探针的门槛

DATA、TENOR、STATE/TIMING 和 PROBABILITY INTEGRITY 必须全部 `PASS`。概率模型可以诚实为 `BASE_RATE_ONLY`，但这种事件不构成预测增量。任何关键维度 `FAIL/INSUFFICIENT_EVIDENCE` 时停止，不运行产品回测。

---

## 7. 阶段 E：SVXY + SGOV + VXZ 固定经济探针

### 7.1 统一适配器

适配器只读取 V1/V2 共同稳定接口中的：

```text
session_date
decision_as_of
data_status
market_story.answers.carry
market_story.answers.shock
market_story.answers.persistence
```

不得增加按版本分支或 normalization layer。固定事实谓词：

```text
SHORT_ALLOWED =
    data_status == OK
    AND carry == SUPPORTIVE
    AND shock == CALM
    AND persistence == NORMAL

MID_DIFFUSION_CONFIRMED =
    data_status == OK
    AND persistence == DIFFUSING
```

固定探针：

```text
Short probe:
    SHORT_ALLOWED -> 100% SVXY
    otherwise     -> 100% SGOV

Long probe:
    MID_DIFFUSION_CONFIRMED -> 100% VXZ
    otherwise               -> 100% SGOV

Combined probe, precedence from high to low:
    data_status != OK       -> 100% SGOV
    MID_DIFFUSION_CONFIRMED -> 100% VXZ
    SHORT_ALLOWED           -> 100% SVXY
    otherwise               -> 100% SGOV
```

`PERSISTENT` 代表压力已经广泛存在，不自动等于 VXZ 进攻窗口；它在固定探针中进入 SGOV。`REPAIR` 也不自动开放 SVXY，必须等共同接口重新满足 `SHORT_ALLOWED`。

### 7.2 价格、时点、成本和仓位

所有版本使用完全相同合同：

- 初始资金：`USD 10,000`；
- 资产：仅 `SVXY / SGOV / VXZ`；
- 单次 100% 持有一种资产，允许碎股；
- 研究价格源冻结为 Yahoo Finance Chart JSON API：`query1.finance.yahoo.com/v8/finance/chart/{ticker}`，请求日频 OHLC、splits 和 distributions；三只资产必须使用同一接口与同一抓取批次；
- 原始下载、请求参数、抓取时间和 SHA-256 保存到本地 manifest；
- `t` 日 EOD 天气在下一共同交易日 09:20 ET 形成，最早于 `t+1` 开盘执行；
- 使用 `adjustment_factor = adjusted_close / raw_close`、`adjusted_open = raw_open × adjustment_factor` 构造 adjusted open，并采用 open-to-open 收益；
- 新仓位只获得执行完成后的收益，三日手算例必须通过；
- 单边成本 `5 bp`：`cost = NAV_pre × 0.0005 × Σ|w_new-w_old|`；
- 初次从现金买入成本 5bp；100% A 切换到 100% B 的双边 turnover 为 2、成本 10bp；
- 资产不变不调仓；缺价格时不换提供方、不填收益，报告数据失败。

回测起点是 V1、V2、SVXY、SGOV、VXZ 及所需 adjusted-open 字段的首个共同 session。[iShares 官方资料](https://www.ishares.com/us/products/314116/)显示 SGOV 成立于 `2020-05-26`，因此它不覆盖 `2019-05-02`；不得静默拼接 BIL 或零收益现金。终点为三资产和两版气象站的最新共同完整 session。

### 7.3 唯一输出

```text
outputs/v2_economic_probe/daily_ledger.csv
outputs/v2_economic_probe/report.json
outputs/v2_economic_probe/report.html
```

逐日账本必须能审计：

```text
weather version
signal session / decision_as_of / execution session
data status / carry / shock / persistence
probe state / target asset
adjusted execution price
turnover / cost
gross return / net return
P&L / NAV / drawdown
```

HTML 只从同一账本和 `report.json` 生成一次，不建设独立发布或防御框架。交易员图表仅包括：

1. V1/V2 三个探针净值；
2. underwater 回撤；
3. 最差滚动20日收益；
4. 最差20个 SVXY 日的 V1/V2 实际资产暴露；
5. 状态与持仓时间轴；
6. 调仓次数、turnover 与成本瀑布；
7. 每个 `DIFFUSING` 事件簇的 VXZ 相对 SGOV 收益。

### 7.4 经济判定

每个探针独立分类：

- `POSITIVE`：V2 税费后终值高于 V1，最大回撤和最差滚动20日均不恶化，且至少一项风险指标改善；
- `MIXED`：收益改善但风险恶化，或风险改善但终值降低；
- `NEGATIVE`：终值降低且至少一项主要风险指标恶化；
- `NOT_ELIGIBLE`：对应气象事实没有通过站内验收或没有可评价事件簇。

调仓次数下降不是独立成功标准。只有所有 eligible 探针均为 `POSITIVE`，才可以表述“V2 在固定探针上产生全面经济增量”。任何一个 `MIXED/NEGATIVE` 都必须逐日归因，不能调整适配器后重跑。

---

## 8. 缺陷 loop 与停止条件

唯一合法 loop：

```text
原始业务异常
→ defect_id
→ 数据/期限/状态/时效/概率根因
→ 规格修订
→ 单项最小修复
→ 气象站自身验收
→ 若失败，只返回同一 defect_id
```

所有站内门通过后才运行一次冻结经济探针：

```text
固定经济探针失败
→ signal/position/price/cost/P&L 归因
→ 只有证据指向气象事实缺陷时才新建 defect_id
→ 不改变仓位、资产、阈值、成本或滞后
```

以下情况必须停止而不是继续加代码：

- 无法用干净 V1 复现旧缺陷；
- 原始数据权利或 PIT 证据不足；
- 修复只能依靠未标记的合成值；
- 需要从产品收益反推天气阈值；
- 关键站内维度为 `INSUFFICIENT_EVIDENCE`；
- 代码量触发反过度设计熔断；
- 第二次修复仍无法关闭同一缺陷。

---

## 9. 提交与最终交付顺序

建议提交边界，不允许合并成一个巨大提交：

1. `audit: record MatVIX V1 business defects`；
2. `docs: freeze MatVIX V2 semantic delta`；
3. `fix(v2): close DATA-* defects`；
4. `feat(v2): add accepted tenor facts`；
5. `fix(v2): close STATE/TIMING-* defects`；
6. `fix(v2): close PROBABILITY-* defects`；
7. `test(v2): complete weather-station self-acceptance`；
8. `test(v2): run frozen SVXY SGOV VXZ probes`；
9. `docs: record MatVIX V2 verdict`。

每个提交后检查 diff 和引用；每个功能提交运行聚焦测试。最终必须运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src/matvix
.venv/bin/python -m matvix doctor --project-dir .
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real --project-dir .
git diff --check
git status --short --branch
```

如果 V2 通过所有气象站门和固定经济探针，才允许合并到 `main` 并推送；否则保留开发分支和明确失败结论，不推广、不美化为 ready。

最终报告必须直接回答：

1. V1 原始缺陷是什么；
2. 每个缺陷改了什么、没有改什么；
3. 气象站五维验收各自结论；
4. V1 与 V2 的固定探针经济增量；
5. 尚未验证或被拒绝的业务能力。

---

## 10. 新 session 的第一条执行指令

```text
逐字阅读 /Users/logan/MatVIX/MATVIX_V2_CONSTRUCTION_PLAN.md。
把它作为下一轮唯一施工合同。先验证干净 main 与正式 V1 基线，
再创建 codex/matvix-v2 分支。严格完成阶段 A 的五维业务审计；
审计期间不得读取 SVXY、SGOV、VXZ 价格，不得恢复隔离包，
不得编写策略、HTML 发布框架或 V1.1 路径。只有缺陷台账与 V2
语义规格冻结后，才按 defect_id 分别施工。
```
