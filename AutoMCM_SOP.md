# AutoMCM-Pro: 工业级数学建模智能体操作规范 (SOP v2.1)

> **本文件是 AI 执行数学建模任务时的绝对行为准则。**
> 优先级高于所有其他提示词和对话指令。违反任何一条强制规定（Mandatory）视为严重故障。

---

## 0. 核心哲学

本系统的设计哲学是：**"人类作为 Router，AI 作为全栈引擎"**。

- AI 拥有高性能的数学推导、代码生成和学术写作能力，但可能产生"数学幻觉"。
- 人类拥有对真实世界约束的判断力和最终决策权。
- 因此，任何重大输出必须经过人类检查点（Checkpoint）才能流入论文。
- **"快"永远服从"对"。** 跳过验证门禁是绝对禁止的行为。

### 0.1 Skill 触发时的依赖同意

每个新的智能体会话首次触发 AutoMCM-Pro 时，必须先询问使用者是否安装核心 Python
建模依赖，以及是否准备可选的 LeanGate / Lean 4。本步骤不进行环境扫描，不静默
安装，不把沉默视为同意。获得明确同意后才可调用安装器；拒绝后同一会话不重复询问。
headless 环境无法等待回答时必须显示问题并暂停。后续只有实际命令因依赖缺失而失败
时才报告缺失项，不得擅自安装。

---

## 1. 模式声明协议 (Mode Declaration)

### 1.1 模式定义

系统支持两种互斥的工作模式。**模式一经在 `state/pipeline.json` 中锁定，本次会话内不可变更。**

#### AP 模式 (Autopilot — AI 主导)

| 角色 | 职责 |
|------|------|
| **AI (Pilot)** | 自主提出数学模型、推导公式、编写代码、生成验证脚本、撰写 LaTeX |
| **人类 (Copilot)** | 在 Checkpoint 审查 AI 输出，提供宏观方向调整，最终审批 |

适用场景：赛题有充足的先验知识可以支撑 AI 自主决策；或希望最大化自动化程度。

#### Manual 模式 (人类主导)

| 角色 | 职责 |
|------|------|
| **人类 (Architect)** | 在 `state/human_intervention.md` 中明确指定数学模型、核心公式、处理逻辑 |
| **AI (Copilot)** | **100% 忠实**地将人类规格转化为 Python 代码和 LaTeX，**严禁发散** |

**Manual 模式黄金律（AI 必须遵守）：**
1. 若 `human_intervention.md` 未覆盖某一细节，**必须停止执行，明确向人类提问**，而不是自行决定。
2. 禁止在 Manual 模式下主动"优化"或"改进"人类指定的模型结构。
3. 若人类指定的方法在数学上存在明确错误（如目标函数不可微），**必须先书面告知，经确认后方可修改**。

### 1.2 模式读取

每次 AI 被唤醒时，**第一件事**是执行：
```bash
python scripts/pipeline_manager.py status
```
读取 `state/pipeline.json` 中的 `"mode"` 和 `"current_stage"` 字段，确认自己的角色和当前位置，再开始工作。

---

## 2. 流水线阶段定义 (Pipeline Stages)

流水线由以下阶段顺序构成。每个阶段有明确的**入口条件**（前置阶段 `approved`）和**出口动作**（发起 Review 请求）。

```
[init]
   ↓
[problem_analysis]      ← Checkpoint ①
   ↓
[data_preprocessing]    ← Checkpoint ②
   ↓
[model_{n}_build]       ← （每个问题一次）
   ↓
[model_{n}_verify]      ← Checkpoint ③（每个问题一次，强制）
   ↓
[sensitivity_analysis]  ← Checkpoint ④
   ↓
[latex_draft]           ← Checkpoint ⑤
   ↓
[final_compile]
   ↓
[complete]
```

**阶段状态机：**
```
not_started → in_progress → pending_review → approved
                                  ↕
                               rework  →  in_progress
```

---

## 3. GitOps 检查点协议 (Checkpoint Protocol)

### 3.1 发起 Review（AI 必须严格执行）

每完成一个需要审查的阶段后，AI **必须**：

**Step A** — 写入审查报告：
```bash
python scripts/pipeline_manager.py request-review \
  --stage <stage_name> \
  --summary "本阶段工作摘要" \
  --results "关键数值/验证结果" \
  --concerns "发现的问题或不确定点" \
  --next "拟进入的下一阶段"
```
此命令会自动更新 `state/review_request.md` 和 `state/pipeline.json`。

**Step B** — **根据模式决定后续行为**：

#### AP 模式：AI 自评自批，自动推进

在 `state/human_intervention.md` 中追加 AI 自评：

```
[APPROVED:<stage_name>:<round>]
AI 自评（<stage_name>）：
- 本阶段完成情况：<一句话总结>
- 关键数值检查：<列举 2-3 个代表性结果>
- 验证状态：<PASS / 本阶段无强制验证>
- 进入下一阶段的理由：<简要说明>
```

然后立即执行：
```bash
python scripts/pipeline_manager.py advance <stage_name>
```

**无需停下来等待人类输入，直接开始下一阶段。**
（人类可随时查看 `state/review_request.md` 审阅自评记录。）

#### MANUAL 模式：必须等待人类批准

在终端输出：
```
╔══════════════════════════════════════════════════════════╗
║      CHECKPOINT — 等待人类审查                            ║
║                                                          ║
║  阶段: [stage_name]                                      ║
║  报告: CUMCM_Workspace/state/review_request.md           ║
║                                                          ║
║  请操作:                                                 ║
║  1. 阅读 review_request.md                               ║
║  2. 在 human_intervention.md 中填写意见                   ║
║     • 同意 → 写入 review_request 中的阶段/轮次批准标记     ║
║     • 修改 → 写入对应阶段/轮次返工标记 + 具体指令          ║
║  3. 在终端输入「继续」后按 Enter                           ║
╚══════════════════════════════════════════════════════════╝
```
然后**不再执行任何代码或写入任何文件**，等待人类输入。

### 3.2 处理 Review 结果

**AP 模式**：AI 自评完成后直接 advance，无需此步骤。

**MANUAL 模式**，AI 被唤醒后：
```bash
python scripts/pipeline_manager.py check-approval --stage <stage_name>
```

**若返回 `APPROVED`：**
- 执行 `pipeline_manager.py advance <stage_name>`
- 继续下一阶段

**若返回 `REWORK`：**
- 读取 `human_intervention.md` 中的具体修改意见
- **只针对被批评的部分**重新执行，其余已批准的内容不得触碰
- 重新执行完毕后再次发起 Review
- 在 `memory/evaluation_log.md` 中记录本轮 Rework 的原因和改动

**若文件内容不明确：**
- 向人类输出一条清晰的问题，等待澄清

---

## 4. 强制代码自证协议 (Self-Verification Mandate)

### 4.1 黄金律

> **任何 `src/models/` 中的求解代码，在其对应的 `src/verifications/` 验证脚本通过之前，结果数据和图表禁止写入论文。**

### 4.2 验证脚本命名规范

| 模型脚本 | 验证脚本 |
|---------|---------|
| `src/models/problem1_lp.py` | `src/verifications/verify_problem1_lp.py` |
| `src/models/problem2_regression.py` | `src/verifications/verify_problem2_regression.py` |

### 4.3 验证脚本必须包含的测试（按模型类型）

