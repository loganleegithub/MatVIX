# MATVIX Prospective 001 — P0 Power Design

状态：`P0_COMPLETE / RECOMMENDATION_ONLY / NOT_FROZEN`

结论先行：可以继续保留 Prospective 001 方向，但**现在仍不得施工 writer 或创建
activation tag**。历史证据否定了“积累 252/504 条重叠逐日预测便具有充分统计功效”这一
想法。504 条可作为最低证据完整性门，不能表述为 80% power。

若真实 Brier Skill 仅等于历史准入下限 2%，在 5/10 日标签高度重叠和事件簇依赖下，四个
条件模型达到单侧 5% 显著性、80% power 的估计时间约为 **100、259、166、671 年**。
这些数值不是等待计划，而是可行性否决证据：Prospective 必须允许诚实的
`INCONCLUSIVE`，不能为了在 2–3 年内得到绿灯而把日行当作独立考卷或事后改门。

P0 建议冻结一个最低完整性门，并在达到该门后的唯一预定审查点做 cluster-bootstrap
裁决。强效应若真实持续，可以较早形成证据；边界效应长期无法区分时，结论就是
`INCONCLUSIVE`。

## 1. 边界与输入身份

本次只读：

- `data/probability/oof_ledger.parquet`
- `data/probability/target_ledger.parquet`
- `outputs/v3_station_acceptance/daily_ledger.parquet`

未读取 SVXY、SGOV、VXZ，未读取 `data/raw/economic_probe` 或
`outputs/v3_economic_probe`，未使用收益、仓位或交易成本。未修改模型、特征、阈值、
配置、Schema、合同数字或运行代码。

| 输入 | 行数/会话 | bytes | SHA-256 |
|---|---:|---:|---|
| OOF ledger | 7,710 | 414,812 | `330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820` |
| Target ledger | 16,670 | 120,963 | `fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913` |
| Stage-D calendar ledger | 3,334 | 49,423 | `24de7e129cf2349bc18bc3aef697986af4c77184ea017c7dc2ad9423b049a7ef` |

复算程序为 `analysis/prospective_001_power_design.py`。它只向 stdout 输出 JSON，并先验证
OOF 与 target ledger 的事件、日期、标签状态、已解析标签和 outcome availability 完全
一致。

## 2. 统计对象

### 2.1 不能混为一个对象的两种概率

Prospective record 应最少区分：

1. `published_probability`：当天对产品实际发布的概率；失去资格时等于 causal BaseRate；
2. `candidate_probability`：当天因果计算得到的 rolling-intercept 条件模型概率；即使产品
   因过去 252 条验收失败而诚实回退，也作为无交易权限的 shadow science 字段保存；模型
   未成功计算时为 null。

这是记录语义修复，不是模型修改。若 P1 只保存一个模糊的 `probability`，未来会无法区分：

- 模型本身是否有增量信息；
- 产品的 fallback policy 是否可靠；
- Skill 下降究竟来自模型失效还是模型根本没有发布。

因此建议使用两个预先声明的 estimand：

- **Core model estimand**：`candidate_probability` 相对同日 causal BaseRate 的 paired score；
- **Publication-policy estimand**：所有实际 `published_probability` 相对 causal BaseRate 的
  paired score，并单独报告 `CALIBRATED_MODEL` coverage。

Core model estimand 是正式科学裁决对象；publication-policy estimand 是产品可靠性诊断，
不得拿 fallback 产生的零差异替代模型通过。Broad 始终只有 BaseRate reference，不计算
Skill。

### 2.2 成熟历史样本

四个条件模型只使用已完成、`ROLLING_INTERCEPT_252` 的因果 OOF。Broad 使用其全部已完成
`NOT_APPLICABLE` BaseRate rows。

| 事件 | 年跨度 | resolved | 正例 | 负例 | 正 episode | 负 horizon block |
|---|---:|---:|---:|---:|---:|---:|
| `acute_front_stress_5d` | 8.99 | 1,686 | 256 | 1,430 | 42 | 268 |
| `front_inversion_5d` | 8.41 | 1,289 | 163 | 1,126 | 30 | 217 |
| `mid_curve_pressure_accelerates_5d` | 9.04 | 1,284 | 556 | 728 | 88 | 174 |
| `carry_environment_recovers_10d` | 8.49 | 1,437 | 457 | 980 | 39 | 86 |
| `broad_stress_persists_10d` | 6.14 | 267 | 109 | 158 | 18 | 43 |

episode/block 在看到 prospective 结果前定义如下：

- 正 episode：相邻正标签 origin 之间若不超过该事件 horizon 个 XNYS session，则属于同一
  episode；只有连续 horizon 个 session 没有正标签才关闭；
