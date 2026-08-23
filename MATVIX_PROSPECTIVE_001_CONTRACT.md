# MATVIX PROSPECTIVE 001 施工合同（草案）

状态：`READY_FOR_HUMAN_REVIEW / NOT_EXECUTED`

本合同只建设 MatVIX V3 的本地 prospective 证据记录。它不修改气象站模型、事件、
特征、阈值、历史验收、经济探针结论，也不授予交易权限。

在本合同经人类明确冻结前，不得编写运行代码、创建激活标签或产生正式 prospective
样本。

## 1. 产品边界

Prospective 001 只回答：MatVIX 在不知道未来结果时，当天实际发布了什么；5/10 个
交易日后，对应事件是否发生。

正式记录范围仅包含当前五个 V3 概率事件：

- `acute_front_stress_5d`
- `front_inversion_5d`
- `mid_curve_pressure_accelerates_5d`
- `broad_stress_persists_10d`（仅 `BASE_RATE_ONLY` 参考）
- `carry_environment_recovers_10d`

`calm_carry_breaks_5d` 与已拒绝的 Fragility 经济适配器不属于本项目的正式概率事件；
现有反事实 CSV 不得混入 Core prospective 样本。

本项目继续保持：

- `READ_ONLY_RESEARCH_WEATHER_STATION`
- `NO_TRADING_AUTHORITY`
- `HISTORICAL_CORE_ACCEPTED`
- `PROSPECTIVE_CONFIRMATION_PENDING`

## 2. 激活边界与禁止回填

科学根仍为 `matvix-v3.0.1`，peeled commit 为
`63ea5900e7eab0b0c91a74e18eea361fdebe6e7d`。

最终合同、实现和验收通过后，另建唯一 Prospective activation tag。首条正式样本是该
tag 之后发布的第一份 passing receipt。tag 之前的所有 snapshot/receipt 均属于历史，
不得转写、推算或补录为 prospective prediction。

若合同讨论或施工期间出现新的正式 receipt，只记录为 `PRE_ACTIVATION`，不得为了制造
“零缺口”而回填。

## 3. 最小本地记录

本项目不建设数据库、全局 hash chain、WORM 存储、签名密钥或外部服务。

本地权威由两类独立 JSON 文件构成：

1. `PREDICTION_PUBLISHED`
   - 每个 accepted session 一个文件；
   - 保存 session、`decision_as_of`、本地发布时间、snapshot SHA-256、事件状态、模型
     状态、概率、causal BaseRate、有效期和科学版本；
   - receipt 保存该 prediction 文件的相对路径、SHA-256 和字节数。
2. `OUTCOME_RESOLVED`
   - 每个需要解析的 event 一个新文件；
   - 引用原 prediction SHA-256；
   - 保存固定 horizon、`valid_through_session`、`outcome_available_at`、标签、实际解析
     时间和 target-ledger digest；
   - 不修改 prediction 文件。

文件写入规则：

- 只允许 exclusive create；
- 完整写入后刷新到磁盘并设为只读；
- 相同内容重跑为幂等；
- 同一逻辑路径出现不同内容时停止覆盖并报告冲突；
- CSV、mtime 和 Dashboard 页面均不是证据权威。

Prediction 记录不复制受限原始行情，也不包含 SVXY/SGOV/VXZ、经济探针或交易仓位。

## 4. Receipt 是最终发布点

正式顺序固定为：

1. 运行现有 V3 candidate 与真实数据验收；
2. 持久化 exact snapshot；
3. 写入本地 prediction 文件；
4. receipt 绑定 snapshot 与 prediction 的 SHA-256，并最后发布；
5. Dashboard 只读取 passing receipt 所绑定的两份内容。

Receipt 中 prospective 状态仅有：

- `LOCAL_CAPTURED`
- `EVIDENCE_CAPTURE_GAP`
- `PRE_ACTIVATION`

本地 prediction 写入失败时，当前天气事实仍可发布，但 receipt 必须写
`EVIDENCE_CAPTURE_GAP`，Dashboard 总体显示 `DEGRADED`，且该 session 永远不得补写
prediction。

若 snapshot 或 receipt 自身无法可靠写入，则没有新的正式 publication，继续保留
last-good。

本合同不调用时间戳服务、不向网盘复制、不自动 Git commit/push，也不调用 Telegram、
微信或任何机器人。未来若需要外部旁证，必须另立独立合同，且不得回填此前样本。

## 5. Outcome 解析

每次成功日更先检查已经 receipt-bound 的 prediction，再解析已到期事件。