#### 优化模型（LP / QP / MIP / NLP）

```python
# verify_problem1_xxx.py 必须执行以下检查：

# [V-OPT-1] 原始可行性：所有约束被严格满足（不等式留5%裕量检查）
assert all(g_i(x_opt) <= 0 + 1e-6 for i ...), "约束违反"

# [V-OPT-2] 替代求解器交叉验证：
# 若主求解器为 SLSQP，则用 differential_evolution 重新求解
# 若两者目标值差异 > 1%，标记为"可能非全局最优"，写入 review_request

# [V-OPT-3] 扰动测试：
# 对最优解每个分量施加 ±0.1% 随机扰动，验证扰动后目标函数值不优于原始值

# [V-OPT-4] 灵敏度快检：
# 关键约束 RHS 扰动 ±5%，计算目标函数变化率（影子价格估计）
```

#### 回归 / 机器学习模型

```python
# verify_problem2_xxx.py 必须执行以下检查：

# [V-REG-1] 残差正态性：Shapiro-Wilk 检验（p > 0.05 方通过）
from scipy.stats import shapiro
stat, p = shapiro(residuals)
assert p > 0.05, f"残差非正态 (p={p:.4f})，考虑 Huber 损失或变换"

# [V-REG-2] 异方差性：Breusch-Pagan 检验
from statsmodels.stats.diagnostic import het_breuschpagan
_, p_bp, _, _ = het_breuschpagan(residuals, X)
# 若 p < 0.05，在 review_request 中标记，建议 WLS 或稳健回归

# [V-REG-3] 自相关：Durbin-Watson 统计量（1.5 < DW < 2.5 为正常范围）
from statsmodels.stats.stattools import durbin_watson

# [V-REG-4] 泛化能力：5折交叉验证，CV-RMSE / in-sample RMSE < 1.2
# [V-REG-5] 蒙特卡洛稳定性：Bootstrap 1000次，计算参数置信区间
```

#### 微分方程 / 动力学模型

```python
# [V-ODE-1] 守恒量验证：
# 若模型为守恒系统，验证仿真全程守恒量偏差 < 0.1%

# [V-ODE-2] 边界条件检验：
# 验证 t=0 和 t=T 的数值解满足初始/边界条件（误差 < 1e-6）

# [V-ODE-3] 网格收敛性：
# 步长 h 和 h/2 的解之差 < 0.1%（验证数值方法收敛）

# [V-ODE-4] 已知解析解对比：
# 若存在简化情形的解析解，数值解与解析解误差 < 1%
```

#### 图论 / 网络模型

```python
# [V-GRF-1] 路径合法性：验证输出路径中每条边确实存在于原图
# [V-GRF-2] 流守恒：对每个中间节点，入流量 = 出流量（误差 < 1e-9）
# [V-GRF-3] 小规模暴力验证：在 ≤10 节点的子图上，与穷举解对比
```

### 4.4 验证报告格式

每个验证脚本的最后必须打印结构化报告：
```python
print("=" * 60)
print(f"VERIFICATION REPORT — {model_name}")
print("=" * 60)
for check_id, result, detail in checks:
    status = "✓ PASS" if result else "✗ FAIL"
    print(f"  [{check_id}] {status}  {detail}")
print("=" * 60)
print(f"OVERALL: {'ALL PASS' if all_pass else 'FAILED — SEE ABOVE'}")
```
验证报告全文必须被复制到 `state/review_request.md` 对应的 Checkpoint 中。

---

## 5. AP 模式执行规范

### Phase 1 — 破题与文献调研

1. 读取题目，在 `memory/thought_process.md` 中写下：
   - 问题类型判断（优化/预测/仿真/图论/混合）
   - 每个小问拟用模型及选择理由
   - 文献调研结果（用运行时提供的网络检索/网页抓取工具，至少 5 篇）
2. 发起 **Checkpoint ①**

### Phase 2 — 数据预处理

1. 编写 `src/models/00_data_eda.py`，运行并验证
2. 所有图表 → `latex/images/`，结果摘要 → `memory/thought_process.md`
3. 发起 **Checkpoint ②**

### Phase 3 — 模型构建 + 验证（每个小问循环）

1. 编写 `src/models/problem{n}_{type}.py`
2. 运行成功后，**立即**编写 `src/verifications/verify_problem{n}_{type}.py`
3. 运行验证脚本，检查是否全部通过
4. 若有 FAIL：修复模型代码，重新验证，直到全通过
5. 发起 **Checkpoint ③**（含完整验证报告）

### Phase 4 — 灵敏度分析

1. 编写 `src/models/sensitivity.py`
2. 编写 `src/verifications/verify_sensitivity.py`（验证灵敏度计算的数值稳定性）
3. 发起 **Checkpoint ④**

### Phase 5 — LaTeX 写作

1. 按论文模板逐章撰写，每章节三轮自审
2. 发起 **Checkpoint ⑤**
3. 批准后编译 PDF

---

## 6. Manual 模式执行规范

### 前置要求

在 AI 开始任何工作之前，人类必须在 `state/human_intervention.md` 的 `[MANUAL_SPEC]` 区块中填写：

```markdown
## [MANUAL_SPEC]

### 问题一
- **模型类型**: [e.g., 非线性规划]
- **决策变量**: [列举所有变量及其含义]
- **目标函数**: [精确数学表达式]
- **约束条件**: [精确数学表达式，每条一行]
- **求解方法**: [e.g., scipy.optimize.minimize, method='SLSQP']
- **特殊处理**: [e.g., 需要对数据做对数变换]
```

### AI 在 Manual 模式下的行为准则

| 情形 | AI 必须做的 |
|------|------------|
| 规格清晰 | 100% 按规格实现，不添加任何额外逻辑 |
| 规格有歧义 | 停止，书面提问，等待澄清 |
| 规格有数学错误 | 停止，指出错误，提供修正建议，等待人类确认 |
| 规格未覆盖边界情况 | 停止，描述边界情况，等待人类指示 |

**Manual 模式下严禁的行为：**
- 自行选择"更好的"替代模型
- 在规格之外添加约束条件
- 修改人类指定的目标函数
- 基于"数学直觉"进行任何发散性扩展

---

## 7. 绝对禁止清单

1. **禁止在 MANUAL 模式下跳过 Checkpoint**：MANUAL 模式必须等待人类写入 `[APPROVED:<stage>:<round>]` 后方可推进；AP 模式由 `request-review` 记录绑定阶段与轮次的 AI 自评后自动推进
2. **禁止将未验证的数据写入论文**：`verify_*` 脚本必须全通过才能引用该模型结果
3. **禁止在 Manual 模式下发散**：见第6节
4. **禁止覆写已 `approved` 的内容**：除非 Rework 指令明确指向该内容
5. **禁止静默跳过验证失败**：若 `FAIL` 无法自主修复，必须在 Checkpoint 中如实报告
6. **禁止在代码未实际运行时声称"已验证"**
7. **禁止在 Los Alamos 探索层跳过 Checkpoint LA 的强制人类终审**：即使当前锁定为 AP
   模式，只要触发第 9 节定义的存疑条件（两轨冲突 / 分歧熵超阈值），也不得自评自批
   自动推进——这是对第 1 条"AP 模式由 AI 自评自批"规则的唯一例外，详见 §9.2

---

## 8. 故障恢复协议

