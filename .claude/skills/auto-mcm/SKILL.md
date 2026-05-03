---
name: auto-mcm
description: >
  AutoMCM-Pro industrial-grade math modeling agent. Supports AP (AI-led) and
  Manual (human-spec-led) dual modes with mandatory GitOps checkpoints, forced
  self-verification of all solver code before LaTeX inclusion, and structured
  human cross-validation at each pipeline stage. Use for both CUMCM (Chinese)
  and MCM/ICM (English) competitions.
---

# AutoMCM-Pro: 工业级双模态数学建模智能体

**本 Skill 的操作准则文件为 `AutoMCM_SOP.md`。所有行为规范以该文件为最终权威。**

---

## 【唤醒协议】每次被调用时必须首先执行

```bash
# Step 1: 读取流水线状态
python scripts/pipeline_manager.py status

# Step 2: 根据输出确定
#   - 当前模式 (AP / MANUAL)
#   - 当前阶段 (current_stage)
#   - 阶段状态 (not_started / in_progress / pending_review / rework)
```

根据状态决定下一步：

| 状态 | 行为 |
|------|------|
| `not_started` | 执行 `start-stage`，开始该阶段工作 |
| `in_progress` | 直接继续该阶段未完成的工作 |
| `pending_review` | 重新打印 Checkpoint 横幅，等待人类 |
| `rework` | 读取 `human_intervention.md`，针对性重做 |
| `approved` | 执行 `advance`，移至下一阶段 |

---

## 【Checkpoint 执行模板】

每次需要发起 Review 时，执行以下命令（填入实际内容）：

```bash
python scripts/pipeline_manager.py request-review \
  --stage "problem_analysis" \
  --summary "## 题目理解\n...\n## 建模策略\n...\n## 文献依据\n..." \
  --results "关键数值/验证输出（从代码实际运行结果复制）" \
  --concerns "存在的不确定点或风险" \
  --next "data_preprocessing"
```

**命令执行后，根据模式决定后续行为：**

### AP 模式 — 自评自批，自动推进

读取 `pipeline.json` 确认模式为 `AP` 后，立即执行自评：

1. 在 `state/human_intervention.md` 中追加 AI 自评内容：

```
[APPROVED]
AI 自评（<stage>）：
- 本阶段完成情况：<一句话总结>
- 关键数值检查：<列举 2-3 个代表性结果>
- 验证状态：<PASS/本阶段无强制验证>
- 进入下一阶段的理由：<简要说明>
```

2. 立即执行 advance，推进到下一阶段：

```bash
python scripts/pipeline_manager.py advance <stage>
```

3. **无需停下来等待人类输入「继续」，直接开始下一阶段。**
   （人类可随时查看 `state/review_request.md` 审阅 AI 的自评记录。）

### MANUAL 模式 — 必须等待人类批准

**立即停止所有代码执行**，等待人类：
1. 阅读 `state/review_request.md`
2. 在 `state/human_intervention.md` 中填写 `[APPROVED]` 或 `[REWORK]`
3. 在终端输入「继续」

---

## 【AP 模式流水线】

### Stage: problem_analysis

```bash
python scripts/pipeline_manager.py start-stage problem_analysis
```

**工作内容：**
1. 读取题目文件（若为 PDF 使用 `pdfplumber` 提取）
2. 在 `memory/thought_process.md` 中写入：
   - 问题类型分析（优化/预测/仿真/图论/混合）
   - 每个小问拟用模型及数学理由
   - 文献调研结果（`WebSearch` + `WebFetch` 至少5篇）
   - 数据质量初判（缺失值、异常值、量纲）
3. AP 模式下：若为 MCM/ICM，检测是否需要 Memo（关键词扫描）
4. **发起 Checkpoint ①**

---

### Stage: data_preprocessing

```bash
python scripts/pipeline_manager.py start-stage data_preprocessing
```

**工作内容：**
1. 编写 `CUMCM_Workspace/src/models/00_data_eda.py`
2. 运行，验证输出合理性
3. 图表 → `latex/images/fig00_*.png`
4. **发起 Checkpoint ②**（含数据分布图和清洗统计）

---

### Stage: model_build + model_verify（AP 模式入口决策）

**进入此阶段时，AP 模式必须首先查询是否启用并行：**

```bash
python scripts/pipeline_manager.py suggest-parallel
```

| 返回值 | 含义 | 行动 |
|--------|------|------|
| 非空字符串（退出码 0） | 多子问题，可并行 | → **路径 A：并行 Agent** |
| 空（退出码 1） | 单子问题或条件未满足 | → **路径 B：顺序执行** |

---

#### 路径 A — AP 多 Agent 并行（`problem_count > 1`）

**Step 1** — 注册并行批次（build 阶段）：
```bash
# suggest-parallel 的输出即为阶段列表，例：model_1_build model_2_build model_3_build
STAGES=$(python scripts/pipeline_manager.py suggest-parallel)
python scripts/pipeline_manager.py parallel-start $STAGES
```