只有同时满足以下条件才可写 `OUTCOME_RESOLVED`：

- 原 prediction 文件存在且 SHA-256 与 receipt 一致；
- event 当日为 `ELIGIBLE`，并存在固定的 `valid_through_session`；
- 当前时间不早于原记录的 `outcome_available_at`；
- target ledger 中 event、prediction session、horizon、valid-through 完全一致；
- label 为完整可观察的 `OBSERVED_0` 或 `OBSERVED_1`。

断源时 outcome 保持 pending。数据恢复后，允许对已有 prediction 延迟解析，但必须保留
计划时间、实际时间和 `resolved_late=true`；不得使用原 valid-through 之后的信息重定义
标签。

缺失 prediction 永远不能补写。Outcome 冲突也不得覆盖，必须停止并进入人工审计。

## 6. Scientific cohort

Cohort 冻结的是科学生成规则：事件标签、特征集、训练窗口、purge、超参数、校准、
fallback、配置 digest 和影响概率的代码。

按冻结算法因果更新的每日 Logistic 系数、rolling intercept 与 causal BaseRate 不构成
cohort 变化。任何科学生成规则变化必须先开新 cohort；纯 Dashboard 或记录器修复在证明
预测字节不变后可保留 cohort。

每条 prediction 同时保存 scientific cohort id 与运行 release id，不跨 cohort 合并正式
统计。

## 7. Power/evidence 合同待冻结项

以下评估方法现在先冻结，不得看到 prospective 结果后更改：

- 主指标：相对同日 causal BaseRate 的 paired Brier Skill；
- 次指标：paired Log Loss、calibration intercept/slope、ECE；
- 重叠 horizon 不按独立逐日样本处理；使用预定义 episode/block 聚类与 bootstrap；
- 报告正负 outcome、独立 stress/carry episode、lead time、false-alarm duration、模型
  coverage 与 capture-gap rate；
- Broad 只作为 BaseRate reference，不计算相对自身的 Skill；
- 只在固定半年度审查日正式查看统计结果，日常只监控写入完整性。

最终最小日历跨度、正负类别数、独立 episode/block 数、置信区间算法和
`CONFIRMED / CONTRADICTED / INCONCLUSIVE` 门槛尚未冻结。施工前必须先用冻结前历史
ledger 做一次只读 power 设计；它只决定前向证据需求，禁止改变模型或根据经济收益选择
门槛。Power 结果须由人类写入本合同并再次明确批准。

在该节所有数字仍缺失时：

- 可以讨论 Schema 与测试方案；
- 不得施工运行 writer；
- 不得创建 activation tag；
- 不得产生可计入正式验收的 prospective 样本。

## 8. 计划施工阶段（尚未授权）

1. `P0 POWER DESIGN`：只读历史 power/cluster 可行性报告，人类冻结第 7 节数字。
2. `P1 LOCAL RECORD`：Prediction/Outcome Schema 与只读 exclusive writer。
3. `P2 RECEIPT BINDING`：receipt-last、幂等和同 session 冲突保护。
4. `P3 RESOLVER`：5/10-session outcome 自动解析与 pending/late 语义。
5. `P4 RUNTIME`：Dashboard 显示 capture 状态、cohort、待解析数和 gap 数。
6. `P5 ACCEPTANCE`：故障测试、全量质量门、真实数据不变性检查。
7. `P6 ACTIVATION`：合并 main、创建 activation tag、推送后等待首条自然 receipt。

每一阶段不得修改 V3 模型或用 prospective/经济结果回调信号。

## 9. 最终验收条件

施工后的验收至少包括：

- 预测文件 exclusive-create、只读、hash 可复算；
- receipt 精确绑定 snapshot 与 prediction；
- identical rerun 不产生新证据；
- same-session 不同内容拒绝覆盖；
- prediction gap 永不回填；
- due/pending/late outcome 符合冻结 horizon；
- 文件损坏、重复实例、重启和 last-good 测试通过；
- Dashboard 正确区分 `LOCAL_CAPTURED / EVIDENCE_CAPTURE_GAP / PRE_ACTIVATION`；
- 完整 pytest、Ruff、Mypy、doctor、真实数据 acceptance 通过；
- V3 正式概率、历史 Stage D 和经济探针证据保持不变；
- 仍为 `READ_ONLY / NO_TRADING_AUTHORITY / PROSPECTIVE_CONFIRMATION_PENDING`。

本合同当前只供人类审查，不是施工授权。