若 AI 在某阶段意外中断，重新启动后：

```bash
python scripts/pipeline_manager.py status
```

根据 `current_stage` 的状态：
- `in_progress` → 从该阶段重新开始，不要重复已完成的子步骤
- `pending_review` → 重新显示 Checkpoint 等待提示，等待人类输入
- `rework` → 读取最新的 `human_intervention.md`，执行 Rework

所有中间结果（`data/`, `src/`, `latex/images/`）**优先复用，不重复计算**，除非 Rework 指令明确要求重算。

---

## 9. Los Alamos 探索协议（可选层，触发时强制）

> 架构设计与理由见 `LOS_ALAMOS_DESIGN.md`；具体执行步骤（Alsos/Division/Bletchley/
> 评审小组的 Prompt 模板与 CLI 命令）见 `.claude/skills/auto-mcm/SKILL.md`「路径
> C」。本节只规定**必须遵守的刚性规则**，不重复"怎么做"的操作细节。

### 9.1 定位

Los Alamos 是叠加在现有流水线（内部代号 **Project Apollo**）之上的**可选探索层**，
在单个子问题存在真实建模范式分歧时，由 Director 对该子问题触发。它：

- **不是第三种模式**：不改变第 1 节 AP/MANUAL 模式锁定，锁定的模式依然决定"谁最终
  拍板"，Los Alamos 只改变"拍板前要不要先比较几个方案"；
- **不是与 A/B 并列的整体路线**：是子问题级别的加注，可以只对 N 个子问题中的某一个
  触发，其余子问题走原有单模型流程；
- **默认关闭**：未命中触发条件（SKILL.md 路径 C Step 0）时，本节全部规则不适用。

### 9.2 治理刚性层（不可变通，违反视为严重故障，与第 7 节绝对禁止清单同级）

1. **情报请求必须挂靠假设 DAG 节点**：任何 `INTEL_REQUEST` 报文必须填写
   `ref_assumption_id`（挂靠已有假设）或 `new_assumption_proposal`（声明为受限额度
   的新方向）二选一，两者皆无视为无效请求，**不得据其检索结果修改模型**。
   `quality_gate.py message` 是该规则的硬性执行者，退出码 1 时不得放行。
2. **探索型请求受配额约束**：`new_assumption_proposal` 类请求超出每分支每阶段的
   默认额度（2 次）时，必须先取得 Director 的书面批准（记入报文日志），不得静默
   放行。
3. **红队复核是候选进入决赛圈的必要条件**：任何分支在 `verify_pass` 之后，必须有
   一条 `verdict ∈ {survived, weakened}` 的 `RED_TEAM_REPORT`（由
   `quality_gate.py red-team` 校验）才可进入决赛圈；`verdict = broken` 或缺失记录
   一律禁止晋级，也**禁止将其结果写入论文**——与第 4 节自证协议的黄金律同等效力。
4. **两轨冲突或分歧过大必须升级人类终审**：Track 1（熵权-TOPSIS）与 Track 2（专家
   小组两两比较）冠军不一致，或 Track 2 平均分歧熵超过阈值，**无论当前锁定 AP 还是
   MANUAL 模式**，都必须触发 Checkpoint LA 并真正等待人类输入——**AI 不得自评自批**。
   这是对第 3 节"AP 模式由 AI 自评自批自动推进"规则的唯一例外，也是第 7 节第 7 条
   绝对禁止事项。两轨呈方向性矛盾（如 Track 1 数值领先但 Track 2 一致认为其核心
   假设不成立）时优先级最高，即使分歧熵本身不高也必须升级。
5. **范围锚点冻结后不可静默修改**：`scope_anchor_{N}.md` 一经在探索开始时写入，
   后续若确有必要修改题意理解，必须发起 `AMEND_ANCHOR` 报文并强制触发 Checkpoint
   LA 级人类确认，不得因"越查越觉得应该换个理解方式"而悄悄改变问题定义。
6. **分支决策必须查询假设树物化视图，不得只凭叙述记忆**：是否继续展开、
   哪些分支进入 build/verify、决赛圈还剩几个候选，这类判断动手前必须先跑
   `hypothesis_tree.py status` 拿到当前真实状态——`hypothesis_tree_{N}.json`
   不是写完就不再读的审计日志，是决策的输入来源，见 SKILL.md 路径 C 相应
   Step 前的 `status` 调用。

### 9.3 假设 Ledger 黄金律

1. 分支 build 过程中依赖的每一条关键假设，必须在
   `memory/ledgers/problem{N}_{node_id}.json` 中登记，字段包括
   `id/statement/math_form/source/source_ref/citation_id/depends_on/
   downstream_impact/falsifiable_if/proposed_by`，`depends_on` 必须正确指向上游
   假设 id（不得悬空、不得成环，`quality_gate.py ledger` 校验）。
2. **红队必须实际验证 `falsifiable_if` 条件**，不得采信 Division 自陈"未触发"——
   这是红队复核区别于自证协议的核心职责（自证协议只能验证"代码对自身声称的假设是否
   忠实"，无法验证"假设本身是否站得住"）。
3. `source: literature` 的假设，其 `citation_id` 必须真实存在于对应的
   `paradigm_pool_{N}.json` 条目中，禁止编造文献依据；`quality_gate.py ledger`
   校验不通过时禁止 advance。

### 9.4 落选方案的处理

决赛圈中未胜出的分支**禁止删除**，必须归档至
`memory/alternative_approaches_{N}.md`，作为论文"模型比较"章节的素材来源。这不是
可选的清理步骤，落选分支的假设 ledger 和验证报告本身就是竞赛论文里"我们比较过其他
方法、并说明为什么不采用"这一学术论证的直接依据。

### 9.5 与其他章节的关系

- 第 1 节模式锁定：Los Alamos 不改变模式锁定，只在触发时增加 §9.2 第 4 条这一唯一
  例外；
- 第 3 节 Checkpoint 协议：Checkpoint LA 复用 `request-review`/`check-approval` 的
  底层机制，但流程上强制走"MANUAL 模式等待人类反馈"分支，不适用"AP 模式自评自批"
  分支；
- 第 4 节强制代码自证协议：自证协议（"代码是否忠实"）与红队复核（"假设是否站得住"）
  是两道独立且都必须通过的关卡，二者不可互相替代。

### 9.6 Track 2 分歧过高时的中间步骤：RAND Delphi 匿名收敛（可选，先于 Checkpoint LA）

Track 2 评审小组分歧熵超过阈值时，**不必立刻升级 Checkpoint LA**——先尝试一轮
Delphi 式匿名收敛：把当轮投票按候选对/维度聚合成不带评审身份的摘要（票数分布 +
理由列表，`scripts/los_alamos/adjudicate.py delphi-summary`），交给评审小组阅读后
重新投一轮（`panel-vote --round N+1`）。收敛（分歧熵回落到阈值以下）则按 §8.5 汇总
规则正常晋级；仍不收敛才升级 Checkpoint LA。

**约束**：

1. 最多尝试 **2 轮**收敛（含首轮共 3 轮投票），第 3 轮仍不收敛必须升级人类终审，
   不得无限重试——这是"匿名反馈能减少从众/固执，但不能保证一定收敛"这一事实的
   直接体现，避免用"再试一轮"无限拖延本该交给人类判断的存疑情况；
