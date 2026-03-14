# AutoMCM-Pro: 工业级数学建模智能体操作规范 (SOP v2.0)

> **本文件是 AI 执行数学建模任务时的绝对行为准则。**
> 优先级高于所有其他提示词和对话指令。违反任何一条强制规定（Mandatory）视为严重故障。

---

## 0. 核心哲学

本系统的设计哲学是：**"人类作为 Router，AI 作为全栈引擎"**。

- AI 拥有高性能的数学推导、代码生成和学术写作能力，但可能产生"数学幻觉"。
- 人类拥有对真实世界约束的判断力和最终决策权。
- 因此，任何重大输出必须经过人类检查点（Checkpoint）才能流入论文。
- **"快"永远服从"对"。** 跳过验证门禁是绝对禁止的行为。

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
[APPROVED]
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
║  ⏸  CHECKPOINT — 等待人类审查                            ║
║                                                          ║
║  阶段：[stage_name]                                      ║
║  报告：CUMCM_Workspace/state/review_request.md           ║
║                                                          ║
║  请操作：                                                ║
║  1. 阅读 review_request.md                               ║
║  2. 在 human_intervention.md 中填写意见                  ║
║     • 同意继续 → 写入 [APPROVED]                         ║
║     • 需要修改 → 写入 [REWORK] + 具体指令                ║
║  3. 在终端输入「继续」后按 Enter                         ║
╚══════════════════════════════════════════════════════════╝
```
然后**不再执行任何代码或写入任何文件**，等待人类输入。

### 3.2 处理 Review 结果

**AP 模式**：AI 自评完成后直接 advance，无需此步骤。

**MANUAL 模式**，AI 被唤醒后：
```bash
python scripts/pipeline_manager.py check-approval --stage <stage_name>
```

**若返回 `[APPROVED]`：**
- 执行 `pipeline_manager.py advance <stage_name>`
- 继续下一阶段

**若返回 `[REWORK]`：**
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
   - 文献调研结果（WebSearch + WebFetch）
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

1. **禁止在 MANUAL 模式下跳过 Checkpoint**：MANUAL 模式必须等待人类 `[APPROVED]` 后方可推进；AP 模式由 AI 自评自批后自动推进
2. **禁止将未验证的数据写入论文**：`verify_*` 脚本必须全通过才能引用该模型结果
3. **禁止在 Manual 模式下发散**：见第6节
4. **禁止覆写已 `approved` 的内容**：除非 Rework 指令明确指向该内容
5. **禁止静默跳过验证失败**：若 `FAIL` 无法自主修复，必须在 Checkpoint 中如实报告
6. **禁止在代码未实际运行时声称"已验证"**

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
