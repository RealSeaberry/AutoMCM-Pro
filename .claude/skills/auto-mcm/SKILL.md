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

### Step 1 — 检查工作区是否已初始化

```bash
python scripts/pipeline_manager.py status 2>/dev/null
```

- **退出码 0（已初始化）** → 读取当前阶段和状态，跳到 Step 3
- **退出码非 0（未初始化）** → 执行 **Step 2【首次启动协议】**

---

### Step 2 — 首次启动协议（全程自然语言，用户零命令）

**2a. 用自然语言询问最少必要信息（AskUserQuestion）：**

> "请告诉我：① 题目文件的路径（PDF 或文本），② 附件数据文件所在位置（如有），③ 希望用哪种模式？AP 模式（AI 全自动推进，仅在关键节点可干预）或 MANUAL 模式（每步等待你的审批）？默认 AP。"

**2b. 读取题目，自动推断配置：**

```bash
# 提取题目文本
python -c "import pdfplumber; pdf=pdfplumber.open('PROBLEM_PATH'); [print(p.extract_text()) for p in pdf.pages]" 2>/dev/null \
  || python -c "import pypdf; r=pypdf.PdfReader('PROBLEM_PATH'); [print(p.extract_text()) for p in r.pages]"
```

根据题目内容自动推断：
- 竞赛类型（CUMCM / MCM / ICM）
- 子问题数量（N）
- 是否有数据附件

告知用户推断结果，例如：
> "我分析了题目，检测到 **3 个子问题**。将开启多 Agent 并行模式，同时启用竞赛版本控制。是否有补充？"

（默认直接执行，用户沉默 = 确认）

**2c. 自动运行所有初始化命令（静默执行，不让用户看到命令行）：**

```bash
python scripts/setup_workspace.py

python scripts/pipeline_manager.py init \
  --mode {AP|MANUAL} \
  --contest {CUMCM|MCM|ICM} \
  --problems {N} \
  --git

# 将题目和数据复制到工作区
cp PROBLEM_PATH CUMCM_Workspace/data/
cp DATA_FILES   CUMCM_Workspace/data/   # 如有
```

**2d. 以自然语言告知用户就绪状态：**

> "✓ 工作区已就绪！配置：**AP 模式** | **3 个并行 Agent** | **版本控制已开启**。
> 现在开始建模，我会在完成每个阶段后向你汇报进展。"

---

### Step 3 — 根据流水线状态决定行动

| 状态 | Agent 行为 |
|------|-----------|
| `not_started` | 执行 `start-stage`，静默开始工作 |
| `in_progress` | 直接继续该阶段未完成的工作 |
| `pending_review`（MANUAL 模式） | 用自然语言向用户汇报并等待反馈 |
| `rework` | 读取 `human_intervention.md`，针对性重做，无需用户重新输入命令 |
| `approved` | 执行 `advance`，静默推进，告知用户进展 |

**所有 `pipeline_manager.py` 命令均由 Agent 在后台执行，用户只看到自然语言进度汇报。**

### Step 4 — 依赖自检（首次启动 & 每次唤醒）

在开始任何 Python 脚本之前，静默检查并安装必要依赖：

```bash
python -c "import pdfplumber, scipy, numpy, matplotlib, pandas, openpyxl" 2>/dev/null \
  || pip install -q pdfplumber scipy numpy matplotlib pandas openpyxl
```

如需 LaTeX 编译：
```bash
which xelatex >/dev/null 2>&1 || echo "[提示] 未检测到 xelatex，建议安装 TeX Live 或使用 Docker"
```

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

### AP 模式 — 自评自批，自动推进，自然语言汇报

1. 在 `state/human_intervention.md` 中写入自评：
```
[APPROVED]
AI 自评（<stage>）：
- 本阶段完成情况：<一句话总结>
- 关键数值检查：<列举 2-3 个代表性结果>
- 验证状态：<PASS/本阶段无强制验证>
- 进入下一阶段的理由：<简要说明>
```

2. 执行 advance（静默）：
```bash
python scripts/pipeline_manager.py advance <stage>
```

3. **用自然语言向用户汇报本阶段成果，然后直接开始下一阶段，无需等待任何输入。** 汇报格式示例：
> "✓ **数据预处理**完成。发现 243 条记录，清洗后保留 231 条，缺失值用中位数填补。生成了数据分布图 3 张。→ 开始问题一、二、三并行建模。"

### MANUAL 模式 — 自然语言等待人类反馈

完成阶段后，以自然语言向用户展示汇报摘要，然后明确说：
> "请告诉我是否继续，或者提出修改意见。"

等待用户回复（**用户输入自然语言即可**，无需填写任何文件或输入命令）。  
收到确认后自动写入 `[APPROVED]` 并执行 advance；收到修改意见则直接进入 rework。

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

Manual 模式下，在开始 `model_{n}_build` 之前，读取 `human_intervention.md`，然后**用自然语言**向用户逐条复述建模规格：

> "我将按以下规格实现问题一：目标函数 max T_shield(θ,v)，决策变量 θ∈[0°,360°]、v∈[70,140] m/s，求解器 SLSQP。有遗漏或歧义请告知，否则我将立即开始。"

用户回复自然语言确认即可，无需填写任何文件。Agent 内部将确认写入 `human_intervention.md` 并开始编码。