2. 摘要必须真正匿名（不带 `judge_id`），否则失去 Delphi 法"匿名反馈防止权威压制/
   从众"的核心价值，退化成普通轮流发言的会议讨论；
3. 两轨方向性矛盾（DESIGN §8.5，Track1 数值好看但 Track2 认为假设站不住）时，
   直接升级 Checkpoint LA，不适用本节的多轮收敛——方向性矛盾不是"评审没讨论够"，
   是需要人类判断的实质分歧。

---

## 10. Project Skunk Works — 轻量快速模式（可选，触发时生效）

> 灵感来自 Lockheed Kelly Johnson 的 14 条法则：团队规模压到最小、单一负责人直接
> 对使用者负责、跳过非必要的中间流程。填补 Project Apollo（严谨 Checkpoint）和
> Los Alamos（更贵的多假设探索）之间的空白——题目简单、时间紧迫时，两者都嫌重。

### 10.1 触发方式

Skunk Works 可以通过两种方式触发：

1. **人类明确要求**：用户在启动时显式要求（"简单跑一下""时间不多，快一点""不用
   太严谨"），或 `pipeline_manager.py init --skunk-works` 显式开启。
2. **Director 自主判断触发（仅限"时间紧迫"这一个理由）**：Director 判断剩余时间
   预算明显不足以支撑全套严谨流程（例如用户告知或 `pipeline.json` 记录的截止时间
   逼近、对话中出现"还有 X 小时就要交"这类时间信息但用户没有直接说"简化"）时，
   可以自主决定进入 Skunk Works——但**必须先用自然语言明确告知用户"判断时间紧迫，
   将采用 Skunk Works 轻量模式简化流程"**，不得静默切换；用户随后若明确反对（要求
   维持全套严谨度），Director 必须服从并退回全套模式。

**触发依据只能是"时间预算"，不能是"对题目难度的主观评估"**——不允许 Director 仅
因为"这题看起来简单"就自主进入 Skunk Works，题目难度判断本身可能有偏差，而时间
约束是对话或 `pipeline.json` 里客观、可核实的信息。未命中以上任一条件（人类没提，
时间也不紧迫）时，默认保持全套严谨模式。

这与 Los Alamos／Andon／RAND Delphi 的自主触发不同——那几个自主触发的方向都是
"增加"严谨度，判断失误的代价只是多做一点工；Skunk Works 自主触发的方向是"降低"
严谨度，判断失误的代价是使用者不知不觉拿到一份比预期单薄的东西，所以哪怕开放给
Director 自主判断，也必须保留"先告知、后执行"这一步，不能变成静默降级——
"降低标准"这件事本身仍然需要让人类知情，AI 不能替用户悄悄决定要不要少做验证。

### 10.2 放宽的规则（仅这些，其余照旧）

1. **文献引用门控降到 ≥1 篇**（正常 ≥2 篇），`quality_gate.py lit` 自动读取
   `pipeline.json` 的 `skunk_works` 标志放宽阈值；
2. Checkpoint 汇报可以更简短（不要求列举 2-3 个代表性数值，一句话总结即可），
   但**仍然必须发起 Checkpoint、仍然必须走 AP 自评自批或人类审批流程**——
   Skunk Works 精简的是"汇报的详细程度"，不是"要不要有审查这件事"；
3. **仅限 AP 模式**——MANUAL 模式本身就要求人类逐条确认规格，跟"快速轻量"的
   诉求矛盾，若用户同时要求 MANUAL 和 Skunk Works，需先向用户澄清取舍。

### 10.3 绝对不放宽的规则（第 4 节强制代码自证协议在 Skunk Works 下同样生效）

**`verify_*` 未通过不得写入论文**这条黄金律没有 Skunk Works 版本的例外——"快"
体现在流程精简，不体现在降低对结果正确性的要求。省下来的时间应该花在"少做一些
探索性的工作"，而不是"对已经在做的工作降低验证标准"。

---

## 11. Andon Cord — 紧急停止协议（任意角色、任意时刻可用）

> 灵感来自丰田生产方式：产线上任何一个工人，不分职级，发现异常都有权拉绳让整条
> 线立刻停下来（Toyota Production System，Taiichi Ohno / Eiji Toyoda）。

### 11.1 与现有 Checkpoint 机制的区别

Checkpoint 是**排定好的**审查点（在特定阶段结束时触发）；Los Alamos 的
Checkpoint LA 是**特定条件触发的**升级（两轨冲突/分歧过高）。Andon 是**任意时刻、
任意角色**都能主动发起的紧急停止——填补"发现问题但还没到下一个排定的 Checkpoint"
这个空隙。例如：Bletchley 红队在探索过程中发现的不是"某个假设站不住"（这是红队
正常职责范围内的发现，走 §9.2 的既有流程），而是"整个问题理解方向从根本上错了"
这种超出当前阶段职责范围的重大发现，此时不应该等到下一个排定的 Checkpoint 才
上报。

### 11.2 使用方式

```bash
# 任意 Agent 发现严重问题时
python scripts/pipeline_manager.py andon-pull --reason "一句话说清楚问题" --by "<角色名>"

# 效果：state/pipeline.json 记录告警；此后所有 advance 调用返回非 0 退出码并
# 拒绝执行，直到 andon-clear——这是硬性阻断，不是建议性警告
```

**人类确认问题已处理后**：

```bash
python scripts/pipeline_manager.py andon-clear --resolution "怎么解决的，一句话说清楚"
```

`andon-status` 可随时查询当前状态（退出码 0=正常，1=已拉下）。

### 11.3 使用边界（防止滥用成"逃避正常流程的借口"）

1. **不是普通 rework 的替代品**——某个具体阶段的问题（假设需要调整、代码有 bug）
   走第 6 节 Rework 执行规程即可，不需要拉 Andon。Andon 保留给"超出当前阶段职责
   范围"或"可能影响已经批准的更早阶段"这类问题；
2. **拉绳后必须给出具体原因**（`--reason` 必填），不接受空泛的"感觉不对"；
3. **清除必须给出具体解决方案**（`--resolution` 必填），清除记录连同原始告警
   原因一起存档，不会互相覆盖，供事后审计——这是"拉绳有代价、不能随手拉"的
   设计意图，跟 §9.2 探索型请求配额、§4 强制自证协议的"刚性不可变通"精神一致；
4. AP 模式下，Andon 拉下后即使后续自评看起来一切正常，也**不能自动 andon-clear**
   ——清除本身需要人类确认（或走 Checkpoint 同等的自评自批记录），不是纯技术性
   动作。

---

## 12. Go/No-Go 发射前检查 — final_compile 阶段强制门控

> 灵感来自 NASA 任务控制中心：阿波罗任务发射前，每个分系统（推进/导航/电力/
> 生命维持……）独立回报 go 或 no-go，Flight Director 逐一点名，全部 go 才发射。

### 12.1 触发时机

**`final_compile` 阶段开始前必须运行**，不是可选步骤：

```bash
python scripts/quality_gate.py launch-check
# 退出码 0 → 全部 GO，可以进入 final_compile
# 退出码 1 → 有 NO-GO 项，禁止进入 final_compile，按报告逐项修复后重跑
```

### 12.2 检查内容（复核"该做的事有没有做完"，不是重新做验证）

