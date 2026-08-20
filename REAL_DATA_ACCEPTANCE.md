# MatVIX 真实数据验收记录

> 验收日期：2026-08-20
> 最新完整市场日：2026-08-18
> Feature / State / Probability：1.0.0 / 1.0.0 / 1.1.0
> 结论：13 / 13 业务门通过

## 1. 数据基座

- 已核对本地 vendor manifest：183 / 183 个文件 SHA-256 一致。
- 正规化 observation revision ledger：67,610 行，覆盖 VIX OHLC、VIX9D、VIX3M、VIX6M、VVIX、SKEW 与 SPX。
- 正规化标准月 VX settlement ledger：29,792 行；`Settle<=0` 的无效记录未被替代或前填。
- 可用 F1-F6 正式曲线从 2013-05-20 开始；2026-08-19 尚无完整 VX 曲线，因此最新完整共同市场日是 2026-08-18。
- 四个 SKEW 原始缺口按缺失保留：2017-09-14、2018-12-03、2019-07-05、2024-11-29。

历史文件不保存原始发布时间，因此正式回放证据为 `ASSUMED_PIT`：按下一共同交易日 09:20 ET 生效。它满足可复现的 point-in-time 规则，但不冒充历史当时真实采集留痕。

## 2. 状态与市场叙事

状态历史包含 3,333 个 XNYS session（2013-05-20 至 2026-08-19）：

| 状态质量 | 日数 |
|---|---:|
| OK | 2,546 |
| PARTIAL | 624 |
| UNKNOWN | 163 |

2,546 个 `OK` 日的五个分数均在 `[0,100]`，五个业务答案及 phase 均合法，无违规行。七种可观察 phase 均在真实历史自然出现，不靠合成数据制造。

2026-08-18 的发布叙事为：

- phase：`MIXED_TRANSITION`
- pressure / direction：`WATCH / RISING`
- BaselineScore：`40.3652`
- 当前判断：carry supportive、shock building、tail normal、persistence mixed、repair inactive
- 叙事结论：前端 carry 仍有缓冲，短端保险定价升温但尚未形成急性压力，期限广度分化。

独立数值复算检查了 2020-03-16 与 2026-08-18。F1-F6 选择、严格 30 日 VX 插值、FrontSlope30、Basis30EOD、NearStress、三段 forward variance/volatility、756-session 排除当日的滚动百分位，与 Parquet/JSON 除 `6.94e-18` 浮点舍入外完全一致。

## 3. 概率链

完整 target ledger 有 13,332 行；完成标签共 7,139 条。概率版本 1.1.0 把 `minimum_training_samples` 从 756 调整为 252，只决定何时允许模型开始接受检验；30/30 类别下限、20-session purge、顺序 Platt 和独立 252 条发布验收均未放宽。

| 事件 | 完成标签（正/负） | Raw / calibrated OOF | 最近252条验证 | 发布资格 |
|---|---:|---:|---|---|
| Acute Front Stress 5D | 2,301（325/1,976） | 2,035 / 1,763 | BrierSkill 7.56%，ECE 5.06% | 通过 |
| Front Inversion 5D | 2,122（265/1,857） | 1,861 / 1,609 | BrierSkill 8.06%，ECE 4.20% | 通过 |
| Broad Persistent Stress 20D | 2,102（393/1,709） | 1,942 / 1,541 | BrierSkill 21.53%，ECE 9.02% | ECE 失败，回退 BaseRate |
| Fast Repair 5D | 614（166/448） | 363 / 294 | BrierSkill -3.70%，ECE 10.08% | 失败，回退 BaseRate |

逐条重算 6,201 条 OOF 的训练边界、已完成 outcome、20 日 purge、rolling BaseRate、Platt 先后顺序与 sigmoid 算术，违规数为 0。

2026-08-18 的实际发布为：Acute 与 Front Inversion 使用 `CALIBRATED_MODEL`；Broad Persistent 使用 `BASE_RATE_ONLY`；Fast Repair 当日问题不适用，因此为 `NOT_APPLICABLE / NOT_RUN`。发布对象、outlook 与独立重算完全相同。

## 4. 可重复验收

```bash
cd /Users/logan/MatVIX
.venv/bin/python -m matvix doctor --project-dir .
.venv/bin/python -m matvix build-history --project-dir .
.venv/bin/python -m matvix train-probabilities \
  --date 2026-08-18 --full-rebuild --project-dir .
.venv/bin/python -m matvix accept-real \
  --date 2026-08-18 --project-dir .
.venv/bin/python -m pytest -q -p no:cacheprovider
```

机器验收报告写入 `artifacts/acceptance/real_acceptance_2026-08-18.json`。概率 artifact contract 对 spec、runtime、state digest、target 与 OOF digest 进行绑定；相同输入的增量重跑为 `EXACT_CACHE_HIT`，三份概率产物的字节和修改时间均保持不变。

## 5. 数据权利边界

技术验收使用可追溯的 Cboe/CFE 官方历史文件。公开下载不等于可以无限制商业再分发；vendor 原文件不进入 Git。专业或商业使用前，项目所有者仍需确认适用的数据许可：

- [CFE 历史数据](https://www.cboe.com/markets/us/futures/market-statistics/historical-data/futures)
- [Cboe 使用条款](https://www.cboe.com/terms)
- [Cboe 指数信息许可申请](https://cdn.cboe.com/resources/us/indices/Information_License_Request_Form.pdf)
