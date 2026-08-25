# Los Alamos 专家团架构 (v1.1)

> 状态：**Phase 0/1 已落地**（`scripts/los_alamos/` 脚本包 + `SKILL.md` 路径 C +
> `AutoMCM_SOP.md` §9 均已实现并本地测试通过，默认关闭，触发时才生效）；多层展开/
> best-first 调度脚本化（Phase 2）与整题级多工作区扩展（Phase 3）仍是**提案**，
> 尚未实现。本文件是架构规格本体；落地到
> AutoMCM-Pro 现有代码库的具体接线方式见 [`LOS_ALAMOS_INTEGRATION.md`](./LOS_ALAMOS_INTEGRATION.md)。
> 设计演进历程见文末附录 A。

---

## 0. 定位

AutoMCM-Pro 现有流水线（`problem_analysis → data_preprocessing → model_{n}_build/verify
→ sensitivity_analysis → latex_draft → final_compile`）对每个子问题只走一条建模路径：
提出模型、编码、自证、通过就定稿。这在范式明确的题目上没问题，但数模竞赛的大多数子
问题**并非只有一种合理建模方式**，而"哪种更好"往往**不是数值可比的**——需要判断
假设是否成立、论证是否站得住、是否契合题意，这些是语义/定性问题，不是单纯比谁的
误差小。

Los Alamos 架构是叠加在这条主流水线之上的**可选探索层**：把子问题的建模探索本身
建模为一棵**假设树（合并后成为 DAG）**，用分层的评估机制（便宜的语义筛选做剪枝，
一道红队攻击关卡做压力测试，决赛圈再用"客观量化 + 专家小组定性比较"双轨裁决）遴选
最优方案，全程记录假设与语义传递链条，落选分支归档为论文的"备选方案比较"素材。

### 0.2 与 Project Apollo 的关系

AutoMCM-Pro 现有的主流水线（GitOps Checkpoint、AP/MANUAL 模式锁、强制自证）内部
正式定名为 **Project Apollo**——它的分阶段里程碑审查、"test as you fly"式自证协议、
GitOps 版本管理即构型管理，本质上就是 Apollo 计划那种系统工程纪律的直接体现。
**Apollo 与 Los Alamos 是 Director 可选的两种打法，不是谁包着谁**：题目范式明确、
时间紧张时走纯 Apollo（单线严谨执行到底）；题目存在真实范式分歧、值得多方案比较时
切到 Los Alamos 探索，选出冠军后**产出仍然汇入同一套 Apollo 式 Checkpoint 流水线**
做最终整合验证——探索期用 Los Alamos，执行收尾用 Apollo 纪律。两个名字都不缩写成
"AP"，避免与现有"AP 模式"（Autopilot，AI 主导）的缩写冲突。落地方式见
[`LOS_ALAMOS_INTEGRATION.md`](./LOS_ALAMOS_INTEGRATION.md) §1。

### 0.1 设计原则：治理刚性，策略弹性

| 层次 | 内容 | 可否变通 |
|------|------|----------|
| **刚性治理层** | 情报请求必须挂靠 DAG 节点（§5.2）；探索型请求有配额；`verify_*` 未 PASS 不得入决赛圈/写论文；两轨冲突或分歧过大必须人类终审（§9）；预算超限触发告警（§6） | **不可变通**——这是项目"人类是 Router"+"强制自证"哲学的延伸，不因为多了探索层就松动 |
| **弹性策略层** | 一个节点展开几个子分支、要不要合并、要不要回溯、何时把某分支提前送入决赛圈、要不要把四类范式全用上 | **由 Director 依实时信号动态决定**，不写死成固定步骤——这是本架构相对于"四路固定并行"最大的改进 |

---

## 1. 角色总览

