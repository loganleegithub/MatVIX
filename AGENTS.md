# MatVIX Repository Constitution

本文件是 MatVIX 仓库的总宪法。它约束人类与 AI agent 在本仓库中的研究、开发、文档和发布
行为。目标不是把风险降到零，而是在不伪造证据、不污染生产边界的前提下，持续提高系统对
市场天气的解释与预测能力。

若本文件与用户当前明确指令冲突，以用户指令为准；若与历史合同、报告或 closeout 冲突，
以本文件和当前 active 文档为准。历史冻结文件描述当时的证据和裁决，不拥有永久阻止未来
人类授权研究的权力。

## 1. 项目使命

MatVIX 是 VIX 市场天气站。它的主任务依次是：

1. 识别市场压力是否正在形成；
2. 估计未来五个交易日首次跨越 E15 的可校准发生概率，并在数据或证据不足时诚实拒绝；
3. 用校准、可审计的概率或分布表达不确定性；
4. 只有在独立证据成立后，才允许下游系统讨论风险预算、仓位或交易。

当前 E15 对象由 `docs/README.md` 指向的唯一 active research brief 定义。它研究同一个五日
first-passage 事件在真实信息时钟上的概率前沿：每个节点的概率语义、相邻节点之间的诚实更新，
以及 clock value 与 method value 的分离。完整幅度 Severity、E30/E60 分级、条件分位数和完整路径
分布保留在历史研究中，不是当前 E15 authority。HTTP 200、测试全绿、报告生成、事后
perfect-label 收益或更晚时钟的天然信息优势均不能替代可校准概率证据。

## 2. Agent 主线与证据优先级

每次非平凡任务开始时，agent 只先读取 `AGENTS.md`、`docs/README.md` 指向的唯一
active research 文档和当前 `git status`。动手前必须在当前会话或计划中明确五件事：

1. `NORTH_STAR`：父级研究目标；
2. `CURRENT_EVIDENCE`：已成立和尚未成立的证据；
3. `CLOSED_LEAVES`：已关闭的候选、数据路径或动作主张；
4. `CURRENT_QUESTION`：本轮只回答的一个问题；
5. `MINIMAL_SURFACE`：需要新增、保留和删除的最小文件面。

这五项是工作上下文，不是新的配置、状态文件或合同。最近一个实验是研究树的叶子，
不得因为刚执行完就取代 `NORTH_STAR`。如果叶子失败，回到父问题选择下一条有新信息的
路径，不在该叶子上继续叠加修复、治理或抽象。

当前五项内容必须从唯一 active brief 的 `Current working context` 读取；交接、archive、output
或旧分支只能帮助导航和核验，不能提供第二套当前状态。

发生冲突时按以下顺序判断：

1. 当前用户明确指令；
2. 当前 checkout 的真实数据、代码、运行结果和 Git 状态；
3. 本文件与 `docs/README.md` 指向的 active 文档；
4. 当前测试和可复现的审计产物；
5. archived/superseded 合同、报告和解释文字。

不得用旧哈希、旧状态、旧报告或记忆覆盖当前可直接验证的事实。不得用测试通过覆盖统计门、
经济门或运行时事实。

## 3. 三条工作通道

每项工作只进入以下一条通道。不要把更高通道的治理成本提前施加给更低通道。

### A. 探索研究

目标是最快获得可靠信息。默认允许：

- 一个简短 research brief；
- 一个可复用实验 runner；
- 一个 focused test 文件；
- 少量由明确假设驱动的 baseline/candidate；
- 训练折内部的特征诊断、模型选择和超参数选择；
- 可覆盖、可重建的本地实验产物。

探索研究不要求 source/test 哈希冻结、immutable output、exact-no-op、全库身份清单、逐阶段人类
冻结或生产级 fault matrix。禁止以“防止未来误用”为理由预建 API、Schema、recorder、adapter、
扩展点或消费者。

### B. 冻结评估

当候选已存在并准备接受一次正式历史 OOF 或独立 holdout 评估时，才冻结：

- 科学问题、target 和 decision clock；
- 外层时间切分、purge/embargo 和主指标；
- baseline、候选集合和停止规则；
- 评分所需输入数据身份。

冻结评估可以使用少量预注册 candidate，不强制“一份合同只能运行一个模型”。模型比较必须在
外层验证数据不可见的前提下完成。负结果只关闭本次明确主张，不得自动升级为整个 target、
整个领域或所有未来数据源不可建模。

### C. 晋升与运行

只有候选通过冻结评估并准备进入 prospective、产品、API、Dashboard 或外部消费者时，才启用：

- immutable prediction/outcome；
- release manifest 和必要哈希；
- schema/version migration；
- full-suite、build、runtime 和回滚验证；
- 生产/交易权限的明确人类裁决。

