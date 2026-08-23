# MatVIX V3 外部策略器消费合同

文档状态：`FINAL_FROZEN / SINGLE_EXTERNAL_CONSUMER_AUTHORITY`

适用对象：读取 MatVIX 的外部策略器、回测器、纸盘系统和 AI agent。

产品状态：`READ_ONLY_RESEARCH_WEATHER_STATION / NO_TRADING_AUTHORITY / HISTORICAL_CORE_ACCEPTED / PROSPECTIVE_CONFIRMATION_PENDING`

本文件是唯一的外部消费说明，同时记录 MatVIX V3 的最终冻结边界和 Prospective 001 P6
当前事实。它不创建策略，不提供仓位、下单、杠杆、持有期或风险预算。

本文中的“必须”“禁止”“仅”是消费合同。若外部策略无法满足某项前置条件，默认结果是
`ABSTAIN_DATA`，不得由 AI 临场补阈值、猜测缺失值或制造交易。

## 1. 最终冻结身份

- 科学核心：tag `matvix-v3.0.1`，peeled commit
  `63ea5900e7eab0b0c91a74e18eea361fdebe6e7d`。
- Prospective 激活：annotated tag `matvix-prospective-001-activation`，peeled commit
  `ce7d325dfe7c2b3490d2bfe73ef3c4d108873da6`。
- 全仓最终冻结：annotated tag `matvix-v3-final-freeze-2026-08-24`。该 tag 所指 commit/tree
  是本文件、运行记录器和全部仓库字节的最终身份，避免在文档内写自引用 commit hash。
- 产品身份：`model_id=MATVIX_CBOE_CORE_V3`。
- `schema_version=feature_version=state_version=probability_version=3.0.0`。
- Prospective scientific cohort：`MATVIX_V3_0_1_CORE`，Schema `1.0.0`。

V3 仓库从最终冻结 tag 起不再修改。配置、Schema、科学代码、记录器、合同和说明文档均属
冻结字节；未来若要改变任何语义，必须建立新版本/新 cohort，不得原地修补 V3。

冻结不等于停止日常运行。原始行情、本地 processed 数据、accepted snapshot/receipt、日志、
Prospective prediction/outcome 会按既有合同继续产生；这些是运行证据追加，不是修改 V3。

Prospective 001 的 P1–P5 已验收，P6 已完成合并、activation tag 和远端推送。冻结检查时
正式 Core prediction/outcome 仍为零，状态继续是 `PROSPECTIVE_CONFIRMATION_PENDING`；首条
样本只能来自 activation 后的自然 passing receipt，禁止回填。

## 2. 文档口径与保留理由

下列文件不是重复的当前说明，而是不同层级的不可替代证据：

- `MATVIX_PROSPECTIVE_001_POWER_DESIGN.md`：P0 当时的 pre-freeze 研究记录；其中
  `NOT_FROZEN`、尚无 writer/tag 等表述只描述 P0 时点。
- `MATVIX_PROSPECTIVE_001_CONTRACT.md`：人类冻结的 Prospective 协议；其原字节由 P5
  报告中的 SHA-256 绑定。
- `MATVIX_PROSPECTIVE_001_ACCEPTANCE.md`：P5 当时的验收记录；其中
  `READY_FOR_P6_ACTIVATION` 和 tag 尚未创建只描述 P5 时点。
- `README.md` 与各数据目录 README：安装、运行或目录索引，不另行定义消费语义。

当前 P6、最终冻结和外部消费口径只读本文件。不得把历史报告中的阶段状态覆盖为“当前
事实”，也不得改写历史证据来消除表面上的时间差。

## 3. 权威读取面