- 负 horizon block：从 activation session 锚定的不重叠 5/10-session block；block 内至少
  一条已解析 eligible prediction 且没有正标签，才计一个负 block；
- 缺失或 capture gap 不制造正例、也不计作已解析负例。

## 3. 依赖处理与 power 方法

主分析以 20 个 XNYS session 为不重叠 calendar block。20 等于最大 10-session horizon 的
两倍；10 与 40 只作结构敏感性检查，不用于挑选更好结果。

对于每条预测：

\[
d_t=(y_t-p_{base,t})^2-(y_t-p_{model,t})^2
\]

正值代表模型改善。Brier Skill 使用损失总和之比：

\[
Skill=\frac{\sum_t d_t}{\sum_t (y_t-p_{base,t})^2}
\]

置信区间对 calendar block 成组重采样 10,000 次，固定 seed `20260823`。Power 计算先从
历史 `d_t` 删除实际均值，只保留其波动、稀疏性与依赖结构，再分别施加 2%、5%、10%、
15% 的目标 Skill。以下采用单侧 alpha=5%、power=80% 的 block-variance 渐近估计。

这种设计有两个刻意的保守点：不把重叠标签视为独立，也不把已经看到的历史高 Skill
当成未来必然效应。所需年数只能解释为数量级可行性，不是市场过程的精确时间预测。

## 4. 历史描述性结果（不得冒充 prospective）

| 事件 | candidate Skill | 20-session 单侧 95% lower | 历史 causal gate coverage | publication-policy Skill |
|---|---:|---:|---:|---:|
| Acute | 2.26% | -2.18% | 49.05% | 1.47% |
| Front inversion | 10.61% | 4.24% | 95.89% | 9.65% |
| Mid-curve acceleration | 10.86% | 5.21% | 14.17% | 3.51% |
| Carry recovery | 17.87% | 6.12% | 13.64% | 6.58% |

这张表只说明方法的历史表现：完整成熟 OOF 上，Front/Mid/Carry 的 block lower bound 为
正，Acute 仍跨零。它不推翻既有历史 Core 验收，也不构成前向通过。

低 historical coverage 同时说明：若只记录最终 fallback 概率，Mid 与 Carry 的模型证据
会大量不可恢复地丢失。P1 保存 nullable `candidate_probability` 是必要的最小语义，而非
额外基础设施。

## 5. Power 可行性

20-session 主 block 下，达到 80% power 的估计日历年数：

| 真实 Skill | Acute | Front inversion | Mid-curve | Carry recovery |
|---:|---:|---:|---:|---:|
| 2% | 99.9 | 259.5 | 166.3 | 671.1 |
| 5% | 16.0 | 41.5 | 26.6 | 107.4 |
| 10% | 4.0 | 10.4 | 6.7 | 26.8 |
| 15% | 1.8 | 4.6 | 3.0 | 11.9 |

2% 情景在 10/20/40-session block 下的范围分别为：

- Acute：92.0–100.7 年；
- Front inversion：211.9–259.5 年；
- Mid-curve：148.1–166.3 年；
- Carry recovery：522.5–671.1 年。

所以 2% 应继续作为**点估计最低经济/科学增量线**，但不能承诺在一个个人交易系统的
合理期限内对 2% 边界效应取得 80% power。若真实效应接近历史 Front/Mid/Carry 水平，
Prospective 才可能在若干年内给出正 lower bound；Acute 若只维持约 2%，很可能长期保持
`INCONCLUSIVE`。

## 6. 建议冻结的最低证据门

建议四个条件事件统一使用以下进入裁决的最低门：

| 项目 | 建议值 |
|---|---:|
| activation 后日历跨度 | >= 36 个月 |
| 已解析 candidate predictions | >= 504 |
| 正 outcome | >= 50 |
| 负 outcome | >= 50 |
| 独立正 episode | >= 20 |
| 负 horizon block | >= 30 |

这些是“有资格作一次正式判断”的完整性门，不是通过门，也不是 80% power 声明。任何一项
不足都直接为 `INCONCLUSIVE`。

不建议另设一个容易被误读的 capture-gap 百分比特批线。正式统计对缺失
`candidate_probability` 使用 partial-identification：已知 outcome 后，把每个缺失 candidate
的 Brier loss 保守限制在 `[0,1]`。确认必须在所有缺失项取最不利 loss 后仍通过；否定必须
在取最有利 loss 后仍失败；其余为 `INCONCLUSIVE`。这样断网或 writer 故障不会被假设为
随机缺失，也不会因为 0.9% 之类的任意阈值被悄悄忽略。capture-gap rate 仍逐次报告。

按成熟历史的年化积累速度、假设 candidate 每次均成功计算，达到完整性门的理想化时间：