不可变、WORM、exact-no-op 和全链路身份属于晋升边界，不属于日常研究默认值。

## 4. 研究设计原则

- 先定义交易员真正要知道的量，再选模型。不得因现有模型方便而替换科学对象。
- 使用 causal/PIT 输入；未来 outcome、经济结果和下游 P&L 不得进入天气特征选择。
- 使用 walk-forward 或等价的时间外推验证；五日重叠、episode 聚类和 regime drift 必须进入
  评估，但不得借依赖性把全部 origin 简化成一个不必要地悲观的样本数。
- `UNKNOWN`、gap、censor 和 late 必须保留；这条数据诚实原则不因精简治理而放松。
- 本地缺数或首次公开检索无结果，不构成把 P0 基础数据问题直接转交人类的理由。agent 必须先
  自主完成有边界的合法取数排查：替代供应方、官方 archive/sample、零价自助下载、实际字节
  获取、解压、Schema/日历/覆盖率/来源交叉验证和权利边界记录。不得只凭产品页或搜索摘要宣告
  `DATA_UNAVAILABLE`；只有这些路径已被实际尝试且仍无可审计字节时才可停止，并列出尝试证据与
  剩余的精确技术障碍，而不是笼统要求人类“提供数据”。
- 自主解决数据缺口不扩大外部权限：允许领取不产生付款、订阅或额外特权的公开零价数据；禁止
  虚构身份、绕过访问控制、违反禁止自动提取条款，或未经明确授权购买付费数据。原始数据默认
  留在本地并排除出 Git，来源、取得时间、覆盖与许可/不可再分发边界必须可审计。只有
  数据身份会实质影响一次冻结评估或发布时，才记必要哈希；不建仓库级哈希绑定层。
- 探索阶段默认比较一个 causal baseline 与少量互补 candidate。没有新假设时禁止无限追加模型；
  有明确新假设时也禁止旧 closeout 永久阻止新研究。
- 在 candidate loss 尚不存在前，功效分析只能标记为 design sensitivity，不能用于宣判整个科学
  对象不可运营。
- 先报告 observed effect、稳定性和误差结构，再讨论 prospective 年限。
- 排名能力、数值尺度、校准和经济映射是不同问题，不得互相冒充。

## 5. E15 专项边界

- V3 probability 与 frozen product surface 保持独立；E15 研究不得修改其 Schema、发布值或
  prospective cohort。
- Active target 是 `P(E15 first passage within 5 sessions | clock-time PIT information)`；历史
  `E15` 继续表示 `log(VIX_future / VIX_current) >= 0.15`，literal 15% 只能作预写敏感性。
- 同一 sequential probability 问题内的各节点必须共享 event identity、anchor、target window、
  deadline 和 outcome；增加信息时钟不得重置 target 或缩短 horizon。
- 各 forecast clock 必须在自己的 causal baseline 上裁决；若比较跨时钟 forecast，必须另设同钟
  comparator，分开 clock/new-information value 与 method value。更短 lead time 不得冒充模型进步。
- 节点分别校准不自动构成诚实 probability process；任何 sequential-update 主张都必须另外检查
  相邻更新边的一致性。prior、sensor mapping 和 observation/receipt-quality drift 应拆开报告，
  纯 intercept、lag memory 或重校准不得吸收漂移后冒充新增信息。
- 新天气概率候选必须带来真正新增的 causal/PIT 信息，并通过 proper score、
  校准、相同时钟增量与时间/制度稳定性证据。历史 OOF 通过最多 nomination；看过的历史数据不能
  建立 global best 或 prospective confirmation。
- 数据迟到、gap 或 OOD 时输出 `ABSTAIN`；没有独立授权的研究概率不得改变仓位。
- `CLOSED_LEAF` 只约束原信息集、时钟、候选构造、动作和损失函数。历史裁决既不授权新施工，也
  不永久否决具有真正新增 causal/PIT 信息的新问题。
- 概率、经济与执行是三层不同证据：概率层在所有有效 origin 上按 clock-specific baseline 裁决；
  经济层必须另行冻结动作、可选集合、决策时钟、损失和基准；执行层还需要资产、方向、规模、
  entry/exit、bid/ask/size、receipt、费用、滑点、容量和明确人类授权。动作失败只关闭动作叶子，
  proper-score 或规范化 cost-loss 改善也不产生交易权限。
- 在相对动态 climatology、V3 level/occurrence 与当前期限结构建立独立增量前，不接入 SmatVIX、
  Compensation、仓位、订单或交易结果。

## 6. 代码与仓库结构

- 正式产品代码放在 `src/matvix/`；独立研究 runner 放在 `analysis/`。只有确定要进入产品时才把
  研究代码迁入 package。