**在 Manual 模式下，严禁以下行为：**
- 将 `human_intervention.md` 未提及的变量加入目标函数
- 因"数值稳定性"等理由更换人类指定的求解器（需先提问）
- 在论文中添加人类规格外的模型或方法

---

## 【Rework 执行规程】

用户用自然语言提出修改意见后（无需任何命令），Agent 立即：

1. 将反馈摘要写入 `human_intervention.md`，静默执行：
```bash
python scripts/pipeline_manager.py rework <stage> --feedback "反馈摘要"
```
2. 向用户复述理解到的修改要求，确认无歧义
3. **只修改被明确批评的部分**，其余已 `approved` 的内容不得改动
4. 在 `memory/thought_process.md` 中记录修改方案和关键数值变化
5. 重新运行受影响的验证脚本
6. 完成后用自然语言汇报结果，自动进入下一轮 review

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

## 【建模质量门控】

质量门控由 `scripts/quality_gate.py` 强制执行，**不是 AI 行为规则，而是硬检查脚本**。  
在对应时机调用，退出码 1 时禁止 advance。

### 调用时机

```bash
# model_N_build 开始前 — 门控 1：文献引用
python scripts/quality_gate.py lit --stage model_{N}_build --problem-n {N}
# 退出码 1 → 补充文献再编码

# model_N_build 运行后 — 门控 2：数值合理性
python src/models/problem{N}_{type}.py > /tmp/model_output.txt 2>&1
python scripts/quality_gate.py sanity --stage model_{N}_build --output-file /tmp/model_output.txt
# 退出码 1 → 回到模型修复

# model_N_verify 运行后 — 门控 3：结构化报告解析
python src/verifications/verify_problem{N}_{type}.py > /tmp/verify_report.txt 2>&1
python scripts/quality_gate.py verify --stage model_{N}_verify --report-file /tmp/verify_report.txt
# 退出码 1 → 禁止 advance

# 所有 verify 完成后（并行模式）— 门控 4：多问题一致性
python scripts/quality_gate.py consist --problems {N}
# 退出码 1 → 修复后重跑受影响的 verify

# 或一次运行所有适用门控
python scripts/quality_gate.py all \
  --stage model_{N}_verify \
  --report-file /tmp/verify_report.txt \
  --problem-n {N} \
  --problems {total_N}
```

### 验证报告格式（门控 3 强制）

`verify_problem{N}_{type}.py` 末尾必须打印结构化报告，否则 `quality_gate.py verify` 返回失败：

```
========== VERIFICATION REPORT ==========
Stage  : model_{N}_verify
Result : PASS
Checks :
  ✓ 约束满足性: 所有决策变量在可行域内
  ✓ 物理可行性: 结果符合物理量纲
  ✓ 数值稳定性: 无 inf/nan，收敛
  ✓ 边界条件:   边界情形均已验证
==========================================
```

### 门控 5 — LaTeX 编译重试（`final_compile` 专用）

```bash
# 尝试 1
xelatex -interaction=nonstopmode main.tex 2>&1 | tee /tmp/latex_out.txt
grep -q "! LaTeX Error\|Undefined control sequence" /tmp/latex_out.txt && {
  # 解析错误行号 → 修复 main.tex → 尝试 2
  xelatex -interaction=nonstopmode main.tex 2>&1 | tee /tmp/latex_out.txt
  grep -q "! LaTeX Error\|Undefined control sequence" /tmp/latex_out.txt && {
    # 尝试 3
    xelatex -interaction=nonstopmode main.tex || {
      echo "[quality_gate] LaTeX 编译 3 次仍失败，请求人工介入"
      python scripts/pipeline_manager.py checkpoint-banner --stage final_compile
    }
  }
}
```

---

## 【安全规程】

### S1 — API 密钥保护

- **禁止**将 `OPENAI_API_KEY` 或任何凭证写入代码文件、日志、`thought_process.md` 或任何被 git 追踪的文件
- 在代码中使用环境变量读取：`os.environ.get("OPENAI_API_KEY")`
- 若用户在对话中粘贴了密钥，立即提示其撤销并重新生成

### S2 — 文件路径验证

在使用用户提供的文件路径前，始终验证：

```python
from pathlib import Path
path = Path(user_provided_path).resolve()
# 确保路径在工作目录内（防止路径遍历）
assert str(path).startswith(str(Path.cwd())), "路径越界"
assert path.exists(), f"文件不存在: {path}"
```

### S3 — 外部服务调用告知

调用 `WebSearch` / `WebFetch` 时，不将用户的题目原文直接发送为搜索词——使用抽象化的关键词（例如用"非线性规划运输优化"而非直接粘贴题目原文）。

### S4 — 返工上限

若某阶段的返工次数接近上限（`max_reworks`，默认 5），在第 3 次返工时主动告知用户：

> "⚠ 该阶段已返工 3 次，还有 2 次机会自动修复。若仍未解决，将暂停并请求人工介入。"

### S5 — 密钥提交拦截

竞赛 Git 的 `auto_commit` 会在提交前扫描暂存区，若检测到疑似密钥（如 `sk-` 开头的字符串）会自动阻止提交并打印警告。Agent 发现此警告时，应立即通知用户检查并从文件中移除。

---

## 【绝对禁止（摘要）】

所有规则详见 `AutoMCM_SOP.md § 7`。核心禁令：
- 不得跳过 Checkpoint
- 不得将 `verify_*` 未通过的模型结果写入论文
- Manual 模式下不得自行发散
- 不得覆写已 `approved` 的内容
