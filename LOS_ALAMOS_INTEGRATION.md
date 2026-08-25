# Los Alamos 落地整合方案

> 前置阅读：[`LOS_ALAMOS_DESIGN.md`](./LOS_ALAMOS_DESIGN.md)（架构规格本体）。
> 本文件回答两个问题：① 这套架构在 Claude Code 这样的 coding agent 上具体怎么跑
> 起来；② 怎么接进 AutoMCM-Pro 现有的 `SKILL.md` / `AutoMCM_SOP.md` / `scripts/`。
> 状态：**Phase 0/1 已落地**——本文件描述的角色→执行机制映射、触发开关、SKILL.md/
> SOP.md 接入点均已实现（`scripts/los_alamos/`、`.claude/skills/auto-mcm/SKILL.md`
> 路径 C、`AutoMCM_SOP.md` §9）。Phase 2（多层展开脚本化）/Phase 3（整题级扩展）
> 仍是提案。

---

## 1. 重新定位：AutoMCM-Pro 不是一个 Skill，是一份 Agent 团队规格

`.claude/skills/auto-mcm/SKILL.md` 目前的包装形式是 Claude Code 的 Skill，但内容
实质上定义的是一个**多角色 Agent 团队的行为规范**——GitOps 状态机、模式锁定
（AP/MANUAL）、强制自证协议、多 Agent 并行策略，这些都不是"一段可复用的提示词"，
而是一整套**协议**：谁在什么状态下该做什么、产出物长什么样、什么时候必须停下来
等人类。Skill 只是这份协议目前唯一的宿主/运行时绑定（binding）。