- 测试按生产代码与研究代码分层；研究实验不应为了方便新增正式 package surface。
- 优先复用现有 calendar、PIT、walk-forward、metrics 和 storage 能力。不要复制一套只为单个
  合同服务的框架。
- 不为假想调用者增加 abstraction、config、flag、factory 或 plugin。
- 重构必须减少重复或修复真实边界。不得把“以后可能用到”当作重构理由。
- 生成数据和大体积 machine-readable evidence 放入 `data/`、`outputs/` 或 `artifacts/`，不要把
  数千行 JSON 展开进 Markdown。
- 不新增依赖，除非现有依赖无法满足当前实验且新依赖能降低总体维护成本。

## 7. 验证标准

验证强度与变更风险匹配：

- 文档/索引变更：链接、状态、`git diff --check`；
- 独立研究 runner：synthetic focused tests、Ruff、必要的 Mypy、代表性 smoke run；
- 共享库修改：受影响 focused tests，再运行相关 integration/full suite；
- 产品或发布变更：full pytest、Ruff、Mypy、build/CLI/runtime 及必要数据契约。

不要在每次文档编辑后运行 full suite，也不要用 focused test 证明真实模型效果。运行失败必须保留
真实原因；修复实现错误不等于修理科学结果。

## 8. 文档治理

文档是导航和决策工具，不是第二套程序。

### 8.1 文档位置

- `README.md`：当前产品、用户入口和稳定运行方式；
- `AGENTS.md`：仓库总宪法；
- `docs/README.md`：唯一文档索引和 active authority 清单；
- `docs/research/`：当前 research brief、实验说明和简洁结果；
- `docs/decisions/`：少量仍影响当前架构的决策记录；
- `docs/archive/`：被替代的合同、closeout 和历史报告索引；
- `outputs/` / `artifacts/`：生成报告、完整 cell、ledger 和机器证据。

根目录只保留稳定产品/发布文档与当前真正需要高可见性的 active 文档。不得继续在根目录堆叠
同一对象的 `_001/_002/P0/PREFLIGHT/CLOSEOUT/REPORT` 链。

### 8.2 生命周期

每个科学或产品对象最多有一份 active 文档，状态只使用：

- `ACTIVE`：当前有效；
- `DRAFT`：正在形成但尚未执行；
- `SUPERSEDED`：被新文档替代；
- `ARCHIVED`：仅保存历史证据。

新增、重命名或归档文档时必须同步更新 `docs/README.md`。历史文档不得因文件名含有
`FROZEN`、`AUTHORITY` 或 `CLOSEOUT` 就覆盖当前 active 决策。

### 8.3 内容规则

- 一份文档只回答一个当前问题；背景用链接，不复制整段历史。
- 合同只用于不可逆、外部消费者、prospective 或晋升边界。普通实验使用 research brief。
- 报告先给科学结论、误差和限制，再给工程验证；不以 SHA 表格占据主体。
- 机器证据保存在结构化 artifact 中，Markdown 只保留摘要和路径。
- 失效文档归档，不通过再写一份 closeout 来关闭上一份 closeout。

## 9. Git 与工作树

- 物质性开发在 `codex/` 分支进行；切分支前先记录现有 dirty 状态。
- 用户已有变更默认属于用户。不得 reset、checkout、stash、clean、恢复或顺手提交无关字节。
- 清理优先采用可恢复归档；删除前搜索引用并确认对象已被替代。
- 每个分支只承载一个可解释目标。研究 artifacts 与正式产品修改不得混成一次晋升。
- 未经用户明确要求，不 push、tag 或发布；本地 commit 也应是可审阅、目标单一的完成单元。

## 10. 明确禁止的反模式

- 用更多治理文件代替一次有信息量的实验；
- 用哈希一致、exact-no-op 或测试全绿宣称模型有效；
- 为防止所有理论失败而让主线无法运行；
- 看到一个 half 变差就永远关闭整个科学对象；
- 看到一个 half 变好就忽略其他时期或晋升生产；
- 在同一历史验证集上无界调参或挑模型；
- 因 sunk cost 保留重复代码、重复合同或重复报告；
- 用 Q80、风险上限或 position cap 冒充 Severity magnitude；
- 把研究级 `ASSUMED_PIT` 冒充 production PIT；
- 把仓位、收益或产品价格反馈进天气模型选择。

## 11. 完成定义

任务只有在以下条件满足时才算完成：

1. 用户要求的真实结果已交付，而不只是计划、合同或绿色测试；
2. 实现是满足当前目标的最小系统，没有平行旧路径和无用途保护层；
3. 在正确层级完成验证，并明确未验证部分；
4. active 文档、代码、测试和 artifact 路径一致；
5. 最终 diff、Git 状态和相关引用已检查；
6. 科学结论、工程状态、产品权限和交易权限被清楚分开。