Andon 状态、model_*_build/verify 阶段完整性、LaTeX 引用的图片是否物理存在、
论文正文有无残留 TODO/FIXME/占位标记、（若启用 Los Alamos）假设 ledger 完整性。
**这是复核，不是重新验证**——真正的数值/逻辑正确性已经在 §4 强制代码自证协议里
把关过，Go/No-Go 抓的是"验证都做完了，但论文本身有没有明显的遗漏"这一类问题。

阶段完整性只检查 `model_N_build`/`model_N_verify` 中 `N ≤ problem_count` 的部分——
`pipeline.json` 出于实现原因固定预置 `model_1`~`model_3` 三组阶段位，单/双问题竞赛
里超出实际题目数的那些阶段永远不会被 `advance` 到，不应计入 NO-GO 判定
（`scripts/quality_gate.py` `gate_launch_check()` 按 `problem_count` 过滤）。

### 12.3 与第 7 节绝对禁止清单的关系

新增第 8 条：**禁止跳过 `launch-check` 直接进入 `final_compile`**，即使 AP 模式
自评认为一切正常，也必须先跑这个门控拿到 GO 裁定——这是纯脚本判定（退出码），
不依赖 AI 的自我报告，与项目一贯"硬检查脚本，不是 AI 行为规则"的哲学一致。

---

## 13. Project Kaizen（改善）— 通过门控后的主动质量打磨循环

> 灵感来自丰田生产方式的"改善"：即使产线没有异常（Andon 没拉），一线员工依然
> 持续寻找可以做得更好的地方，小步快跑、永不停歇（Taiichi Ohno）。这是 Andon
> 在时间轴另一端的对应——Andon 管"错了要不要停"，Kaizen 管"没错要不要还能
> 更好"。二者合起来才是完整的 TPS 双面。

### 13.1 定位：填补"过关就是过关"的空白

在 Kaizen 之前，流水线只有**反应式**迭代：`quality_gate.py` 的各项门控是二元
判定（PASS/FAIL），`rework` 只在门控真的 FAIL 时触发——一旦 `sensitivity_analysis`
的所有验证都 PASS，流程直接往下走，没有机制去问"结果对，但够不够好"。Kaizen
补的就是这一层**主动**判断：结果已经正确（`verify` 已通过），但 Director 主动
评估还有没有值得打磨的空间。

**Kaizen 不是 rework 的替代品**——rework 处理"错了"，Kaizen 处理"没错但普通"，
两者面对的问题性质不同，触发条件也不同（rework 由门控 FAIL 触发，Kaizen 由
主动自评触发）。

### 13.2 触发时机与质量自评

**只在 `sensitivity_analysis` 已 approved 之后**（该子问题的建模、验证、灵敏度
分析全部通过 §4 强制代码自证协议）才有意义调用，`latex_draft` 开始前是最自然
的检查点：

```bash
python scripts/pipeline_manager.py kaizen-assess --problem-n {N} \
  --significance {1-5} --robustness {1-5} --assumptions {1-5} --completeness {1-5} \
  --weakest "<最弱维度的一句话说明>"
# 退出码 0 = PROCEED（放行）  1 = ROUND_RECOMMENDED（建议打磨一轮）
```

四个自评维度，如实按题目实际情况打分，不是走过场：

| 维度 | 含义 |
|---|---|
| `significance` 显著性 | 结果/改进幅度是否有实际说服力（跟朴素基准比是否有数量级或统计意义上的差异，而不是自吹） |
| `robustness` 稳健性 | 灵敏度分析是否显示结果对关键假设参数过于敏感（比如 ±10% 扰动就导致结论反转） |
| `assumptions` 假设合理性 | 模型假设有没有明显可以放宽/改进但没做的粗糙简化 |
| `completeness` 论证完整性 | 有没有该讨论但论文里没讨论的角度（比如遗漏了明显的备择方案对比） |

均分 ≥ 4.0 视为达标，直接 PROCEED；均分 < 4.0 且轮数未用满，裁定
ROUND_RECOMMENDED——但这只是**建议**，不是强制，见 13.3 的触发闸门。

### 13.3 是否真的开始打磨：时间预算是唯一闸门

`ROUND_RECOMMENDED` 不等于必须打磨——是否真的开一轮，取决于**时间预算**（与
Los Alamos Step 0、Skunk Works §10.1 用的是同一个客观信号，方向相反：Skunk
Works 在时间紧迫时降低严谨度，Kaizen 在时间充足时提升润色度）：

- 时间预算充足（用户告知或 `pipeline.json` 有截止日期字段时距今 > 阈值，
  与 Los Alamos 沿用同一 48h 默认值） → 可以打磨；
- 时间紧迫或没有时间信息 → 即使 `ROUND_RECOMMENDED`，也应该直接放行，不主动
  开新一轮——普通及格线以上的结果按时交付，优先于锦上添花。

判定要打磨后：

```bash
python scripts/pipeline_manager.py kaizen-round-start --problem-n {N} --plan "<这一轮打算改什么>"
# 到轮数上限（默认每题 2 轮，init --kaizen-max-rounds 可调）会直接拒绝，exit 1
```

打磨内容必须针对 `--weakest` 指出的具体短板，不是随意重跑。**改进后必须重新
走 §4 强制代码自证协议**——Kaizen 不能绕过验证，"改进"若验证不通过就是普通的
`rework`，不能算作 Kaizen 轮次的产出写入论文。

一轮结束后重新 `kaizen-assess`，若仍未达标且时间预算允许可以再来一轮，直到
均分达标、轮数用满、或时间预算判定不再充足，三者任一命中就必须放行进入
`latex_draft`。

### 13.4 透明性：不能变成静默地无限打磨

打磨前必须先用自然语言告知用户"质量自评发现 <维度> 偏弱，时间预算允许，将
打磨一轮"，打磨结束后告知改进了什么、新的自评结果——这与 Skunk Works §10.1
的"先告知、后执行"是同一条精神：主动决策可以自主做，但不能让用户完全不知情
地看到流水线突然多花了几轮时间。

---

## 14. 工作日志 — 单文件、简体中文、完整覆盖

> 定位与 Los Alamos 的 `bus.py` 事件溯源不同：`bus.py` 是给脚本/门控消费的
> 结构化真相来源，工作日志是给**人事后翻阅**用的流水账，纯文本、按时间顺序，
> 不需要额外工具解析。

### 14.1 记什么、不记什么

`CUMCM_Workspace/memory/worklog.md` 用户消息、Agent 关键决策、代码/门控执行
结果三类都要有记录，覆盖的是**类别**而不是要求逐字复刻所有中间推理过程：

- **阶段推进/返工/Andon/Kaizen 的决策结果**：由 `pipeline_manager.py`
  在 `advance`/`rework`/`andon-pull`/`andon-clear`/`kaizen-assess`/
  `kaizen-round-start` 内部自动写入，**不需要 Agent 额外调用**；
- **门控 PASS/FAIL 结果**：由 `quality_gate.py` 的 `run_gate()` 自动写入
  （取每条门控消息的第一行），同样不需要 Agent 额外调用；
- **用户说了什么、Agent 做出了什么关键判断**（这两类脚本本身看不到，只有
  Agent 自己知道）：Agent 在每次处理新的用户消息、以及做出不由脚本自动记录
  的关键判断时（比如 Los Alamos Step 0 的触发判定理由、Skunk Works 是否
  自主触发的理由），手动调用：
  ```bash
  python scripts/worklog.py append --role user  --text "<用户这次说的话，一句话概括>"
  python scripts/worklog.py append --role agent --text "<Agent 的判断/决定，一句话>"
  ```