这个区分在 Los Alamos 架构里变得更明确，也更重要——因为 issue #2
（[Proposal: Optional Codex support](https://github.com/RealSeaberry/AutoMCM-Pro/issues/2)）
已经提出要在 Codex 上跑同一套流程。如果不把"协议本体"和"Claude Code 具体怎么实现
这个协议"分开写，以后每次想适配一个新的 coding agent 都要把整份 SOP 重新捋一遍。
建议明确拆成两层：

| 层次 | 内容 | 是否 Claude Code 专属 |
|---|---|---|
| **Spec 层**（协议本体） | 角色定义（Director/Alsos/Groves/Division/评审）、消息 schema（§7 of DESIGN）、节点状态机（§3）、假设 ledger schema（§9.2）、熵权/TOPSIS 数学、防漂移阈值规则 | **否**——纯数据结构和规则，任何能读写文件、能调用一个"LLM 判断"能力的 runtime 都能实现 |
| **Binding 层**（运行时绑定） | 用 `Agent()` 还是别的机制生成子 Agent、用 `WebSearch`/`WebFetch` 还是别的工具查资料、用 `AskUserQuestion` 还是别的方式等人类输入 | **是**——本文件下面写的都是 Claude Code 的具体绑定；Codex 版本需要另一份绑定文档，但可以复用同一份 Spec |

`LOS_ALAMOS_DESIGN.md` 就是 Spec 层；本文件是 Claude Code 的 Binding 层。未来做
Codex 适配时，理想情况下只需要新写一份 `LOS_ALAMOS_INTEGRATION_CODEX.md`，Spec 文件
不用动——这也顺带回应了 issue #2 里"哪些是 Claude Code 特性绑定"的问题。

### 1.1 Project Apollo：既有流水线的正式命名

AutoMCM-Pro 现有的 GitOps Checkpoint 主流水线正式定名 **Project Apollo**（内部代号，
`README.md`/对外文案是否采用另议）——理由见 `LOS_ALAMOS_DESIGN.md` §0.2。命名时注意：

- **不缩写成 "AP"**——`SKILL.md`/`AutoMCM_SOP.md` 里"AP 模式"已经是 Autopilot 的
  固定缩写，两套系统共用缩写会混淆，一律写全称 "Apollo"；
- Apollo 与 Los Alamos 是**平级的两种打法**，不是"Los Alamos 是 Apollo 的一个可选
  阶段"这种从属关系的简化说法——虽然在流水线时序上 Los Alamos 确实嵌在 Apollo 的
  `model_build/verify` 位置触发，但概念上二者是 Director 依题目性质二选一（或先
  Los Alamos 探索、再用 Apollo 的 Checkpoint 纪律收尾）；
- **Apollo 本身也需要跟着迭代**，不是只有 Los Alamos 在长东西。具体两项，均为
  **可选的质量加固**，不改变现有默认行为：
  1. **消息日志 + Groves 监控**（`LOS_ALAMOS_DESIGN.md` §6, §7）即使在纯 Apollo
     单线路径下也有独立价值——把 `review_request.md` 的自由文本审查过程顺便记一份
     结构化日志，为将来的过程审计/论文附录积累素材，成本很低（见 §6 Phase 0）；
  2. **Track R — Bletchley 红队**（`LOS_ALAMOS_DESIGN.md` §8.2）在 Apollo 单线模式
     下作为 `model_{n}_verify` 通过之后、Checkpoint ③ 之前的**可选**加固关卡：
     `verify_*.py` 只能证明"代码对自己声称的假设忠实"，红队额外去检查假设本身
     （尤其是 `falsifiable_if` 条件）扛不扛得住反例。不强制——很多简单子问题的
     假设一望即知没有反例空间，硬加一道红队没有意义，由 Director 视题目复杂度决定
     要不要在 Checkpoint ③ 汇报里加一段"红队复核"。

---

## 2. 角色 → Claude Code 执行机制映射

这是本文件最核心的一张表——决定了真正花钱 spawn 子 Agent 的地方只有三处，其余角色
要么是主 session 自己内联完成，要么是纯脚本，这直接回应"多 Agent 太贵"的顾虑：

| 角色 | 执行机制 | 说明 |
|---|---|---|
| **Director** | **就是主 session 本身**，不需要 spawn | 主 Agent 一直在跟随 `SKILL.md` 走，Los Alamos 只是它在特定条件下切换进入的一套额外行为，不是另一个 Agent |
| **T/E/O/CM Division（build+verify）** | `Agent()` spawn，**沿用现有"路径 A"模板**（`SKILL.md` 已有的 AP 子 Agent Prompt 模板），只是派发粒度从"按子问题编号"改成"按树节点 `node_id`" | 唯一需要真正独立、可并行执行代码的角色，必须是独立子 Agent |
| **Alsos 冷启动普查**（≥8 篇文献的结构化综述） | `Agent()` spawn，一次性、每子问题一次 | 任务重、需要独立上下文窗口，值得单独 spawn |
| **Alsos 按需响应**（`INTEL_REQUEST` 的零散查询） | **由发起请求的 Agent 自己内联执行**（Director 或某个 Division 子 Agent 自己调用 `WebSearch`/`WebFetch`），只是必须遵守"先写 `INTEL_REQUEST` 消息、查完写 `INTEL_RESPONSE` 消息"的记账规程 | 不需要真的有个"Alsos Agent 常驻"——"常驻服务"在协议层面是"随时可发起"，在实现层面是"谁要用谁自己查，但要按格式登记"，避免为每次小查询多付一次 Agent spawn 的成本 |
| **Track 0 语义筛选** | **Director 内联完成**（读提案 + 祖先路径 + Alsos 相关情报，直接给出 §8.1 的结构化裁定，用脚本写入 `messages.jsonl`） | 明确不 spawn 子 Agent——这是"高频但要便宜"的设计要求（DESIGN §8）落到实现层面的直接后果 |
| **Track R — Bletchley 红队** | `Agent()` spawn，**每个 `verify_pass` 候选一次**，不能是该候选的 Division 自己 | 中等成本、中等频率，跟 Track 2 评审共享"独立盲审"的实现套路（可复用同一份匿名化材料准备逻辑），但发生在更早的时间点、单独产出 `RED_TEAM_REPORT` |
| **Groves 自我状态监控** | **纯脚本 `scripts/groves_monitor.py`**，不涉及 LLM | 读 `messages.jsonl`/`pipeline.json`，算比例、比阈值、写状态文件，跟 `quality_gate.py` 是同类工具 |
| **Track 1 熵权/TOPSIS** | **纯脚本 `scripts/adjudicate.py entropy-weight`** | 同上，无 LLM 参与 |
| **Track 2 评审小组** | `Agent()` spawn ×3~5，**必须相互独立**（不同的 spawn 调用，各自拿到匿名化材料，互不可见彼此的判断，避免从众） | 唯二"故意要花钱多 spawn 几个独立视角"的地方，因为这里的独立性是机制核心 |

**结论**：一次完整的 Los Alamos 探索，典型情况下只 spawn 1（Alsos 普查）+ N（若干
Division，N 通常 2~3）+ N'（红队，约等于存活到 `verify_pass` 的候选数，通常和 N
接近）+ 3~5（评审小组）个子 Agent，其余全部是主 session 内联推理或纯脚本调用——
不是"七个角色七个常驻 Agent 一直跑"。红队的加入不会显著推高总 spawn 数量，因为它
只对已经自证通过、真正进入决赛候选池的方案跑一次，不是对树上所有节点都跑。

> **可选增强（仅 Claude Code）**：如果整场探索都在同一个交互式 Claude Code 会话里
> 进行（而不是 `claude --print` 的批处理式非交互调用），Alsos 的按需响应也可以选择
> 实现成用 `Agent(..., run_in_background: true)` 常驻一个真正的 Alsos 子 Agent，
> 其他 Agent 用 `SendMessage` 向它发起查询、拿到回复。这样能省去"每次查询都要重新
> 建立上下文"的开销，但依赖 Claude Code 特有的后台 Agent + `SendMessage` 机制，
> **不是可移植到 Codex 等其他 runtime 的基线方案**——按 §1 的 Spec/Binding 分层
> 原则，这应该作为 Claude Code binding 里的一个可选优化项单独标注，不写进 Spec 层。

---

## 3. 触发与开关

沿用项目现有"零命令 UX"哲学（`SKILL.md` 现有"首次启动协议"完全自然语言化）：

- **默认关闭**。触发条件（`LOS_ALAMOS_DESIGN.md` §4.1）由 Director 在
  `data_preprocessing` approved 后自动判定，不需要用户学习新命令或新参数；
- 用户也可以在启动阶段的自然语言问答里顺带表达（"这题我想多比较几种方法"），
  Director 据此提高触发倾向，不需要专门的 CLI flag；
- 若被触发，Director 用自然语言告知用户，例如：
  > "问题二检测到至少两种有文献支持的建模范式（排队论解析解 vs 仿真），且用户
  > 未指定优先方法。我会开启 Los Alamos 探索模式并行比较，预计比单一路径多花
  > 1~2 轮建模时间。是否继续？"（AP 模式下用户沉默 = 确认，MANUAL 模式下必须等待）
- `pipeline_manager.py init` 可选新增 `--los-alamos {auto|off|force}` 参数，默认
  `auto`（即上述自动判定），供想显式锁定行为的用户使用，但不是必需交互项。

---

## 4. 具体接入点

### 4.1 `AutoMCM_SOP.md`

新增 **§9「Los Alamos 探索协议」**，与现有 §1~§8 同级，作为强制规则的权威来源：
- §9.1 触发条件（引用 DESIGN §4.1）
- §9.2 假设树状态机与防漂移挂靠规则（引用 DESIGN §3, §5）—— 写成和现有 §4「强制
  代码自证协议」同等级别的"黄金律"，例如：
  > **黄金律（Los Alamos 模式专用）**：任何 `INTEL_REQUEST` 若既未挂靠已有假设
  > 节点、也未声明为受限额度的新方向提案，一律视为无效请求，不得据其检索结果修改
  > 模型。
- §9.3 双轨裁决与 Checkpoint LA（引用 DESIGN §8, §9.1）—— 明确"两轨冲突/高熵必须
  人类终审"是新增的**第 7 条绝对禁止事项**：不得在 AP 模式下自动裁定存疑的方案比较。

### 4.2 `.claude/skills/auto-mcm/SKILL.md`（已落地，以此为准）

**已实现，与下方描述若有出入以 `SKILL.md`「路径 C」原文为准。** 实际接入点与
最初规划有两处偏差，记录在这里供之后维护对照：

1. **没有新增 `pipeline_manager.py suggest-los-alamos` 子命令**——触发判定（DESIGN
   §4.1）最终做成 Director 内联判断（SKILL.md 路径 C Step 0），因为判定条件本身
   依赖 Alsos 的定性普查结果，脚本能做的机械部分（关键词扫描、时间预算）价值有限，
   不值得为此新增一个 `pipeline_manager.py` 子命令、多一层间接。
2. **假设树/裁决操作没有并入 `pipeline_manager.py`**，而是独立在
   `scripts/los_alamos/` 目录下（见 §4.3），保持"核心流水线零改动，探索层是纯
   addon"的边界更干净，也符合"这些流程是可替换 addon"的设计要求。

路径 C 完整步骤（Step 0 触发判定 → Step 1 Alsos 普查 → Step 2 冻结 scope anchor →
Step 3-4 展开+筛选 → Step 5 Division build+verify → Step 6-7 红队复核 → Step 8
Groves 巡检 → Step 9 双轨裁决 → Step 10a/10b 冠军映射或 Checkpoint LA）及全部 4 套
Prompt 模板（Alsos 普查 / Division / Bletchley 红队 / Track2 评审）**已写入
`SKILL.md`「Stage: model_build + model_verify」→「路径 C」**，不在本文件重复维护
第二份副本，避免两处文本漂移不一致。

### 4.3 `scripts/` 新增/扩展（已落地）

| 文件 | 状态 | 内容 |
|---|---|---|
| `scripts/los_alamos/bus.py`（新增） | ✅ 已实现+测试 | 报文总线：`send`/`read`/`validate` |
| `scripts/los_alamos/adjudicate.py`（新增） | ✅ 已实现+测试 | `screen`（Track0）、`redteam`（TrackR）、`entropy-weight`（Track1 熵权-TOPSIS）、`panel-vote`/`panel-entropy`（Track2 Copeland+分歧熵）、`combine`（汇总产出 leaderboard） |
| `scripts/los_alamos/groves_monitor.py`（新增） | ✅ 已实现+测试 | `check`：读 `messages.jsonl`+`pipeline.json`，超阈值追加 `DRIFT_ALERT`/`BUDGET_ALERT` |
| `scripts/los_alamos/hypothesis_tree.py`（新增） | ✅ 已实现+测试 | `expand`/`merge`/`backtrack`/`mark`/`rebuild`/`status`：假设树状态机物化视图 |
| `scripts/quality_gate.py` | ✅ 已实现+测试 | 新增 `message`/`ledger`/`red-team` 三个子命令（门控 5/6/7） |
| `pipeline_manager.py` | 未改动 | 保持零改动，探索层完全通过 addon 脚本 + 消息日志与之解耦 |
| `agent_memory_manager.py` / `contest_git.py` | 未改动 | 原计划的 ledger 合并辅助 / tag 前缀规则**尚未实现**，目前用 `memory/ledgers/*.json` 原始文件已够用，暂无必要新增；contest_git tag 冲突问题在未做整题级扩展（Phase 3）前不会出现 |

用法示例见 `scripts/los_alamos/README.md`。全部脚本已在 scratchpad 环境跑过一次
完整端到端流程（展开→筛选→build/verify→红队→双轨裁决→combine→Groves 告警），
包括故意构造的坏消息（未挂靠请求）、坏 ledger（悬空引用/依赖环/编造引用）验证硬性
校验确实拦截。

### 4.4 `CUMCM_Workspace/` 新增文件（仅 Los Alamos 模式激活时出现）

```
state/
  scope_anchor_{N}.md
  hypothesis_tree_{N}.json
  messages/problem{N}.jsonl
  groves_status_{N}.json
  red_team_reports_{N}.json
  leaderboard_{N}.md
memory/
  paradigm_pool_{N}.json
  literature_survey_{N}.md
  ledgers/problem{N}_{node_id}.json
  alternative_approaches_{N}.md
  groves_log.md
```

---

## 5. 向后兼容

- 未命中触发条件时，以上文件全不生成，现有单线流水线行为**零改动**；
- `pipeline.json` 新增字段（如 `los_alamos: {enabled, mode}`）需保证旧版本
  `pipeline_manager.py status` 在字段缺失时按 `enabled: false` 处理，不报错；
- `quality_gate.py` 新增子命令不影响现有 `lit`/`sanity`/`verify`/`consist`/`all`
  的调用方式和退出码语义；
- Checkpoint 机制（`request-review`/`check-approval`/`advance`）的现有语义不变，
  Checkpoint LA 只是新增了一种"强制不能自评自批"的特殊 stage，复用同一套底层命令。

---

## 6. 落地路线图（沿用 DESIGN 附录 A 的演进逻辑，落到具体交付物）

| 阶段 | 交付物 | 验证目标 |
|---|---|---|
| **Phase 0** | ✅ **已完成** — `messages.jsonl` 格式 + `groves_monitor.py`（纯脚本） | 现有单线流水线也能先用上"可审计消息日志 + 预算监控" |
| **Phase 1** | ✅ **已完成，且范围超出原计划** — `hypothesis_tree_{N}.json`、Track 0/R Prompt、Track 1 熵权-TOPSIS**已脚本化**（原计划归入 Phase 2）、Track 2 Copeland+分歧熵**已脚本化**、`quality_gate.py` 三个新门控、SKILL.md 路径 C 全流程 | 单层展开（固定 2~3 路对比）+ 完整双轨裁决已可实际运行，尚待真实比赛验证 ROI |
| **Phase 2（剩余部分）** | 多层展开的 best-first **自动调度**仍是 Director 手动循环调用 CLI（有意为之，见 `scripts/los_alamos/README.md`"落地阶段"一节），尚未有单独脚本 | 调度策略属于"弹性策略层"，暂不脚本化 |
| **Phase 3** | 合并（Evolution 式重组，`hypothesis_tree.py merge` 命令已就绪但未在 SKILL.md 中编排使用）+ 整题级多工作区扩展（`LOS_ALAMOS_DESIGN.md` 早期草案 §7 的整题级场景） | 高预算场景的"打全场"能力 |

**现状**：Phase 0/1 已经是可以实际使用的完整功能（触发判定 → Alsos 普查 → 分支
展开筛选 → build+verify → 红队 → 双轨裁决 → Checkpoint LA 或冠军映射，全链路
CLI 已实现并本地测试通过），只是单层展开（不做多轮 merge/backtrack 的自动化编排）。
建议先在 1~2 次真实比赛里试跑，验证"语义筛选剪枝 + 红队复核"相对"无差别单模型"
的实际收益后，再决定是否投入 Phase 2 的自动调度和 Phase 3 的整题级扩展。