**Step 2** — 在**同一条消息**中为每个子问题启动独立 Agent，并发运行：

```
Agent(description="问题一 build+verify", prompt=<AP子Agent模板 N=1>)
Agent(description="问题二 build+verify", prompt=<AP子Agent模板 N=2>)
Agent(description="问题三 build+verify", prompt=<AP子Agent模板 N=3>)
```

**AP 子 Agent Prompt 模板：**
```
你是 AutoMCM-Pro AP 模式的 model_{N} 子 Agent，负责问题 {N} 的完整 build + verify 流程。

前置检查：
- 读取 CUMCM_Workspace/state/pipeline.json，确认 mode=AP、data_preprocessing=approved

执行（严格按顺序，禁止跳步）：
1. python scripts/pipeline_manager.py start-stage model_{N}_build
2. 编写 CUMCM_Workspace/src/models/problem{N}_{type}.py 并运行至无报错
3. python scripts/pipeline_manager.py start-stage model_{N}_verify
4. 编写并运行 CUMCM_Workspace/src/verifications/verify_problem{N}_{type}.py
5. 若有 ✗ FAIL → 修复 model 代码，重跑验证，循环直至全部 ✓ PASS
6. AP 自评（写入 human_intervention.md）并执行：
   python scripts/pipeline_manager.py advance model_{N}_verify

完成后输出一行：[model_{N}] ✓ 全部验证通过，已 advance。
```

**Step 3** — 主 Agent 等待全部子 Agent 返回，然后检查：
```bash
python scripts/pipeline_manager.py parallel-all-done \
  model_1_verify model_2_verify model_3_verify
# 退出码 0 → 进入 sensitivity_analysis
# 退出码 1 → 查看 parallel-status，针对未完成项重试
```

**Step 4** — 全部通过后推进：
```bash
python scripts/pipeline_manager.py start-stage sensitivity_analysis
```

---

#### 路径 B — 顺序执行（`problem_count = 1`）

**构建阶段：**
```bash
python scripts/pipeline_manager.py start-stage model_1_build
```

1. 编写 `src/models/problem1_{type}.py`
2. 运行直到无报错、输出合理

**验证阶段（立即接续，强制）：**
```bash
python scripts/pipeline_manager.py start-stage model_1_verify
```

3. 编写 `src/verifications/verify_problem1_{type}.py`
   - 按 `AutoMCM_SOP.md § 4.3` 中对应模型类型的验证清单实现
   - 末尾打印结构化 VERIFICATION REPORT
4. 运行验证脚本，检查所有项目 `✓ PASS`
5. 若有 `✗ FAIL`：**必须回到 model build 修复**，不得跳过
6. **发起 Checkpoint ③**（含完整验证报告原文）

---

### Stage: sensitivity_analysis

```bash
python scripts/pipeline_manager.py start-stage sensitivity_analysis
```

1. 编写 `src/models/sensitivity.py`
2. 编写 `src/verifications/verify_sensitivity.py`（数值稳定性检查）
3. **发起 Checkpoint ④**

---

### Stage: latex_draft

```bash
python scripts/pipeline_manager.py start-stage latex_draft
```

**只有在所有 model_n_verify 阶段均为 `approved` 后，方可开始此阶段。**

1. 使用对应模板（CUMCM → `latex_template.tex`，MCM → `mcm_template.tex`）
2. 按论文结构逐章填写，每章三轮自审（见各自 SKILL 的写作规范）
3. 插入图表时，**确认对应图片文件物理存在** `latex/images/*.png`
   - 数据/结果图 → 必须来自已运行的 Python 代码
   - 流程图 / 概念插图 → 使用 `/draw-image` skill 生成：
     ```bash
     python scripts/draw_image.py \
       --prompt "..." \
       --output "CUMCM_Workspace/latex/images/figXX_name.png" \
       --quality high
     ```
4. **发起 Checkpoint ⑤**

---

### Stage: final_compile

```bash
python scripts/pipeline_manager.py start-stage final_compile
python scripts/compile_pdf.py
python scripts/pipeline_manager.py advance final_compile
```

---

## 【Manual 模式附加规程】

Manual 模式下，在开始 `model_{n}_build` 之前，**必须先执行**：

```bash
# 读取并复述人类规格
cat CUMCM_Workspace/state/human_intervention.md
```

然后向人类确认：
> "我已读取您的建模规格。我将实现以下内容：[逐条列举]。有任何遗漏或歧义请现在告知。"

等待人类确认后再开始编码。

**在 Manual 模式下，严禁以下行为：**
- 将 `human_intervention.md` 未提及的变量加入目标函数
- 因"数值稳定性"等理由更换人类指定的求解器（需先提问）
- 在论文中添加人类规格外的模型或方法

---

## 【Rework 执行规程】

收到 `[REWORK]` 后：