| 使用场景 | 读取对象 | 权威含义 |
|---|---|---|
| 日常/纸盘控制面 | `GET http://127.0.0.1:8788/api/status` | 运行、发布、数据新鲜度和 Prospective 采集健康；不是交易信号 |
| 日常/纸盘天气 | `GET http://127.0.0.1:8788/api/snapshot` | 服务端已验证 passing receipt 与 exact snapshot bytes 后返回的最新 last-good V3 JSON |
| 本机离线天气 | `outputs/daily/YYYY-MM-DD.json` 与 `artifacts/acceptance/real_acceptance_YYYY-MM-DD.json` | 两者必须成对且 receipt 的 `publication_binding` 必须匹配文件 SHA-256、字节数和 session；单独 JSON 不是正式发布 |
| 历史状态回测 | `data/processed/states.parquet` | 一行一 XNYS session 的因果特征与已发布状态历史；必须由同代 passing acceptance/receipt 与配置身份验证 |
| 历史概率研究 | `data/probability/oof_ledger.parquet` 与 `artifact_contract.json` | 顺序、purged、因果 OOF 模型/校准账本；不是“当年真实 live receipt 档案” |
| 结果审计 | `data/probability/target_ledger.parquet` | 事件 eligibility、horizon、结果可得时点和最终 label；只准在 `outcome_available_at` 后用于审计 |
| 气象站验收 | `outputs/v3_station_acceptance/` 与 `MATVIX_V3_RELEASE_MANIFEST.json` | 科学/数据/边界验收证据；不产生策略信号 |
| Prospective 实发证据 | `data/prospective/core/predictions/YYYY-MM-DD.json` | activation 后自然发布的 exact prediction，绑定 snapshot hash |
| Prospective 结果 | `data/prospective/core/outcomes/YYYY-MM-DD/EVENT_ID.json` | 到期后追加的 outcome，绑定原 prediction；只用于事后统计/审计 |

Dashboard HTML、截图、`/healthz`、日志、`outputs/runtime/update_status.json` 和 HTTP 200 仅是
显示或控制面证据，均不能代替 accepted snapshot。

## 4. 日常/纸盘读取流程

外部 agent 每次决策必须按以下顺序执行：

1. 读取 `/api/status`。连接失败、JSON 无效或 `product_status=BLOCKED` 时返回
   `ABSTAIN_DATA`。
2. 验证 `trading_authorized` 严格为 `false`。这证明接口没有越权，不代表“允许交易”。
3. `product_status=READY` 只表示发布健康。`DEGRADED` 必须逐项读取
   `product_status_reasons`；若外部策略没有预先冻结的 reason-specific 处理规则，返回
   `ABSTAIN_DATA`。例如 `EVIDENCE_CAPTURE_GAP` 不改变当日天气 bytes，但也不能被解释为
   新的交易许可。
4. 读取 `/api/snapshot`，用 `schemas/daily_output.schema.json` 验证完整 JSON，并验证：
   - `model_id` 与四个版本字段完全等于第 1 节冻结值；
   - `data_status=OK`；
   - `session_date == /api/status.latest_snapshot_session`；
   - `session_date` 是策略本次决策预先要求的来源 session；
   - 当前决策时间不早于 snapshot 的 `decision_as_of`；
   - `issues` 没有命中外部策略预先冻结的拒绝条件。
5. 新鲜度由外部策略事先定义。HTTP 服务可能诚实保留 last-good；不得因为服务返回 200
   就把旧 session 当成当天数据。没有预定义 stale policy 时，session 不匹配即
   `ABSTAIN_DATA`。
6. 把 snapshot 原文或其 SHA-256、session、`decision_as_of`、版本和策略自身版本写入外部
   决策账本，然后才允许策略规则计算。MatVIX 仓库不得由外部 agent 写入。

读取本地文件而非 API 时，还必须验证 passing receipt：

```text
receipt.passed == true
receipt.session_date == snapshot.session_date
receipt.publication_binding.binding_version == "SNAPSHOT_SHA256_V1"
receipt.publication_binding.snapshot_sha256 == sha256(exact snapshot bytes)
receipt.publication_binding.snapshot_size == len(exact snapshot bytes)
receipt mtime >= snapshot mtime
```

任一条件不满足，文件只是 candidate/artifact，不是正式天气发布。

## 5. 策略可消费的核心字段

### 5.1 身份、时间和数据门

必须整体保留：