### 14.2 最省 token 的具体做法

**日志内容就是本来就会自然产生的短句，不为了记日志而单独生成一轮总结**——
`pipeline_manager.py`/`quality_gate.py` 打印到终端的那句话本身就是日志内容，
只是顺手多写一份到文件；Agent 手动调用时也要求"一句话概括"，不铺陈、不复述
长篇原文（单行超过 300 字符会被 `worklog.py` 自动截断）。这是"完整覆盖类别"
和"省 token"两个目标能同时达成的关键——完整靠的是"类别不遗漏"，省钱靠的是
"每条记录本身很短、且大部分是免费的脚本副作用，不是额外的 LLM 生成"。

### 14.3 用法

```bash
python scripts/worklog.py tail -n 20     # 查看最近 20 条，快速回顾这次做了什么
```

`worklog.md` 是纯追加文件，不做修改/删除——完整的审计价值来自"从不回改"，
和 `los_alamos/bus.py` 的事件溯源、`contest_git` 的提交历史是同一条哲学。

---

## 15. 文献引用：真实性核验 + 跨子问题共享池 + 结构化导出

> 第 5 节 Phase 1 "文献调研至少 5 篇"原来只要求"用检索工具找到就行"，
> `quality_gate.py lit` 也只检查 thought_process.md 里有没有 DOI/URL 形状的
> 字符串——**不检查那个 DOI 是不是真的存在**。LLM 编造引用（标题、作者、DOI
> 全部看起来合理但查无此文）是已知的常见失败模式，本节补上这个漏洞。

### 15.1 三个组件

1. **真实性核验**（`scripts/cite_check.py verify`）：DOI 用 CrossRef API
   （`api.crossref.org`，免费、无需注册）核验是否真实存在，返回 404 视为
   "疑似编造，禁止用于论文"；无 DOI 的用 URL 做 HEAD 请求核验可达性；网络
   异常时判定为"无法确定"，不等同于"确认造假"，不因为网络问题误伤真实引用。
2. **跨子问题共享池**（`CUMCM_Workspace/memory/citations.bib`，标准 BibTeX
   格式）：全项目唯一的引用注册表，按 DOI/URL/标题标准化后去重——同一篇文献
   被第 2 个子问题用到时，`register` 会命中已有条目、只追加一个 `problem{N}`
   标记，不会重复搜索、重复注册。
3. **结构化导出**（`cite_check.py export-bibitems`）：把已验证的结构化字段
   渲染成 `\bibitem{...}` 文本块，直接粘贴进 `latex/main.tex` 的
   `thebibliography` 环境（模板本身用 `\bibitem` 手写列表，不用 `.bib` 编译，
   `citations.bib` 只是登记用的结构化中间态，不改变现有编译方式）。

### 15.2 流程：搜索时怎么用

```bash
# 每找到一篇文献，登记一次（会自动去重，命中已有条目会直接返回已有 key）
python scripts/cite_check.py register \
  --title "..." --author "..." --year 2020 --journal "..." \
  --doi "10.xxxx/..." --problem-n {N}

# 全部搜索完（或阶段性）核验一遍真实性
python scripts/cite_check.py verify
# 退出码 0 = 无造假，1 = 发现疑似编造的条目，必须删除/替换

# 写 latex_draft 时导出已验证的条目
python scripts/cite_check.py export-bibitems --problem-n {N} --verified-only
```

**开始搜索前，先查一下共享池里有没有已经登记过的相关文献**
（`cite_check.py list`），避免跟其他子问题的搜索重复劳动。

搜索范围仍参考 `LOS_ALAMOS_METHOD_CATALOG.md`（六大类 MCM 范式清单）拓宽
候选方向，不限于 Los Alamos 探索层才用得上——任何子问题的文献调研都可以
拿它当检查清单，防止只搜到"最常见"的那一种方法。

### 15.3 quality_gate.py lit 门控的判定优先级

`gate_literature()` 优先信任 `citations.bib` 里 `verified=verified` 且标记
了对应 `problem{N}` 的条目数；不够数时回退到 `thought_process.md` 里的旧式
格式匹配（DOI/URL/角标形状），能过但会提示"未做真实性核验，建议迁移"。
两条路径不是互斥的强制切换——旧式写法依然认，只是新式写法多一层真实性保障，
鼓励迁移但不强制阻断尚未迁移的工作流。

---

## 16. 写作风格打磨——规划、分段、多轮自查，降低"AI 生成感"

> 跟 Kaizen（§13）同一套哲学：主观判断"读起来自不自然"没法验证，必须配一套
> 客观、可检查的判据（`scripts/style_check.py`），不是靠 AI 自己觉得写得好不好。
> **这是 `latex_draft` 阶段固有的写作规范，不是可选 addon**——不存在"要不要
> 触发"的判断，每次写作都按这个流程走。

### 16.1 规划先行，分段撰写

不要一次性把整篇论文吐出来。每写一个章节前，先在 `thought_process.md` 里写
几句这一节打算怎么论证、段落之间怎么衔接（论证逻辑的简短提纲，不是要点罗列），
再动笔写这一节的正文；写完一节再进入下一节，不追求整篇论文风格机械统一——
人类写作各章节的节奏本来就会有自然差异，刻意追求"每节结构一模一样"反而是
AI 味的来源之一。

### 16.2 风格自查（`style_check.py`），最多 2 轮

每写完 2~3 个章节（或全篇初稿完成后），跑一次：

```bash
python scripts/style_check.py scan --file CUMCM_Workspace/latex/main.tex
# 退出码 0 = 未发现需要处理的问题，1 = 发现风格问题，见下方六类
```

