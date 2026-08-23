# MATVIX PROSPECTIVE 001 验收报告

验收日期：`2026-08-23`

状态：`P5 PASS / READY_FOR_P6_ACTIVATION`

本报告验收的是本地 prospective 证据记录器，不重新验收或修改 V3 科学模型。最终产品边界
仍为：

- `READ_ONLY_RESEARCH_WEATHER_STATION`
- `NO_TRADING_AUTHORITY`
- `HISTORICAL_CORE_ACCEPTED`
- `PROSPECTIVE_CONFIRMATION_PENDING`

## 1. 冻结依据与施工提交

- P0 power design：`ba1a990a02335396592dc012f6ba285b8be5c6c6`
- 冻结合同：`23a0365b3793121b06ae517314006e30f582c9b9`
- P1 immutable local records：`1677fac`
- P2 receipt binding：`31d9336`
- P3 outcome resolver：`9f9155d`
- P4 runtime evidence status：`2892fbd`
- P5 durability fault completion：`c5f2c16`

合同与 P0 报告 SHA-256：

- `MATVIX_PROSPECTIVE_001_CONTRACT.md`：
  `f4cc9a4eac67b14783b04dbe12541a1e9203127513af69e54b46eb7762f1b19c`
- `MATVIX_PROSPECTIVE_001_POWER_DESIGN.md`：
  `956dd5c0e022a76f251498f2f94869f19b8c4f63edebfb6dc8f363f09472dc56`

Activation tag 在 P5 验收时尚未创建，因此没有正式 prediction 被提前写入，也没有历史
回填。

## 2. P1–P4 功能门

### P1 LOCAL RECORD — PASS

- Prediction/Outcome Schema 均为 `1.0.0`，Schema SHA-256 分别为
  `f99ec373d19dda07d9b2d85f6a8366b9503759615bdbc7d28a1806c758c22d26` 与
  `aab798b69c6031454381e8ef822088cee26afa414830484ff8f1cec7473c3efa`。
- 固定逻辑路径使用 exclusive create；完整写入后刷新文件与父目录并设为 `0444`。
- 相同 bytes 重跑幂等；不同 bytes 同路径拒绝覆盖。
- 正式发布概率与 shadow candidate 分栏保存；Broad candidate 恒为 null。

### P2 RECEIPT BINDING — PASS

- 正式顺序为 snapshot → prediction → receipt，receipt 最后发布并绑定两份 exact bytes。
- receipt 失败后，完整孤儿 prediction 可按原 `captured_at` 幂等恢复。
- `EVIDENCE_CAPTURE_GAP` 与 `PRE_ACTIVATION` receipt 不允许后续回填。
- same-session 新内容不能覆盖既有 prediction；天气可发布但该 session 永久标记 gap。

### P3 RESOLVER — PASS

- Target ledger 与 `first_event_session` 共用冻结 future predicate 实现。
- 5/10-session horizon 到期前保持 pending；完整 `OBSERVED_0/1` 后只追加 Outcome。
- Broad 首次命中固定为窗口内第 5 个 broad-pressure session。
- 延迟解析保留原 `outcome_available_at` 并设置 `resolved_late=true`。
- Target/Outcome 冲突在新 snapshot/receipt 发布前停止，不覆盖原证据。

### P4 RUNTIME — PASS

- Dashboard 与 `/api/status` 显示 capture 状态、cohort、pending、resolved 与 gap 数。
- 永久 gap 或 prospective 文件损坏将总体状态降为 `DEGRADED`。
- `trading_authorized=false` 保持不变。

## 3. 故障矩阵

| 场景 | 验收结果 |
|---|---|
| identical rerun | 不改 prediction/receipt mtime，不新增证据 |
| same-session different content | 原 bytes 保留，报告 `ProspectiveConflictError` |
| receipt 写入失败后重启 | 孤儿 prediction 幂等恢复，receipt 仍最后发布 |
| prediction writer 失败 | 天气 receipt 发布为 `EVIDENCE_CAPTURE_GAP`，永久不回填 |
| prediction 文件权限/内容损坏 | 该 receipt 失去资格，回退 prior last-good |
| outcome 文件损坏 | 不视为 resolved，不覆盖，进入人工审计 |
| 重复实例 | 项目级非阻塞锁返回 `BUSY` |
| 断源/不完整 horizon | outcome 保持 pending；last-good 不变 |

## 4. 质量门

- 完整 pytest：`268 passed`；唯一信息为既有 pandas `FutureWarning`。
- Ruff：`PASS`。
- strict Mypy：`PASS`，47 个 source files。
- Doctor：全部锁定依赖 `PASS`；`scikit-learn==1.7.2` compatible。
- tracked-files-only clean source export：pytest 268、Ruff、Mypy、doctor runtime 均 `PASS`；
  因未复制授权行情，doctor 正确报告 observations/VX/states `MISSING`，未伪造真实数据重建。

## 5. 真实数据与科学不变性

`accept-real --date 2026-08-20` 的 14 个 gate 全部 PASS，并确认 canonical receipt
`Already current`。`accept-v3-station` 的七维验收与 `STAGE_E_ENTRY` 全部 PASS。

重算前后下列正式 bytes 相同，并与 `MATVIX_V3_RELEASE_MANIFEST.json` 一致：

| 证据 | SHA-256 |
|---|---|
| OOF ledger | `330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820` |
| Target ledger | `fb91968643c2b65fa28f72fa77ca485cb4db934c1e59d20fb554cf2d00939913` |
| Accepted daily snapshot | `287ce0d5e16b94d2d5a3f5479c0c0a1ea00a42768f545a052478a44a23a2d215` |
| Accepted receipt | `670a566bfc34791b6c82bf4b8a928944a71c4c79c2c3181d1bed33ccf907c4ed` |
| Stage D daily | `24de7e129cf2349bc18bc3aef697986af4c77184ea017c7dc2ad9423b049a7ef` |
| Stage D summary | `54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93` |
| Stage D report | `10b1c08a6a547c85864a7319ccfe977aa2e42a0842479eb1c27ecd8b79a35fcd` |
| Economic daily | `2262667420ba371d25d552959b918d4ca53abae4c7293bd14b1192f568b5321e` |
| Economic JSON | `5c6ff064bb1d5a63153967656aac33d1c7f707db006eb1c31e70833370c5a8b5` |
| Economic HTML | `300dbf179bd90029421d6d20278d52f1e73d96a202c0d7ad7568186a367f714a` |

P5 同时确认四份冻结配置、V3 daily schema 与历史 Stage-D comparator hash 未变化。
`probability/engine.py` 的变化只把同日已计算 candidate 暴露给 recorder metadata；
`probability/targets.py` 的变化只抽取原 predicate 供 label 与 first-hit 共用。上表的 OOF、
Target、Snapshot、Stage D 与经济证据 byte identity 证明它们没有改变 V3 科学输出。

## 6. P5 裁决

P1–P5 全部通过，允许执行 P6：合并到 `main`、创建 annotated
`matvix-prospective-001-activation` tag、推送 branch/main/tag，并验证 local、tracking 与
remote refs 一致。首条正式 prospective 样本仍必须等待 activation 后的下一份自然 passing
receipt；不得把 `2026-08-20` 或更早记录回填为 prospective。