| 代号 | 灵感来源 | 角色定位 |
|------|----------|----------|
| **Director** | Oppenheimer（科学主任） | 主协调，唯一有权做"展开/剪枝/合并/回溯/提升决赛圈"决策的角色 |
| **Alsos** | [Alsos Mission](https://ahf.nuclearmuseum.org/ahf/history/alsos-mission/)（战时情报侦察队，先于技术分部行动） | 常驻按需情报服务：任何 Agent 随时可发起查询，但受挂靠规则约束（§5） |
| **Groves** | Leslie Groves（曼哈顿计划总负责人，管资源/进度，不做科学判断） | 自我状态 Agent：只监控预算/漂移/进度，只上报不裁决 |
| **T / E / O / CM** | 洛斯阿拉莫斯四个技术分部（Theoretical / Experimental Physics / Ordnance / Chemistry & Metallurgy） | 假设树第一层展开的**灵感来源**（不是强制骨架，见 §4.2） |
| **筛选评估者** | [Tree of Thoughts 的 value evaluator](https://arxiv.org/pdf/2305.10601) | Track 0：节点展开时给出 expand/prune/merge/needs-intel 裁定 |
| **Bletchley** | [Bletchley Park Hut 6/8 + Bombe](https://en.wikipedia.org/wiki/Hut_6)（机械式矛盾排除）+ [RAND 首创的 Red Teaming](https://greyswanguild.medium.com/the-hunt-for-grey-swans-top-15-methods-frameworks-11-red-teaming-bbc6b8eea8a6) | Track R：候选通过自证后、进决赛圈前的红队攻击关卡（§8.2） |
| **评审小组** | [Google Co-Scientist 的 Ranking(Elo)/Evolution/Proximity Agent](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/) | Track 2：决赛圈两两比较 + 合并候选的灵感来源 |

**仅借用组织架构/行动代号，不做人物拟人化或言论扮演**——Agent 角色叫 `T-Division`
而不是"扮演 Hans Bethe"。

---

## 2. 与既有系统的关系（为何不是重新发明轮子）

| 参照系 | 核心机制 | 本架构借鉴/差异化之处 |
|---|---|---|
| **AutoMCM 现有流水线** | 单线：一个子问题一个 Agent，一次建模一次自证 | Los Alamos 是可选加宽层，不改动主线，只在触发条件命中时启用 |
| **Anthropic 多智能体研究系统**（[官方博客](https://www.claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)） | Orchestrator-Worker：所有协调集中在 Lead Agent，Subagent 之间不互相通信 | 借鉴"协调必须集中"——Alsos 是唯一情报出口，Division 之间不直接互相搜索/传递文献 |
| **Google AI Co-Scientist**（[DeepMind 博客](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)） | Generation/Reflection/Ranking(Elo 锦标赛)/Evolution/Proximity/Meta-review + Supervisor | 借鉴锦标赛式两两对决（Track 2）+ 分支合并（Evolution）/查重（Proximity）；差异化：多一条独立于 LLM 判断之外的纯数学量化通道（Track 1），且候选必须先跑代码自证 PASS 才能入围——数模题目特有的硬证据优势 |
| **Tree of Thoughts**（[arXiv:2305.10601](https://arxiv.org/pdf/2305.10601)） | 生成候选"想法"→独立 evaluator 给 sure/maybe/impossible→BFS/DFS 剪枝 | Track 0 筛选剪枝机制的直接原型，粒度从"推理步骤"换成"建模假设/范式" |
| **"Stay Focused: Problem Drift" 论文**（[arXiv:2502.19559](https://arxiv.org/abs/2502.19559)） | 实证发现多 Agent 讨论会系统性偏离原问题（主观任务 76-89% 会漂移），提出 DRIFTJudge/DRIFTPolicy | 本架构把"漂移可检测"具体化为§5 的 DAG 挂靠机制，而非空泛地"注意别跑题" |
| **Bletchley Park Hut 6/8 + Bombe**（[Wikipedia — Hut 6](https://en.wikipedia.org/wiki/Hut_6)） | 情报收集→线索准备→Bombe 机械式批量排除矛盾候选→人工解码→移交分析，是"廉价机制先淘汰、精贵人力做最后把关"的史实原型 | Track R（Bletchley 红队）的命名与精神源头——不只是省钱，Bombe 的核心动作是**主动寻找矛盾**，这正是红队要做的事，而不是被动等自证脚本报错 |
| **RAND Corporation Red Teaming**（[起源与沿革](https://greyswanguild.medium.com/the-hunt-for-grey-swans-top-15-methods-frameworks-11-red-teaming-bbc6b8eea8a6)） | 1960 年代起源于 RAND 的对抗性测试方法论：刻意扮演攻击者/怀疑者角色，暴露内部评审看不到的漏洞 | Track R 的方法论源头（§8.2 的"主动攻击"具体手段） |

**已知的反面告诫也要正视**：单 Agent + self-consistency 有时比复杂多智能体框架
更省成本且效果更好（[arXiv:2507.06764](https://arxiv.org/pdf/2607.06764)），多候选
方案汇总时评审 Agent 本身常是瓶颈（[arXiv:2603.20324](https://arxiv.org/pdf/2603.20324)）。
应对：默认关闭、显式触发（§8）；Track 0 剪枝把不值得投入的分支尽早挡在门外，避免
"四路都跑到底再比较"的浪费；能量化的部分绝不让 LLM 主观打分（Track 1 纯脚本）。

---

## 3. 假设树 / DAG：探索的核心数据结构

### 3.1 节点 = 一段"建模叙事"的状态快照

每个节点复用假设 ledger 的 schema（§9.2），把它从"事后记录"升级为"驱动探索的可执行
结构"：

```json
{
  "node_id": "N-P1-014",
  "parent_ids": ["N-P1-006"],
  "assumption_id": "A-P1-T-03",
  "seed_paradigm": "T",
  "depth": 2,
  "state": "screened_pass",
  "screening": {
    "coherence": 0.85, "plausibility": 0.70, "novelty": 0.90, "problem_alignment": 0.95,
    "verdict": "expand",
    "rationale": "延续父节点的排队论假设；novelty 高，因为兄弟分支都在做数据驱动路线"
  },
  "created_by": "Director",
  "created_at": "..."
}
```

`parent_ids` 通常 1 个（树的展开）；发生合并（§3.3）时有 2 个，此时整体结构从树
退化为 DAG。存储于 `state/hypothesis_tree_{N}.json`（当前状态的物化视图），由消息
日志（§7）里的操作序列重放生成。

### 3.2 节点状态机

```
proposed ──Track0筛选──▶ screened_pass ──Director分配预算──▶ building
    │                         │                                   │
    │                         └──▶ merge_candidate（§3.3）          │
    │                                                              ▼
    └──▶ screened_pruned（归档，可回溯复活见§3.4）          verify_pass / verify_fail
                                                                    │
                                                        verify_pass │ verify_fail
                                                                    ▼            ▼
                                                          red_team_review    eliminated
                                                         （§8.2 Bletchley）    （归档）
                                                       survived/weakened │ broken
                                                                    ▼        ╲
                                                          in_tournament   修复重 build
                                                          （§8.3/8.4 决赛圈）  或 eliminated
                                                                    │
                                                              champion / runner_up
```

### 3.3 合并（Merge）

若 Track 0 把两个兄弟/表亲节点都标记为 `merge_candidate`（各有所长），Director 可
发起合并：生成新节点，`assumption_id` 描述"取 A 的假设 + 取 B 的求解方法"式的组合
叙事，重新进入 `proposed` 走一遍筛选。这是策略层操作，只在筛选阶段发现"两分支互补"
时才由 Director 判断是否值得一试，消耗新预算需 Groves 许可。

### 3.4 回溯（Backtrack）

分支的所有子节点都 `eliminated` 后不代表永久死亡——若之后 Alsos 收到新情报改变了
当初剪枝的依据，Director 可对已终止节点重新展开。回溯次数计入 Groves 的漂移监控，
避免"反复复活同一条死路"变成变相无限重试。

---

## 4. 触发与第一层展开

### 4.1 触发条件

Director 在进入某子问题建模前，判定是否启用 Los Alamos 探索，命中任一即可：

| 触发源 | 判定方式 |
|---|---|
| **题目复杂度初判（最早触发点）** | Director 在 `problem_analysis` 阶段——**还没开始文献调研、还没进入建模**——就能从题目本身判断出该子问题结构复杂/开放性强（例如：要求"设计方案""在多个目标间权衡""没有唯一标准解法"、涉及多层级决策），不必等其余四条信号出现才触发；越早发现越好，不要因为已经过了 problem_analysis 就假设这个窗口关闭了 |
| 用户显式要求 | "这题模型不确定/都试试/帮我比较几种方法" |
| Alsos 冷启动普查的范式分歧信号 | `paradigm_pool_{N}.json` 中 `paradigm_count ≥ 2` 且范式互不相同 |
| 首次建模验证边际 | 单模型 verify 通过但灵敏度分析显示解对假设高度敏感 |
| 赛题结构要求比较 | 题目原文出现"比较不同方法""讨论优缺点"等字样 |
| 剩余时间预算充足 | 距截止时间 > 阈值（默认 48h，可配置），否则强制走原有单线路径 |

不满足任一条件 → 直接走现有单模型路径，本架构不介入。六条触发源命中任一即可，
检查时机也不互斥——"题目复杂度初判"发生在最早（problem_analysis 阶段），其余
几条可能在后续阶段（文献调研、首次验证）才浮现证据，晚发现依然可以补触发。

### 4.2 T/E/O/CM：第一层展开的灵感来源，不是强制骨架

Director 展开根节点的第一层子节点时，可参考 Alsos 报告、`LOS_ALAMOS_METHOD_
CATALOG.md`（结构化的 MCM 常见范式分类学，覆盖优化/预测/评价/仿真/分类/网络
六大类，防止纯文献检索漏采不那么显眼的技术路线）和 T/E/O/CM 四类范式作为起始
多样性提示，但不要求四个全上——只在真有文献支持的范式上开分支。**分支宽度是
时间预算的函数**：时间充足时应主动展开到 3~4 个、覆盖不同大类，而不是止步于
最先想到的两个；时间紧迫时收敛到 2 个最有希望的即可。

某分支下还可再分叉，且**不限于第一层**——同一范式内部若存在值得比较的技术
路径分歧（求解器选择、离散化粒度、参数化方式），可以对已选定范式的节点再展开
一层（`depth+1`，`parent_ids` 指向父节点），同样要走 Track0 筛选、build/verify、
红队，不因为"只是范式内部选择"而降低验证要求。深度超过第一层后 T/E/O/CM 标签
只在 `seed_paradigm` 字段留痕，供论文写作追溯灵感来源。

### 4.3 假设树是决策的输入，不是只写不读的审计日志

`hypothesis_tree.py` 提供的物化视图（`state/hypothesis_tree_{N}.json`）不能只在
`expand`/`mark` 时写入、事后归档时才读——Director 在"是否继续展开""哪些节点该
进入下一步""决赛圈还剩几个候选"这类判断点，必须先跑 `hypothesis_tree.py status`
拿到当前真实的前沿/决赛圈/剪枝归档状态，而不是凭自己的叙述记忆推断（分支一多、
跨越多轮并行 build/verify/红队之后，记忆很容易跟物化视图的真实状态脱节）。
这是 SOP §9.2 第 6 条治理刚性规则，SKILL.md 路径 C 在 Step 5/9 等关键决策点前
都显式插入了 `status` 调用。

---

## 5. 可控发散：防止目标漂移

### 5.1 范围锚点（Scope Anchor）

`problem_analysis` Checkpoint① 通过后，冻结 `state/scope_anchor_{N}.md`：一段不可变
的"这个子问题到底在问什么"陈述 + 当时确认的假设 DAG 快照。所有后续发散请求必须能
追溯到锚点。修改锚点需显式 `AMEND_ANCHOR` 消息，强制触发 Checkpoint LA 级人类确认。

### 5.2 请求必须挂靠 DAG 节点（核心机制）

每个 `INTEL_REQUEST` 必须二选一：
- `ref_assumption_id`：关联 DAG 里**已存在**的节点（补证据/验证/证伪）——默认放行；
- `new_assumption_proposal`：提出**尚未在 DAG 里**的新方向——默认限流，每个分支
  每阶段最多 K 次（默认 2），超过需 Director 书面批准（`APPROVAL_REQUEST`，理由记入
  日志）。

两者都没有 → Alsos 直接拒绝（`status: rejected, reason: unlinked_request`）。

### 5.3 漂移度量与阈值

Groves 持续计算滑动窗口内"探索型请求 / 总请求"比例 `drift_ratio`，超过阈值（默认
0.3）→ 发 `DRIFT_ALERT` 给 Director（Groves 无权直接叫停）。孤儿假设检测：节点长期
停留在 `screened_pass` 未分配预算、或 `downstream_impact` 长期为空，标记供 Director
参考（不自动惩罚，探索本身有正当性）。回溯次数过多同样计入 `drift_ratio`。

Track 0 的 `prune` 建议允许 Director override（比如"题目原文点名要求讨论此方法"），
但 override 动作本身留痕，计入监控——弹性不等于不留痕。

---

## 6. Groves — 自我状态 Agent

**职责刻意做窄**，不做任何科学判断：
1. 周期性汇总结构化快照 `state/groves_status_{N}.json`：各分支阶段、`drift_ratio`、
   树规模/存活节点数/平均筛选分数/回溯次数、**红队 `broken` 率与重复攻破次数**、
   预算消耗速率 vs 剩余阶段数、返工次数（沿用 SOP 现有 S4 上限）；
2. 超阈值时生成 `DRIFT_ALERT`/`BUDGET_ALERT`，**只发给 Director**，不直接干预任何
   分支；
3. 每次告警和 Director 的响应存档到 `memory/groves_log.md`——赛后可读的过程审计
   报告，本身就是论文附录的好素材（"我们如何控制探索成本"）。

独立于 Director 监控 Director 自己的探索决策，避免自己给自己打分的乐观偏差（与
Track 2 裁决不能由候选自己参与是同一道理）。Groves 是全架构里唯一可以退化成纯脚本、
不必依赖 LLM 的角色（见 [`LOS_ALAMOS_INTEGRATION.md`](./LOS_ALAMOS_INTEGRATION.md) 的
落地建议）。

---

## 7. 格式化报文协议

### 7.1 为什么需要统一格式

Agent 间通信（Division ↔ Alsos、任意 Agent → Groves、评审小组 → 裁决脚本）需要能被
脚本解析统计（比如 `drift_ratio` 计算），自由文本 markdown 不可靠。参考经典多智能体
系统的 [FIPA ACL](https://smythos.com/developers/agent-development/fipa-agent-communication-language/)
消息结构（`performative` 表明"这条消息想干什么" + 发送方/接收方/关联对话元数据），
设计精简版：

```json
{
  "msg_id": "MSG-P1-000042",
  "timestamp": "2026-08-23T10:15:00",
  "performative": "INTEL_REQUEST",
  "sender": "T-Division",
  "receiver": "Alsos",
  "in_reply_to": null,
  "ref_assumption_id": "A-P1-T-03",
  "new_assumption_proposal": null,
  "content": { "...": "视 performative 而定的自由字段" }
}
```

### 7.2 Performative 词表

| performative | 用途 | 发送方 → 接收方 |
|---|---|---|
| `INTEL_REQUEST` / `INTEL_RESPONSE` | 情报查询 | 任意 Agent ↔ Alsos |
| `EXPAND_NODE` | 发起节点展开 | Director |
| `SCREEN_VERDICT` | Track 0 筛选结果 | 筛选者 |
| `MERGE_NODES` / `BACKTRACK` | 合并/回溯操作 | Director |
| `RED_TEAM_REPORT` | Track R 红队攻击结果（§8.2） | Bletchley → Director |
| `STATUS_REPORT` | 心跳/状态汇报 | 任意 Agent → Groves |
| `DRIFT_ALERT` / `BUDGET_ALERT` | 风险上报 | Groves → Director |
| `APPROVAL_REQUEST` / `APPROVED` / `REJECTED` | 探索型请求审批 | Division ↔ Director |
| `VOTE` | Track 2 两两比较投票 | 评审 → 裁决脚本 |
| `AMEND_ANCHOR` | 修改范围锚点（需人类确认） | Director → 人类 |
| `CHECKPOINT_REQUEST` / `APPROVED` / `REWORK` | 复用现有 GitOps Checkpoint 语义 | 任意阶段 |

### 7.3 存储与校验

单一来源 `state/messages/problem{N}.jsonl`（append-only，事件溯源模式）；
`paradigm_pool_{N}.json`/`panel_votes_{N}.json`/`hypothesis_tree_{N}.json`/
`leaderboard_{N}.md` 都是按 `performative` 过滤后**派生**的物化视图，避免多头真相
来源。`quality_gate.py message` 校验必填字段、`INTEL_REQUEST` 的"二选一"约束、
`ref_assumption_id` 是否存在、时间戳单调递增。

---

## 8. 四层评估机制（按成本分层，含红队）

| | 运行时机 | 频率 | 评估对象 | 成本 | 目的 |
|---|---|---|---|---|---|
| **Track 0 — Agent 语义筛选** | 每次展开新节点 | 高频 | 尚未 build 的提案（假设陈述 + 上游叙事路径） | 低（单次判断，不跑代码） | 剪枝：值不值得投入 build+verify 预算 |
| **Track R — Bletchley 红队** | `verify_pass` 之后、入决赛圈之前 | 中频（每个存活候选一次） | 已自证通过的候选：模型代码、verify report、假设 ledger | 中高（独立 Agent 主动攻击） | 压力测试：自证证明"代码逻辑自洽"，红队证明"假设扛不扛得住反例" |
| **Track 1 — 熵权/TOPSIS** | 决赛圈 | 低频（存活候选各跑一次） | 已通过红队的候选，量化指标 | 中（纯脚本，无 LLM 主观分） | 客观排序 |
| **Track 2 — 专家小组两两比较** | 决赛圈 | 低频 | 已通过红队的候选，定性维度 | 高（多 Agent 独立盲审） | 定性终审 |

### 8.1 Track 0 细节

独立筛选者（不是 Director 自己，避免自证自批）读取：假设陈述、从根到此节点的完整
叙事路径、Alsos 相关情报、兄弟节点列表（查重）。输出：

```json
{
  "coherence": 0.0-1.0, "plausibility": 0.0-1.0, "novelty": 0.0-1.0, "problem_alignment": 0.0-1.0,
  "verdict": "expand | prune | merge_candidate | needs_more_intel",
  "rationale": "一句话理由，供人类审计与 Groves 统计"
}
```

`problem_alignment` 与 §5.2 的防漂移挂靠检查共用同一次调用，一次评估两用。
`needs_more_intel` 触发筛选者主动向 Alsos 发 `INTEL_REQUEST`。

### 8.2 Track R 细节 — Bletchley 红队

**定位**：`verify_*.py` 自证的是"这段代码的逻辑和数值是自洽的"；红队要做的是完全
不同的事——**主动攻击**候选方案的假设链条，找现实世界里会让它站不住脚的场景，这是
自证协议从设计上就不覆盖的一块（自证只能检验模型对自己声称的假设是否忠实，不能
检验假设本身站不站得住）。

**执行者**：一个独立 Agent，**不能是该候选的建造者**（Division 自己不能红队自己，
道理和 Track 2 的匿名评审一致）。可以（但不必须）向 Alsos 发 `INTEL_REQUEST` 查该
类模型的已知失效场景。

**具体攻击手段**（至少覆盖前两类，其余按题目类型选用）：
1. **`falsifiable_if` 触发检查**——ledger 里每条假设都记录了"什么情况下这条假设不
   成立"（§9.2），但记录本身不代表真的检查过。红队必须针对每条关键假设，实际验证
   该证伪条件在给定数据/场景下是否被触发（例如假设声明"残差正态"，红队就该真的去
   看 Shapiro-Wilk 检验结果是否支持这一点，而不是相信 ledger 里写的"未触发"）；
2. **边界/极端场景构造**——参数趋于 0 或无穷、题目隐含但 `verify_*.py` 未覆盖的
   退化情形（例如"如果需求为 0""如果只有一个决策周期"），检查模型是否给出荒谬结果；
3. **反例搜索**——尝试构造一个满足题目约束、但会让候选方案结论方向逆转的场景；
4. **选择性呈现检查**——候选方案的验证报告有没有回避一个明显该讨论、但结果不利于
   自己的情形。

**输出**（`RED_TEAM_REPORT` 消息，见 §7.2）：

```json
{
  "node_id": "N-P1-014",
  "attacks_attempted": [
    {"type": "falsifiable_if_check", "target_assumption": "A-P1-T-03",
     "result": "not_triggered", "detail": "Shapiro-Wilk p=0.34 > 0.05，假设成立"},
    {"type": "edge_case", "description": "到达率 lambda→0 时队列长度公式退化",
     "result": "model_breaks", "detail": "分母为零未做保护，需修复"}
  ],
  "verdict": "survived | weakened | broken",
  "severity": "none | minor | major | fatal",
  "rationale": "..."
}
```

**分流规则**：`survived` → 直接进入决赛圈；`weakened`（找到问题但不致命，比如加个
边界判断就能修）→ 允许 Director 决定"打回去修一轮再红队"还是"带着已知弱点直接进
决赛圈、在 Checkpoint LA 如实报告"；`broken`（核心假设被证伪或结论方向可被反例
推翻）→ 强制打回 `building` 修复，修复后必须重新过一遍红队，屡次 `broken` 计入
Groves 的返工监控（沿用 SOP 现有 S4 返工上限）。

**这一关是刚性治理层的一部分**（呼应 §0.1）：在 Los Alamos 模式下，任何候选未经
红队复核不得进入决赛圈——这条和"未过 `verify_*` 不得写入论文"是同一级别的黄金律，
不因为"探索策略可以灵活"而豁免。在纯 Apollo 单线模式下，红队复核是**可选的质量
加固项**（见 [`LOS_ALAMOS_INTEGRATION.md`](./LOS_ALAMOS_INTEGRATION.md) §1.1），不
强制，避免给简单题目也背上额外成本。

### 8.3 Track 1 细节 — 熵权法客观赋权

输入决策矩阵 `X[candidate][criterion]`（各候选的鲁棒性/残差/参数个数/耗时等数值）：
1. 归一化（正向/负向指标分别处理）；
2. 每个指标 `j` 的信息熵 `e_j = -k·Σ p_ij·ln(p_ij)`，`p_ij = x'_ij/Σx'_ij`，
   `k = 1/ln(n)`；
3. 客观权重 `w_j = (1-e_j)/Σ(1-e_k)`——指标在候选间差异越大（熵越低）权重越高，
   所有候选表现趋同的指标自动获得接近 0 的权重；
4. 用客观权重跑 TOPSIS，得到贴近度 `C_i ∈ [0,1]` 作为排名分数。

这是 CUMCM/MCM 论文里常见的"熵权-TOPSIS综合评价"技术
（[原理](https://blog.csdn.net/m0_62558103/article/details/126396293)、
[方法综述](https://zhuanlan.zhihu.com/p/152560388)），纯数学、确定性、可复现。

### 8.4 Track 2 细节 — 匿名两两比较 + 分歧熵

3~5 个独立评审 Agent，读取**匿名化**材料（ledger 去掉 `proposed_by`、verify report、
灵敏度结果，不给代码风格/分部代号，避免"表面特征带偏判断"——
[distracted evaluation, arXiv:2504.14716](https://arxiv.org/abs/2504.14716)）。对每
一对候选，每位评审在每个定性维度给出 `A>B`/`B>A`/`平局` + 一句话理由（`VOTE` 消息，
可审计）。选择两两比较而非直接打分，因为"pairwise comparisons generate relative
assessments that are less susceptible to prompt variations... than single numerical
scores"（同上）。

汇总用 Borda count/Copeland method 出排名；对每场对决的投票分布计算 Shannon 熵
`H = -Σp_i log2(p_i)`（归一化到 `[0,1]`）：`H≈0` 表示高度一致，接近上限表示严重分歧
——分歧熵高于阈值（默认 0.3）→ 不允许 Track 2 单方面裁定，升级人类（§9）。

### 8.5 汇总规则

- Track 1 冠军 = Track 2 冠军，且 Track 2 平均分歧熵 < 阈值 → 明确胜出，AP 模式自动
  晋级；
- 两轨冠军不一致，或 Track 2 分歧熵超阈值 → 判定存疑，触发 Checkpoint LA；
- 两轨**方向性矛盾**（如 Track 1 数值领先但 Track 2 一致认为其核心假设不成立）→
  最高优先级，必须人类介入，不能因熵不算太高就自动放行。

### 8.6 执行策略：best-first、anytime，不锁步

Director 维护"当前前沿"（`screened_pass` 待决策节点 + 已 `in_tournament` 的存活候选），
在任意时刻可选择：深挖前沿里最有希望的节点、提前把某个已 verify PASS 的节点送入
决赛圈（不必等其他分支跑完）、合并互补节点、或对死路回溯重试——依据 Alsos 情报、
Groves 预算信号、Track 0 筛选分数三路实时信号决定，不是"四分部都跑完才能评审"式的
锁步并行。终止条件同样弹性：预算耗尽、前沿节点筛选分数普遍偏低、或某节点已断层
领先，任一满足即可收敛进 Checkpoint LA。

---

## 9. Checkpoint LA 与假设语义传递链条

### 9.1 Checkpoint LA

与现有 Checkpoint ①~⑤ 同构，复用 `pipeline_manager.py request-review`，新增
`--stage model_{n}_adjudicate` 专用汇报模板（两轨排名 + 分歧熵 + 需要人类判断的点）。
**这是唯一一个 AP 模式下也不能自评自批、必须真正等待人类输入的环节**——"选哪个模型
代表队伍参赛"是价值判断，不该被 AI 自己拍板。新增触发：Track 0 override 累计过多、
或合并/回溯显著消耗预算时，Groves 可建议提前进入 Checkpoint LA（建议触发，非强制）。

### 9.2 假设 Ledger Schema（最终版）

```json
{
  "id": "A-P1-T-03",
  "statement": "假设需求波动服从正态分布",
  "math_form": "D_t ~ N(mu, sigma^2)",
  "source": "data_derived",
  "source_ref": "见 memory/thought_process.md#问题一-EDA，Shapiro-Wilk p=0.34",
  "citation_id": null,
  "depends_on": ["A-P1-T-01"],
  "downstream_impact": ["目标函数第2项", "约束(3)", "verify_problem1.py::V-OPT-2"],
  "falsifiable_if": "若残差正态性检验 p<0.05，则此假设不成立，需改用稳健回归",
  "proposed_by": "T-Division"
}
```

`source: literature` 时 `citation_id` 必须引用 `paradigm_pool_{N}.json` 中的真实条目
（`quality_gate.py ledger` 校验，杜绝编造文献依据）。DAG 不只是可追溯性记录，更是
§5.2 防漂移机制的锚点本体——两者共享同一套数据结构。落选方案不删除，归档到
`memory/alternative_approaches_{N}.md`，作为论文"模型比较"章节的直接素材。

---

## 附录 A：设计演进摘要

- **v0.1**：提出 Los Alamos 命名与 T/E/O/CM 四分部并行 + 独立裁决（Trinity）+ 假设
  ledger 的雏形，固定权重打分。
- **v0.2**：意识到大多数比较是非数值可比的，裁决改为双轨（熵权-TOPSIS 客观量化 +
  专家小组两两比较），新增 Alsos 情报组（一次性普查）。
- **v0.3**：情报服务从一次性改为常驻按需；新增 Groves 自我状态 Agent 与格式化报文
  协议；明确防漂移的 DAG 挂靠机制。
- **v0.4 → v1.0**：整个探索过程重新建模为假设树/DAG 搜索，新增 Track 0 语义筛选作为
  剪枝机制（区别于决赛圈的 Track 1/2），执行模式从锁步并行改为 best-first/anytime；
  明确"治理刚性、策略弹性"的分层原则。
- **v1.1**：现有主流水线正式定名 Project Apollo，与 Los Alamos 确立为 Director 可选
  的两种打法（§0.2）；新增 Track R — Bletchley 红队，插在"自证通过"与"进决赛圈"
  之间，主动检验假设 ledger 的 `falsifiable_if` 条件、构造边界场景与反例，弥补
  自证协议"只能检验代码对自身假设是否忠实、不能检验假设本身是否站得住"的盲区。
- **实作（Phase 0/1）**：`scripts/los_alamos/` 脚本包（`bus.py`/`groves_monitor.py`/
  `adjudicate.py`/`hypothesis_tree.py`）、`quality_gate.py` 三个新门控、
  `.claude/skills/auto-mcm/SKILL.md`「路径 C」、`AutoMCM_SOP.md` §9 均已落地并
  本地测试通过（单层展开，不含多层 best-first 自动调度与整题级扩展），详见
  [`LOS_ALAMOS_INTEGRATION.md`](./LOS_ALAMOS_INTEGRATION.md)。

## 附录 B：参考资料汇总

- [NPS — Manhattan Project Science at Los Alamos](https://www.nps.gov/articles/000/manhattan-project-science-at-los-alamos.htm) / [LANL 50th Anniversary 组织架构回顾](http://library.sciencemadness.org/lanl1_a/LANL_50th_Articles/5-28-93.html) / [Alsos Mission — Atomic Heritage Foundation](https://ahf.nuclearmuseum.org/ahf/history/alsos-mission/)
- [NASA — The Apollo Program](https://www.nasa.gov/the-apollo-program/) / [Apollo LOR Architecture Decision Revisited](https://repository.gatech.edu/server/api/core/bitstreams/2cd8233d-f9b6-4b0c-95cc-1a382fc50bc5/content) — Project Apollo 命名依据（§0.2）
- [Bletchley Park — Hut 6](https://en.wikipedia.org/wiki/Hut_6) — Track R 红队命名与"机械式主动排除矛盾"精神来源
- [RAND — Red Teaming 起源与沿革](https://greyswanguild.medium.com/the-hunt-for-grey-swans-top-15-methods-frameworks-11-red-teaming-bbc6b8eea8a6) / [RAND — Delphi Method](https://www.rand.org/pubs/papers/P3558.html)（Delphi 暂未采纳，留作 Track 2 未来可能的多轮收敛升级方向）
- [Anthropic — How we built our multi-agent research system](https://www.claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)
- [Google DeepMind — Co-Scientist](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
- [Tree of Thoughts, arXiv:2305.10601](https://arxiv.org/pdf/2305.10601)
- [Stay Focused: Problem Drift in Multi-Agent Debate, arXiv:2502.19559](https://arxiv.org/abs/2502.19559)
- [Cost-Effective Agent Harnesses (单Agent+self-consistency 的告诫), arXiv:2507.06764](https://arxiv.org/pdf/2607.06764)
- [When Agents Disagree: The Selection Bottleneck, arXiv:2603.20324](https://arxiv.org/pdf/2603.20324)
- [Pairwise or Pointwise? Evaluating Feedback Protocols, arXiv:2504.14716](https://arxiv.org/abs/2504.14716)
- [FIPA ACL 介绍](https://smythos.com/developers/agent-development/fipa-agent-communication-language/)
- [熵权法客观赋权原理](https://blog.csdn.net/m0_62558103/article/details/126396293) / [熵权-TOPSIS 方法综述](https://zhuanlan.zhihu.com/p/152560388)