检查六类客观可数的 AI 写作特征（前四类的判据来自开源 AI 文本人性化项目
[mrshibly/Humanizer](https://github.com/mrshibly/Humanizer)、
[brandonwise/humanizer](https://github.com/brandonwise/humanizer)（后者基于
Wikipedia:Signs of AI Writing）和 Pangram 的检测方法论调研，句长变异系数
的人类/AI 分界（人类约 0.5~1.0，AI 约 0.1~0.3）也来自同一批调研，落地时
按中文学术写作的实际语料做了保守调整，不是照搬英文阈值）：

1. **分点罗列感**：叙述性章节（背景/问题分析/模型评价/结论……）里 itemize/
   enumerate 密度过高——假设/符号说明/算法步骤/优缺点这类本来就该用列表的
   章节不算；
2. **套话/口水连接词**：如"值得注意的是""综上所述""不难发现"，全文反复用
   同一句超过阈值次数；
3. **机械化过渡骨架**："首先...其次...最后..."这套三段式在多个章节里逐字
   重复，是最典型的模板化标志；
4. **句长均匀度**：同一段落内句子长度的变异系数过小（阈值 0.20）——人类写作
   句长天然参差，过于整齐是已知的 AI 生成文本统计特征；
5. **段落长度均匀度**：同一章节内各段字数的变异系数过小（阈值 0.25）——AI
   常见"每段都差不多长"，人类写作段落有的一句话点题、有的层层展开；
6. **跨章节短语重复（n-gram）**：不依赖预设清单，直接用定长字符 n-gram 抓
   这次写作实际反复使用、且跨多个章节出现的任何短语——**这条精度较低**，
   论文自己定义的核心术语/指标名（比如某个自造的复合指标名称）天然会在
   全文反复出现，跟"习惯性套话"是两回事，脚本本身分不清，报告会显式提醒
   "先判断是不是专有名词"，不是每条命中都要动手改。

针对每一条发现，做真实的改写（合并/拆分句子、去掉重复套话、把部分列表改写成
连贯段落、打乱过渡骨架的用词），不是敷衍地换几个同义词。改完重新跑一次 scan，
**最多 2 轮**（跟 Kaizen 同样的轮数上限逻辑，到顶即放行，不追求零发现）。

### 16.3 与 Kaizen（§13）的边界：文风打磨不动数值结论

**这条是硬边界，不可违反**：写作风格打磨只能改变"怎么表达"，不能改变"表达
的是什么"——数值结果、模型结论、假设内容一个字都不能因为"这样写更自然"而
改动。发现结论本身需要改进（不是文字问题，是内容问题）属于 Kaizen 的职权，
不要在风格打磨这一步顺手把两件事混在一起做。

### 16.4 不必强求的边界

- 假设列表、符号说明表、算法步骤这类章节保留列表形式是正常且推荐的写法，
  `style_check.py` 已经排除这些章节，不会误报；
- 不追求"零发现"——2 轮打磨后仍有少量残留发现，只要不是大面积、系统性的
  问题，直接进入 Checkpoint ⑤ 即可，过度打磨文字风格本身不产生学术价值；
- 中英文摘要、致谢这类高度格式化的短文本，本来就有约定俗成的表达套路，
  不必强行套用这套检查。

---

## 17. 官方格式规范合规 — 论文格式、匿名性、AI 使用声明

> 依据《全国大学生数学建模竞赛论文格式规范（2026年修订稿）》与《全国大学生
> 数学建模竞赛人工智能工具使用规定（2025年试行）》（官方文件，
> [mcm.edu.cn](https://www.mcm.edu.cn/) / [cmathc.org.cn](https://www.cmathc.org.cn/)）。
> **AutoMCM-Pro 本身对使用者怎么用这份工具不做限定**——本节只负责把官方要求的
> 格式与文档，如实、按规范产出，供使用者自行决定如何使用。

### 17.1 论文格式（`templates/latex_template.tex` 已同步）

- 电子版第一页必须是摘要专用页（标题+摘要同页），从这页开始编页码；
  承诺书、编号专用页只在需要打印纸质版留存时使用，模板里默认注释掉；
- **不要目录**——`\tableofcontents` 不得出现在正文里（模板已移除）；
- 正文（不含附录）不超过 30 页，附录页数不限但须含全部完整可运行源代码；
- 论文任何地方不能出现参赛者身份、学校、赛区信息（匿名评审要求）。

### 17.2 匿名性检查（门控 8a）

```bash
python scripts/quality_gate.py anon-check
# 已接入 launch-check，final_compile 前会自动检查
```

启发式扫描"我校""本校""指导老师""参赛队号"这类自指性/标签性强信号——**这是
关键词匹配，不是语义理解**，抓不到需要维护全量校名清单才能覆盖的情形（比如
"XX大学"），过了检查不代表一定合规，仍需人工复查一遍。

### 17.3 AI 工具使用声明（`scripts/ai_usage_doc.py`）

官方规定：核心建模与分析必须由参赛队独立完成；使用 AI 工具需在正文标注、
参考文献列出工具、并在支撑材料附一份《AI工具使用详情》PDF（含工具名称版本、
使用目的与环节、关键交互记录、采纳与人工修改情况）；未使用 AI 需在参考文献后
声明"本参赛队未使用任何AI工具"。**这条规则不是"标注够不够规范"的问题，是
"核心建模分析能不能由 AI 代劳"的问题**——AutoMCM-Pro 只负责把用到 AI 的部分
如实生成合规文档，不代表这样生成的论文可以直接当作参赛作品提交。

```bash
# 生成《AI工具使用详情》PDF——取材于 worklog.md（§14）已有的完整交互记录，
# 不需要重新回忆整个过程
python scripts/ai_usage_doc.py generate \
  --tool-name "..." --tool-version "..." --org "..." --date "YYYY-MM-DD"
# 输出 CUMCM_Workspace/output/AI工具使用详情.{md,pdf}

# 参考文献里 AI 工具的引用行——只打印格式化文本，不自动插入任何文件
python scripts/ai_usage_doc.py cite-format \
  --tool-name "..." --tool-version "..." --org "..." --date "YYYY-MM-DD" --index N
```

**AI 工具引用默认不自动插入论文的参考文献列表**——跟 `cite_check.py
export-bibitems`（latex_draft 阶段的常规自动步骤）不同，是否要声明、声明成
什么样，是使用者需要自己决定并手动操作的一步，不属于流水线的自动化范围。

### 17.4 页数目标与附录代码：默认写节选，不是超标了才补救

**附录代码默认就该写节选（关键函数片段），不是"整份塞进去、超标了再回来
删"**——`\lstinputlisting{path/to/file.py}` 不加行号范围会把整个源文件搬进
附录，一个中等复杂度的建模项目（4~5 个 model 文件，每个 200~400 行）单靠
这一项就能把总页数顶到 60~70 页，这不是"意外超标"，是默认行为选错了。

**正确默认做法**：每个 model 文件在附录里只放**能体现核心求解逻辑的 1 个
函数**（通常是最优化/核心算法那个函数，不是 `main()`、不是绘图、不是样板
`import`），用 `\lstinputlisting` 的行号范围直接从真实源文件里截取，不要
另外复制出一份"节选文件"（截取范围和源文件自然保持同步，源文件改了节选
也跟着变，不会出现"附录代码"和"实际跑的代码"对不上的情况）：

```latex
\subsection{问题二求解核心（\texttt{problem1\_geometry.py}）}
坐标轮换爬山精化（完整文件另 407 行，含问题一解析计算、粗网格定位与绘图）：
\lstinputlisting[style=pythonstyle, firstline=161, lastline=186,
  caption={坐标轮换精化核心}]{../src/models/problem1_geometry.py}
```

真正很短的文件（比如 100 行左右的 `sensitivity.py`）可以整份收录，不必
硬切。验证脚本（`src/verifications/`）默认不收录到附录，放关键验证结果
表格即可——完整验证代码本身已经在 `state/.tmp`/`memory` 里有据可查，附录
篇幅应该优先给建模核心逻辑，不是给验证样板代码。

`compile_pdf.py` 编译成功后会自动统计页数并给出提醒（不是门控，不会让
编译失败——页数控制是写作阶段的事）：

- **CUMCM**：正文（附录前，按 PDF 书签定位"附录/核心代码"起始页估算）目标
  20~25 页，硬上限 30 页（官方规定，超出会被取消评奖资格）；附录页数不限，
  但节选原则同样适用——附录再怎么不限页数，也不该是不经筛选的源码搬运。
- **MCM/ICM**：Summary Sheet + 正文 + 参考文献 + 目录 + 附录代码**合计**硬
  上限 25 页（COMAP 官方规定），`Report on Use of AI Tools`单独一节不计入。

即使按上述原则默认写节选，`compile_pdf.py` 提醒仍然超标时，才依次考虑：
① 精简到每文件的节选再收窄（比如从一个函数缩到该函数里最关键的十几行）；
② 精简正文次要内容（灵敏度分析的次要参数组合、重复性论证）。**不得为了
压页数删掉 §4 强制代码自证协议要求的验证逻辑本身**（验证脚本继续留在
`src/verifications/`，只是不整份塞进附录）。

### 17.5 MCM/ICM 与 CUMCM 的格式差异（两份模板已分别处理）

| | CUMCM（`latex_template.tex`） | MCM/ICM（`mcm_template.tex`） |
|---|---|---|
| 目录 | **不要**（官方明文规定） | **要**，`tocdepth=2` 控制在约一页内 |
| 页数上限 | 正文 30 页，附录不限 | 全篇合计 25 页（含目录、附录代码） |
| AI 使用声明位置 | 独立支撑材料 PDF（`ai_usage_doc.py generate`） | 正文末尾追加一节，不计页数（`ai_usage_doc.py mcm-entry` 打印条目，模板里默认注释掉，需手动启用） |
| AI 引用格式 | `[编号] 工具名，版本，机构，日期` | `\textit{工具名} (版本, 日期)` + 用途说明或 Query/Output |
| 参考文献里还要不要提 AI 工具 | 要（如使用） | 要（inline citation + 参考文献列表 + 独立报告节，三处都要） |

MCM 模板的改动只做了结构性调整（`tocdepth`、页数提醒、注释掉的 AI 报告
占位节），**这个环境没有安装 `mcmthesis` LaTeX 宏包，无法在本地实际编译
验证**——只做了平衡括号/环境的结构性检查，不是完整编译验证，第一次实际
使用时建议留意有没有编译问题。

---

## 18. 画图前先查领域惯例——"画什么图"不是想当然

> `plot_style.py`（见 SKILL.md【图表风格规范】）管的是"配色/字体/DPI 这些让图表
> 不难看的规范"；本节管的是更前置的一步——"这类问题该画成什么类型的图"，两者
> 是不同层次的问题，只做好前者、跳过后者，图表依然可能显得业余或信息传达不到位。

### 18.1 规则

动笔生成任何结果图之前，先用运行时的网络检索工具，搜一下这类子问题在学术
文献/相关领域里通常怎么可视化呈现结果——不要不假思索地套用"折线图/柱状图"
这类通用默认。常见问题类型与惯例对照（供参考，不是穷举）：

| 问题类型 | 常见可视化形式 |
|---|---|
| 轨迹/几何优化（路径规划、拦截、投放策略） | 3D 轨迹图 + 关键时刻标注，或俯视投影叠加时间轴 |
| 覆盖/选址/分配 | 地图/散点覆盖示意图 + 甘特图式调度时间表 |
| 多目标/多方案比较 | Pareto 前沿图或雷达图，不是柱状图并排列数字 |
| 灵敏度分析 | tornado 图（参数按影响幅度排序的水平条形图），或多参数曲线族叠画 |
| 分类/聚类/评价排序 | 热力图或按排序维度重排类别顺序的堆叠条形图 |

搜索关键词按 §S3（安全规程，检索前抽象化关键词）处理，不要直接粘贴题目原文。
找到 2~3 个例子确认该领域常见呈现形式后，把判断依据记一笔到
`memory/thought_process.md`（哪种子问题对应哪种图、参考的是什么）——这一步的
产出是"决定画什么"，跟后续套用 `plot_style.py` 的配色规范（决定"怎么画好看"）
是两个独立步骤，不能互相替代。

### 18.2 查不到惯例时怎么办

题目类型比较小众、或检索没有明确结果时，退回常识判断即可，**不强求"一定要
找到文献佐证"**——但要在 `thought_process.md` 里如实写"未查到明确领域惯例，
按常识选用 XX 图"，不得跳过这条记录、也不得因为查不到就随便应付一张图。
这跟第 7 节"禁止静默跳过验证失败"是同一条精神在可视化环节的体现：可以承认
"没查到标准做法"，不能对这件事保持沉默。

---

## 19. LeanGate（可选 Lean 形式化验证）

LeanGate 默认关闭。初始化流水线时用 `--lean-policy selected|required` 启用：

```bash
python scripts/pipeline_manager.py init --mode AP --contest CUMCM --lean-policy selected
python scripts/leangate.py doctor
```

启用后，`problem_analysis` 结束前必须完成逐问题形式化适用性分类并执行
`leangate.py seal-assessment`。每个问题至少有一个 `ELIGIBLE` claim，或一个带明确
理由的 `NOT_APPLICABLE` 记录；`DEFERRED` 不能作为最终分类。注册 claim 时，若属于
`integer_feasibility`、`resource_conservation`、`safety_bound`、`graph_property`、
`dynamic_programming`、`algorithm_invariant`、`uniqueness_monotonicity_convergence`、
`solver_certificate`、`decision_critical` 或 `cross_problem_dependency`，必须用
`--risk-category` 标注并提供 `--classification-reason`。这些 claim 自动成为 mandatory。
分类封存后不得静默新增、删除、降级或改成不适用；需要改变时必须回到问题分析返工。

```bash
python scripts/leangate.py --workspace CUMCM_Workspace register ... \
  --risk-category safety_bound --classification-reason "决定最终方案可行性"
python scripts/leangate.py --workspace CUMCM_Workspace seal-assessment
python scripts/quality_gate.py formal-assessment
```

`selected` 表示只门控已登记的适用 claim；没有适用 claim 时返回 NOT_APPLICABLE。
`required` 表示每个进入 `model_N_verify` 的问题都必须有适用 claim 且通过。Agent 不得
为了放行把适用 claim 改成 `NOT_APPLICABLE`，也不得把 Lean 不可用解释为 PASS。

标准顺序是：生成/编写精确规格与证明 → `register` → `semantic-review` → `freeze` →
`verify` → `quality_gate.py formal`。证书型资源分配案例可先执行
`generate-resource`，它只接受精确 JSON 整数，并把证书摘要嵌入 Lean 源文件。
人类语义批准文件必须包含 `[APPROVED LeanGate <claim-id>]`；将义务纳入 `required` 基线还需
包含 `[REQUIRED LeanGate <claim-id>]` 并执行 `leangate.py require`。这两个标记不能由
任务 Agent 自行代写。

任何规格、证明或证书变化都会使旧结果 `STALE`。Python 验证与 Lean 验证是合取关系；
任何一方失败都不得写成“形式化证明通过”。`FORMALLY_PROVED` 只来自固定快照上的 Lean
内核检查及公理/占位符审计，不来自 Agent 自评、OpenCode/DSH 复核意见或 PASS 文本。

论文只可在 claim scope 与假设范围内引用结论；`launch-check` 会重新消费当前 manifest、
摘要和机器报告。形式化不能替代数据质量、统计检验、现实合理性和价值判断。详细信任
边界、状态模型及哲学定位见 `LEAN_GATE_DESIGN.md`。

LeanGate 启用后，推进 `model_N_verify` 必须让流水线实际执行独立 Python 验证脚本：

```bash
python scripts/pipeline_manager.py advance model_1_verify \
  --verify-script CUMCM_Workspace/src/verifications/verify_problem1.py
```

随后流水线会再次运行正式 Lean gate；不能传入工作区外脚本、符号链接或预先伪造的报告。