- `model_id`
- `schema_version`、`feature_version`、`state_version`、`probability_version`
- `input_manifest_hash`
- `session_date`
- `decision_as_of`
- `data_status`
- `issues`

### 5.2 当前天气状态

稳定的策略输入面是：

- `market_story.phase`
- `market_story.pressure_level`
- `market_story.direction`
- `market_story.structure.stress_tenor_scope`
- `market_story.structure.mid_curve_pressure_state`
- `market_story.structure.carry_environment_state`
- `market_story.answers.carry|shock|tail|persistence|repair|outlook`
- `market_story.scores.carry_risk|shock|tail_price|persistence|repair`

`phase` 是带确认规则的正式发布相位；历史表中存在 `raw_phase` 时，策略只准用 `phase`。
五轴分数是天气量尺，不是仓位百分比、杠杆或损失概率。`outlook` 是事件摘要，也不是买卖
方向。

### 5.3 五个概率事件

| event_id | horizon | 语义 | 正式消费规则 |
|---|---:|---|---|
| `acute_front_stress_5d` | 5 sessions | 急性前端压力出现 | 仅消费合格条件概率 |
| `front_inversion_5d` | 5 sessions | 前端曲线倒挂出现 | 仅消费合格条件概率 |
| `mid_curve_pressure_accelerates_5d` | 5 sessions | 中段压力加速 | 仅消费合格条件概率 |
| `broad_stress_persists_10d` | 10 sessions | 广泛压力持续 | 永远只是 BaseRate 历史参考，不是模型 edge |
| `carry_environment_recovers_10d` | 10 sessions | carry 环境恢复 | 仅消费合格条件概率；这是恢复事件，不是风险事件 |

四个条件事件只有同时满足下列条件时，`probability`、`base_rate`、`uplift` 才属于正式条件
判断：

```text
event_status == "ELIGIBLE"
model_status == "CALIBRATED_MODEL"
probability_kind == "FEATURE_CONDITIONAL"
probability, base_rate, uplift 均非 null
```

其中 `uplift = probability - base_rate`。外部策略必须按 event_id 分别解释，禁止把五个概率
简单相加为“风险分数”。

Broad 仅在 `ELIGIBLE / BASE_RATE_ONLY / HISTORICAL_REFERENCE` 时可作为背景发生率；其
`uplift=0` 不代表安全，也不代表模型失败。条件事件若回退为 `BASE_RATE_ONLY`，只说明没有
可发布的特征增量，禁止把该概率冒充模型 edge。

`NOT_APPLICABLE` 表示当前转移问题不适用，`UNOBSERVABLE` 表示输入不足；二者都不是零概率。
`IDENTITY_WARMUP`、`INSUFFICIENT_HISTORY`、`NOT_RUN` 不属于默认策略可用的合格条件模型。

`valid_through_session` 是事件标签的结果 horizon，不是持仓到期日，也不授权在未来几天反复
使用一份旧 snapshot。策略仍应每天重新读取 accepted publication。

### 5.4 只作解释的字段

`headline`、`narrative`、`drivers`、`counter_evidence`、`repair_evidence`、
`structural_triggers`、`what_changes_the_view` 和每个事件的 `interpretation` 供人类解释。
AI 可以引用它们解释已由结构化字段作出的判断，但禁止解析自然语言生成独立买卖信号。

`observations` 与 `diagnostics` 用于透明审计和故障定位，不是冻结的最小策略接口。外部策略
若要直接使用 VIX、VX、SKEW、技术指标或 component contribution，必须在自己的独立数据/
策略合同中定义，不能声称那是 MatVIX 已授权的策略映射。

## 6. 历史回测与审计

### 6.1 状态回测

从 `data/processed/states.parquet` 读取并至少保留：

- `session_date`
- `data_status`
- `formal_vintage_eligible`
- 正式 `phase`、`pressure_level`、`direction`
- `stress_tenor_scope`、`mid_curve_pressure_state`、`carry_environment_state`
- `carry_answer`、`shock_answer`、`tail_answer`、`persistence_answer`、`repair_answer`
- 五轴正式 score