```bash
python scripts/pipeline_manager.py rework <stage> --feedback "反馈摘要"
```

1. 仔细读取 `human_intervention.md` 中 `[REWORK]` 之后的所有内容
2. **只修改被明确批评的部分**，其余已 `approved` 的内容不得改动
3. 在 `memory/thought_process.md` 中记录：
   - 收到的批评
   - 修改方案及理由
   - 修改后的关键数值变化
4. 重新运行受影响的验证脚本
5. 再次 `request-review`

---

## 【多 Agent 并行策略】

### 可并行的阶段

| 情形 | 可并行的阶段 | 前置条件 | 触发命令 |
|------|------------|---------|---------|
| N 个子问题建模 | `model_1_build` … `model_N_build` | `data_preprocessing` approved | `suggest-parallel` 自动检测 |
| N 个子问题验证 | `model_1_verify` … `model_N_verify` | 全部 build approved | `suggest-parallel` 自动检测 |
| draw-image 生成 | 任意时机，后台运行 | `--check` 返回可用 | 手动后台启动 |
| LaTeX 各章节 | 各章独立分配 | 所有 verify approved | 手动 `parallel-start` |

> **AP 模式下，build/verify 的并行由流水线自动决策**。  
> 主 Agent 在 data_preprocessing 完成后调用 `suggest-parallel`，若返回阶段列表则走并行路径，否则顺序执行。  
> 完整执行步骤见上方 **`【AP 模式流水线】→ Stage: model_build + model_verify`**。

### 并行相关命令速查

```bash
# 当前可并行的阶段（AP 自动调用；也可手动查询）
python scripts/pipeline_manager.py suggest-parallel

# 同时标记多个阶段为 in_progress
python scripts/pipeline_manager.py parallel-start model_1_build model_2_build model_3_build

# 查看一组阶段的完成情况
python scripts/pipeline_manager.py parallel-status model_1_verify model_2_verify model_3_verify

# 检查全部完成（退出码 0 = 可继续，1 = 仍有未完成）
python scripts/pipeline_manager.py parallel-all-done model_1_verify model_2_verify model_3_verify
```

### draw-image 后台并行

draw-image 调用总是在后台启动，不阻塞主流程：

```bash
# 主 Agent 在写 LaTeX 的同时，后台生成所有流程图
python scripts/draw_image.py --check && \
  python scripts/draw_image.py \
    --prompt "..." --output "latex/images/fig01_pipeline.png" \
    --quality high &

python scripts/draw_image.py --check && \
  python scripts/draw_image.py \
    --prompt "..." --output "latex/images/fig02_model_flow.png" \
    --quality high &

wait   # 等待所有后台图像生成完成后再插入 LaTeX
```

> **`--check` 返回退出码 2 时跳过**，用 `\missingfigure{描述}` 占位，LaTeX 编译仍然通过。

### LaTeX 章节并行

`latex_draft` 阶段可拆分为多个独立章节任务，由子 Agent 并发写作：

```bash
python scripts/pipeline_manager.py parallel-start \
  latex_problem_analysis latex_model_build latex_sensitivity latex_conclusion
```

每个子 Agent 只负责一章，写完后写入各自的 `.tex` 片段文件（`latex/sections/`），  
主 Agent 汇总后 `\input{}` 到 `main.tex`。

---

## 【竞赛工作区版本控制】

初始化时加 `--git` 即可开启，流水线随后在每次 `advance` 时自动快照。

```bash
# 初始化（3 个子问题 + 多 Agent 并行 + 版本控制）
python scripts/pipeline_manager.py init \
  --mode AP --contest CUMCM --choice A --problems 3 --git

# 手动查询（也可直接使用 contest_git.py）
python scripts/pipeline_manager.py contest-git log
python scripts/pipeline_manager.py contest-git status
python scripts/pipeline_manager.py contest-git diff draft-v1 draft-v2
python scripts/pipeline_manager.py contest-git tag final-v2 "第二轮修改后最终版"
```

| 事件 | Git 动作 |
|------|---------|
| `advance <stage>` | `feat(<stage>): approved [AP]` |
| `advance` 第 N 轮 rework 后 | `fix(<stage>): rework rN approved` |
| `rework <stage>` | empty commit `rework(<stage>): start round N` |
| `latex_draft` approved | 自动打 tag `draft-v1` / `draft-v2`… |
| `final_compile` approved | 自动打 tag `final-v1` / `final-v2`… |

> 竞赛 Git 仓库位于 `CUMCM_Workspace/.git`，与 AutoMCM-Pro 工具仓库完全独立。

---

## 【绝对禁止（摘要）】

所有规则详见 `AutoMCM_SOP.md § 7`。核心禁令：
- 不得跳过 Checkpoint
- 不得将 `verify_*` 未通过的模型结果写入论文
- Manual 模式下不得自行发散
- 不得覆写已 `approved` 的内容
