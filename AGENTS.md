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
2. 估计未来五个交易日首次跨越 E15 的可校准发生概率，并在证据不足时拒绝输出候选动作；
3. 用校准、可审计的概率或分布表达不确定性；
4. 只有在独立证据成立后，才允许下游系统讨论风险预算、仓位或交易。

当前 `codex/e15-actionable-occurrence` 研究线只回答一个问题：在各自冻结的 EOD 与 pre-open
时钟上，现有 E15 first passage 在未来五个 XNYS session 内发生的概率是多少。完整幅度
Severity、E30/E60 分级、条件分位数和完整路径分布保留在 V4 历史分支，不是本分支的 active
研究对象。HTTP 200、测试全绿、报告生成或事后 perfect-label 收益均不能替代可校准概率证据。

## 2. 证据优先级

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
  留在本地并排除出 Git，来源、哈希、许可/条款和不可再分发边界必须可审计。
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
- 天气概率在所有有效 origin 上评分；主动作评价限于 `data_status == OK` 且 contango 仍允许
  short-vol 的 origin，并分开报告 `PRE_ONSET` 与 `ACTIVE_CASCADE`。
- EOD prior 与 09:20 ET pre-open posterior 是两个不同产品时钟，必须分别击败各自 baseline；
  更短 lead time 不得冒充模型进步。
- 新候选必须带来真正新增的 causal/PIT 信息，并同时通过 proper score、校准和固定行动价值门。
  数据迟到、gap 或 OOD 时输出 `ABSTAIN`，不得改变仓位。
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