默认信号样本只允许 `data_status=OK` 且 `formal_vintage_eligible=true`。`PARTIAL`、`UNKNOWN`、
缺行和非正式 vintage 必须保留为 `ABSTAIN_DATA/UNKNOWN`，禁止前填、后填或用 Close 替代
无效 VX Settle。

任何历史交易时间必须不早于该 session 对应的冻结 `decision_as_of`。不得把 EOD 天气应用到
同一个 session 的收盘成交；价格、成交、成本和滑点必须来自外部策略自己的因果数据源。

### 6.2 概率回测

`oof_ledger.parquet` 的 `raw_probability`、`published_probability`、
`base_rate_at_prediction` 和校准字段是逐日顺序、purged 的 OOF 科学账本。它可用于
`CAUSAL_OOF_RESEARCH`，但字段名 `published_probability` 不证明当日曾有 live receipt，也
不单独证明当日运行时 publication gate 最终选择了条件模型。

若回测声称“严格复现正式 MatVIX 日报”，必须在冻结 tag 和锁定依赖下按每个 prediction
date 调用完整 V3 snapshot/policy replay，并让输出通过 daily Schema；不能仅把 OOF 列改名为
live signal。自然 forward 审计则优先读取 Prospective prediction record 中的
`published_probability`。

历史 join key 是：

```text
states.session_date == oof.prediction_date
并按 event_id 分行
```

信号侧不得 join `label`。结果侧只有在 `outcome_available_at <= audit_as_of` 后才能读取
`label` 和 `label_status`。

### 6.3 结果和 Prospective 审计

- `target_ledger.parquet` 是历史目标/结果账本，不是特征表。
- Prospective prediction 的 `published_probability` 是产品实际发布值；
  `candidate_probability` 仅属 shadow science，严禁进入策略。
- Prospective Outcome 只能在完整 horizon 到期后用于评估；`first_event_session`、`label`、
  `resolved_late` 都是事后字段。
- prediction 缺失或 `EVIDENCE_CAPTURE_GAP` 永不回填。缺口必须保留，不能用后来的 snapshot
  或 OOF 重建。

外部策略的最小可审计链必须独立保存：

```text
accepted snapshot/prediction identity
-> strategy rule/version
-> intended position
-> causal execution price/fill
-> fee/slippage/cost
-> P&L
-> NAV and drawdown
```

气象站只负责链条第一项。没有成交或价格证据时应记录 `KNOWN_BLOCK` 或 `ABSTAIN_DATA`，不得
伪造交易。

## 7. 严格禁止消费的内容

外部策略或 AI agent 严格禁止：

- 把 MatVIX 当成订单、仓位、方向、仓位大小、杠杆、止损、交易许可或收益保证。
- 把 `/api/status` 的 `READY/DEGRADED/BLOCKED`、HTTP 200、LaunchAgent 存活或 Dashboard
  绿色界面当成买卖信号。
- 读取未被 passing receipt 绑定的 candidate snapshot，或把 last-good 默认为最新 session。
- 把 `PARTIAL/UNKNOWN`、null、`NOT_APPLICABLE`、`UNOBSERVABLE` 转为 0、沿用上一日、插值
  或强行生成仓位。
- 使用 `raw_phase`、candidate phase/state、`raw_probability`、Prospective
  `candidate_probability`、calibration intercept 或 diagnostics 建立未经独立冻结的隐藏策略。
- 把 Broad 的 BaseRate 说成条件模型，把 fallback BaseRate 说成 model PASS，或把
  `valid_through_session` 说成持仓期限。
- 在信号时点读取 `target_ledger.label`、`outcome_available_at` 之后才知道的结果、
  `first_event_session`、任何 `fwd*` 列或 Prospective Outcome。
- 消费 `outputs/v3_economic_probe/`、`data/prospective/v3_fragility_shadow_ledger.csv`、
  `calm_carry_breaks_5d`、被拒绝的 Fragility adapter、SVXY/SGOV/VXZ 结果作为 V3 正式天气
  或交易许可。
- 从 Stage-D comparator、acceptance report、P0 power study、测试结果或 release status 反推
  当日交易方向。