| 事件 | 年化 resolved | 年化正 episode | 理想化门时间 | 历史年度锚点已完成窗口 |
|---|---:|---:|---:|---:|
| Acute | 187.5 | 4.67 | 4.28 年 | 3.05–4.85 年 |
| Front inversion | 153.3 | 3.57 | 5.61 年 | 4.50–6.86 年 |
| Mid-curve | 142.0 | 9.73 | 3.55 年 | 3.22–3.85 年 |
| Carry recovery | 169.3 | 4.59 | 4.35 年 | 3.35–4.98 年 |

后半段历史锚点受 2026-08-20 截止而右删失，因此完成窗口不是保证。现实预期应理解为：
**至少约 4–6 年，Front 可能更久**；candidate 计算缺失或数据 gap 只会延长，不得回填。

## 7. 建议的唯一正式裁决

### 7.1 审查时点

- 每半年只做 ledger 完整性与积累进度报告，不据此晋升模型；
- 当某事件首次满足第 6 节全部门后，只在下一个预先固定的 6 月 30 日或 12 月 31 日进行
  该 cohort 的**一次**正式统计裁决；
- 不因中途曲线好看提前考试；首次裁决若为 `INCONCLUSIVE`，Prospective 001 不重复偷看
  同一批 outcome 来取得绿灯。后续正式再检验必须预先冻结新的非重叠 confirmatory
  cohort；旧 ledger 仍可作描述性研究。

这样避免了按分数反复考试的 optional stopping；达到完整性门本身是预先冻结的
event-count stopping rule，因此同一 cohort 只允许一次正式裁决，不把日历排期误称为
可以无限重复检验的许可。

### 7.2 单事件三态

建议 Core model estimand 采用 20-session block bootstrap：

- `CONFIRMED`：完整性门全部满足；candidate Brier Skill 点估计 >=2%；包含 candidate
  capture gap 最不利界的单侧 95% lower >0；prospective ECE 点估计 <=7%；
- `CONTRADICTED`：完整性门全部满足，且 paired Skill 的单侧 95% upper <0；或 ECE 的
  cluster-bootstrap 单侧 95% lower >7%；candidate gap 必须取最有利界后仍满足否定条件；
- `INCONCLUSIVE`：其他全部情况，包括样本/episode 不足、区间跨零、candidate 缺失或
  Skill 为正但未达到 2%。

Calibration intercept/slope、paired Log Loss、10/40-session block 敏感性、lead time 和
false-alarm duration 全部报告，但不在看到结果后新增否决线。ECE 对超过 252 条样本使用
预冻结的 5 个等频 bin，按 probability、prediction session、record hash 稳定排序；bin
大小最多相差 1。

总体 Core 只有四个条件事件全部 `CONFIRMED` 才能称
`PROSPECTIVE_CORE_CONFIRMED`。任何一个 `CONTRADICTED` 必须明确暴露；其余情况继续为
`PROSPECTIVE_CONFIRMATION_PENDING`。Broad 只能得到 `BASE_RATE_REFERENCE_VALID/INVALID`，
永不计作第五个模型 PASS。

### 7.3 仍需 P1 补齐的可测量性

现有 target ledger 只保存 horizon 最终标签，没有保存首次命中 session。因此仅凭当前合同
中的 Outcome JSON 无法严格计算 lead time。P1 Schema 在人类批准后应让 resolver 额外保存
冻结目标逻辑得到的 nullable `first_event_session`；它只能在完整 horizon 到期后写入，不能
改变 label。若不增加该字段，lead time 必须诚实标为 `NOT_MEASURED`，不得从报告图形反推。

False-alarm duration 建议固定定义为：`candidate_probability > causal_base_rate` 且最终 label=0
的连续 eligible origin session 数。该阈值是零 uplift 的自然物理边界，不允许事后扫描。

## 8. P0 停止点

P0 已完成以下工作：

- 验证三份输入身份及 OOF/target 对齐；
- 量化事件率、episode、负 block、历史 causal coverage；
- 对 10/20/40-session 依赖结构完成固定 power sensitivity；
- 给出可执行但尚未冻结的完整性门、estimand 与三态裁决；
- 识别 `candidate_probability` 与 `first_event_session` 两个必须在人类批准后写入合同的语义。

当前没有 writer、Schema、receipt binding、resolver、Dashboard 改动或 activation tag。下一步
只能由人类选择是否把第 2、6、7 节建议写回
`MATVIX_PROSPECTIVE_001_CONTRACT.md`；在此之前保持：

- `READ_ONLY`
- `NO_TRADING_AUTHORITY`
- `HISTORICAL_CORE_ACCEPTED`
- `PROSPECTIVE_CONFIRMATION_PENDING`