- 混合不同 model/schema/cohort，修改冻结阈值，看到回测或 outcome 后回调规则，或补录历史
  prospective 样本。
- 修改 MatVIX V3 仓库、配置、Schema、合同、冻结 tag 或运行证据。策略逻辑必须放在外部
  项目；需要改变气象站时另开新版本。

## 8. 外部 AI agent 的最小决策模板

```text
1. status 不可读或 BLOCKED -> ABSTAIN_DATA
2. DEGRADED 且没有预冻结的 reason policy -> ABSTAIN_DATA
3. snapshot 身份/版本/Schema/data_status/session/decision_as_of 任一失败 -> ABSTAIN_DATA
4. 只提取正式 phase/structure/answers/scores
5. 每个 event 单独验证 eligibility + model_status + probability_kind
6. 不可用事件 -> UNKNOWN，不填 0，不沿用旧值
7. 把 weather observation 交给外部、已版本化的 strategy policy
8. 保存 weather -> position -> price -> cost -> P&L -> NAV 全链
9. 永远保留 trading_authorized=false 和 MatVIX 无交易权限的边界
```

若 agent 无法证明它读到的是哪一个 session、哪个冻结版本、哪份 accepted bytes，结论只能是
`ABSTAIN_DATA`。

## 9. 最终冻结验收记录

冻结日期：`2026-08-24`。

- Git：Prospective 分支提交 `ce7d325` 已是最终 `main` 的祖先；最终提交、
  `origin/main` 与 `matvix-v3-final-freeze-2026-08-24^{commit}` 必须相同。activation tag
  继续固定在 `ce7d325`，不因最终文档提交而移动。
- 文档：Prospective 目录中“未施工、无 Schema、无 activation tag”的漂移已修正；本文件是
  唯一当前消费说明。P0、冻结合同、P5 报告按时点证据保留，未伪造事后状态。
- 冻结原件：Prospective 合同 SHA-256 仍为
  `f4cc9a4eac67b14783b04dbe12541a1e9203127513af69e54b46eb7762f1b19c`，P0 Power Design
  仍为 `956dd5c0e022a76f251498f2f94869f19b8c4f63edebfb6dc8f363f09472dc56`；科学 release
  manifest 与 `matvix-v3.0.1` 中的原件 byte-identical。
- 代码质量：pytest `268 passed`（仅一条既有 pandas `FutureWarning`）、Ruff PASS、Mypy
  PASS（47 个 source files）、doctor 的全部锁定依赖 PASS。
- 真实数据：`accept-real --date 2026-08-20` 的 14 个 gate 全部 PASS，receipt 为
  `Already current`。
- 气象站自身：`DATA / TENOR / STATE_TIMING / PROBABILITY_INTEGRITY /
  PROBABILITY_MODEL / BASE_RATE_REFERENCE / FRAGILITY_BOUNDARY / STAGE_E_ENTRY` 全部 PASS。
- 冻结证据：OOF、Target、Stage-D、经济探针与验收产物的 SHA-256 均保持 P5 记录值；没有
  用策略收益修补天气信号。
- 运行烟测：重载旧常驻 Dashboard 进程后，`/api/status` 为
  `RUNNING / READY / trading_authorized=false`，并已暴露 cohort、prediction/outcome、gap
  等 `prospective_evidence` 字段；`/api/snapshot` 仍返回 accepted V3 `3.0.0`、
  `data_status=OK` 的 last-good。
- 文档清理：未发现可删除的 tracked 垃圾文档。三份 Prospective 文件分别是 P0 科学证据、
  冻结合同和 P5 验收证据，删除或合并会破坏审计链；目录 README 仅保留索引/操作职责。
  `.pytest_cache/README.md` 等 ignored cache 不是仓库文档，`outputs/v3_station_acceptance/report.md`
  是本地验收证据，均不进入“重复说明文档”口径。

任一未来检查若不满足以上身份或质量门，只能停止消费或建立新版本；不得移动冻结 tag、
修改本文件或降低 V3 门槛。
