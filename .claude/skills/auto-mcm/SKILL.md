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

### Step -1 — 本会话首次触发时取得依赖安装同意

每个新的智能体会话中，第一次触发本 Skill 时，必须先用自然语言分别询问：

> “是否安装 AutoMCM-Pro 的核心 Python 建模依赖（pdfplumber、scipy、numpy、
> matplotlib、pandas、openpyxl）？是否同时准备可选的 LeanGate / Lean 4？”

本步骤只询问，不预先扫描依赖，不把沉默视为同意，也不得在回答前联网安装。
用户同意后，按其选择调用 `bash install.sh --with-python-deps` 和/或
`--with-lean`；明确拒绝则继续当前任务，同一会话不再重复询问。若随后执行到依赖
确实缺失，只报告缺失项和安装方法，不自动安装。无法等待用户回答的 headless 模式
必须显示问题并暂停，不能自行选择。

### Step 0 — 工作日志：记一句用户这次说了什么

> `AutoMCM_SOP.md` §14。只在工作区已经 `setup_workspace.py` 过（`CUMCM_Workspace/`
> 存在）时才有地方可写，未初始化时的第一次对话跳过这步，等 Step 2 建好工作区后
> 把这轮用户消息补记一笔即可。

```bash
python scripts/worklog.py append --role user --text "<用户这次说的话，一句话概括，不要逐字长篇转录>"
```

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

若用户在对话中主动表示"简单跑一下""时间不多，快一点""不用太严谨"等诉求，
判定为触发 **Project Skunk Works**（轻量快速模式，见 `AutoMCM_SOP.md` §10），
告知用户"将以精简模式执行（文献要求放宽、汇报更简短，但验证标准不变）"，
2c 的 init 命令加 `--skunk-works`。仅限 AP 模式——若用户同时要求 MANUAL，
先向用户澄清取舍。

**除了用户明说，也可以自主判断触发**（SOP §10.1 第 2 种方式）：如果对话或题目
本身透露出时间预算明显不足（用户提到截止时间很近、"还有 X 小时"之类的话，但
没有直接说"简化"），可以自己判断要不要进 Skunk Works——但判断依据只能是"时间
紧迫"，不能是"这题看起来简单"；决定要用之前，必须先告知用户"判断时间紧迫，
将采用 Skunk Works 轻量模式简化流程"，不能静默切换。没有时间紧迫的信号时，
默认走全套严谨模式，不用主动问用户要不要开。

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

# 触发 Skunk Works 时（见 2a）追加 --skunk-works
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

### Step 4 — 按需报告依赖缺失

不要在唤醒时预扫描或静默安装依赖。只有实际命令因依赖缺失而失败时，才向用户报告
缺失项，并在获得明确同意后调用 `bash install.sh --with-python-deps`。

如需 LaTeX 编译：
```bash
which xelatex >/dev/null 2>&1 || echo "[提示] 未检测到 xelatex，建议安装 TeX Live 或使用 Docker"
```

图表中文显示自检（首次启动跑一次即可，后续复用检测结果）：
```bash
python scripts/plot_style.py check
# 退出码 0 → 中文字体可用，正常进行
# 退出码 1 → 会打印按操作系统区分的安装建议；无法立即安装时，图表标题/标签先改用
#           英文，避免中文乱码（方框）进入论文，不要在未确认可显示的情况下硬上中文
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

1. `request-review` 自动在 `state/human_intervention.md` 中写入绑定阶段与轮次的自评：
```
[APPROVED:<stage>:<round>]
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
收到确认后自动写入 review_request 指定的 `[APPROVED:<stage>:<round>]` 并执行 advance；
收到修改意见则写入对应 `[REWORK:<stage>:<round>]` 后进入 rework。

---

## 【Andon Cord — 紧急停止】任意阶段、任意角色发现重大问题时使用

不是排定好的 Checkpoint，是"发现问题但等不到下一个 Checkpoint 就该立刻上报"的
紧急通道（详细边界见 `AutoMCM_SOP.md` §11，不要拿它当 Rework 的替代品——具体
阶段内的问题走正常 Rework 流程，Andon 保留给"可能推翻已批准内容"或"超出当前阶段
职责范围"的发现）：

```bash
python scripts/pipeline_manager.py andon-pull --reason "一句话说清楚问题" --by "<你的角色>"
# 拉下后，任何 advance 调用都会被拒绝（退出码非0），直到 andon-clear
```

拉绳后**立即用自然语言向用户说明情况**，不要静默处理。用户/自评确认问题已解决后：

```bash
python scripts/pipeline_manager.py andon-clear --resolution "怎么解决的，一句话说清楚"
```

AP 模式下也不能自动 andon-clear——这是本协议里少数几个"AP 模式也必须真正等人类
确认"的环节之一（另一个是 Los Alamos 的 Checkpoint LA）。

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
   - **文献调研（`WebSearch` + `WebFetch` 至少5篇，见 `AutoMCM_SOP.md` §15）**：
     参考 `LOS_ALAMOS_METHOD_CATALOG.md` 拓宽候选范式（不限于 Los Alamos 才用），
     搜到一篇就登记一次，不要攒到最后再手工整理：
     ```bash
     python scripts/cite_check.py list                        # 先查共享池，避免重复搜索
     python scripts/cite_check.py register --title "..." --author "..." \
       --year 2020 --journal "..." --doi "10.xxxx/..." --problem-n {N}
     # 全部搜完后：
     python scripts/cite_check.py verify                      # 真实性核验，退出码1=有疑似编造条目
     ```
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
   - 脚本开头 `import plot_style; plot_style.apply()`（见【图表风格规范】），
     所有图用 `plot_style.save(fig, path)` 存盘，不要各自手写 `plt.savefig`
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

**在此之外，对每个具体子问题 N（无论它落在路径 A 的哪条并行 lane，还是路径 B 的
单线里），在开始该子问题的 build 之前，都要额外做一次"是否叠加 Los Alamos 探索"
判定（见下方 **路径 C**）——路径 C 不是与 A/B 并列的第三条整体路线，而是"这个
子问题该不该从单模型直接建模，换成多假设探索后再选优"的**单题级别加注**，可以
和路径 A 的并行同时发生（比如 3 个子问题里只有第 2 题触发路径 C，第 1、3 题仍走
普通单模型流程）。

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

#### 路径 C — Los Alamos 探索模式（单题级别加注，可与路径 A/B 叠加）

> 架构与理论依据见 [`LOS_ALAMOS_DESIGN.md`](../../../LOS_ALAMOS_DESIGN.md)、
> [`LOS_ALAMOS_INTEGRATION.md`](../../../LOS_ALAMOS_INTEGRATION.md)。CLI 工具在
> `scripts/los_alamos/`（用法见该目录 `README.md`）。**默认不触发**，未命中下方
> 触发条件时，子问题 N 按现有路径 A/B 的普通单模型流程执行，本节不介入。

**Step 0 — 触发判定（Director 内联判断，不需要新脚本）**

命中以下任一条，才对子问题 N 启用 Los Alamos 探索：

- **题目复杂度初判（最早触发点，见下方说明）**：还没开始文献调研、还没进入建模，
  仅凭题目原文本身，就判断出该子问题结构复杂/开放性强；
- 用户在对话中显式要求（"这题模型不确定/都试试/帮我比较几种方法"）；
- `memory/thought_process.md` 里问题 N 的文献调研已发现 ≥2 种互不相同、都有文献
  支持的建模范式；
- 单模型 verify 通过但灵敏度分析显示解对假设高度敏感（首次建模验证边际信号）；
- 题目原文对问题 N 出现"比较不同方法""讨论优缺点"等字样；
- 剩余时间预算充足（用户告知或 `pipeline.json` 有截止日期字段时距今 > 48h）。

命中则继续 Step 1；未命中，直接按普通单模型流程处理问题 N（见路径 A/B 原有步骤）。
六条触发源检查时机不互斥——**最早在 `problem_analysis` 阶段（Checkpoint① 之后）
就该做一次"题目复杂度初判"**，不要等到 data_preprocessing/文献调研阶段才第一次
评估；后续阶段（文献调研、首次验证）浮现的证据依然可以补触发，不要因为
problem_analysis 时判断"暂不需要"就关闭这个窗口。

**"题目复杂度初判"怎么判断**：不是凭感觉，看题目本身是否呈现以下任一客观特征——
要求"设计方案""提出并论证策略"而非单一确定性计算；在多个目标间权衡（覆盖率 vs
成本 vs 可行性这类）；结果对不确定量的建模方式选择很敏感；该类问题存在业界公认
的至少两种不同技术路线（如精确算法 vs 启发式算法）。命中越早发现越好，因为
Los Alamos 是叠加层，早触发不影响后续正常推进，晚触发则要接受已经做掉的工作
无法回溯利用范式比较的收益。

**贯穿 Step 3~9 的一条规则：决策前先查树，不要只靠自己的叙述记忆判断。**
`hypothesis_tree.py` 不是只写不读的审计日志——是否要继续展开、要不要合并/回溯、
决赛圈还剩哪些候选没决出胜负，这类判断点动手前先跑一次：

```bash
python scripts/los_alamos/hypothesis_tree.py status --problem-n {N}
```

拿到当前物化视图（前沿 / 决赛圈 / 已剪枝归档）的真实状态再决定下一步，而不是
凭记忆猜"现在应该还有哪几个分支在跑"——分支数量一多、跨越多轮 build/verify/
红队之后，叙述记忆很容易跟实际状态脱节，`status` 是唯一权威来源。

**Step 1 — Alsos 冷启动普查（spawn 一次性子 Agent）**

```
Agent(description="问题N Alsos 文献普查", prompt=<Alsos 普查 Prompt 模板>)
```

**Alsos 普查 Prompt 模板：**
```
你是问题 {N} 的 Alsos 情报组，任务是做一次结构化文献普查，不建模、不下结论。

1. 用抽象化关键词（不要直接粘贴题目原文，遵守 SOP S3）检索该题型的已有解法，
   目标 ≥8 篇跨越不同范式的文献。
2. **对照 `LOS_ALAMOS_METHOD_CATALOG.md` 自查**：题目所属的大类（优化/预测/
   评价/仿真/分类/网络）里，清单上列出但纯文献检索没搜到的候选范式，针对性补
   一轮检索——这一步是为了防止文献普查只找到"最常见"的范式、漏掉同样适用但
   不那么显眼的技术路线，不是要凑齐清单上所有条目。
3. 对识别出的每个建模范式，写一条结构化记录（paradigm_id 格式 PM-P{N}-序号）：
   name / typical_assumptions / strengths / weaknesses / applicable_when /
   citations / maps_to_division（T=解析理论 / E=数值仿真 / O=元启发式 / CM=数据驱动，
   若都不像就留空，不必强行归类）。
4. 把结构化列表写入 CUMCM_Workspace/memory/paradigm_pool_{N}.json（JSON 数组），
   人类可读版写入 memory/literature_survey_{N}.md；**每篇引用同时用
   `scripts/cite_check.py register --problem-n {N} ...`（见 SOP §15）登记进共享
   引用池，不要只写进 JSON 就算了——`quality_gate.py lit` 认的是登记+核验过的
   citations.bib，不是 paradigm_pool_{N}.json 里的自由文本**。
5. 完成后输出一行：[Alsos-P{N}] ✓ 普查完成，发现 {paradigm_count} 种范式，
   分歧点：<一句话>。
```

**Step 2 — 冻结范围锚点与评分标准**

```bash
mkdir -p CUMCM_Workspace/state
cat > CUMCM_Workspace/state/scope_anchor_{N}.md << 'EOF'
# 问题 {N} 范围锚点（冻结于 Los Alamos 探索开始时，非 Checkpoint LA 不得修改）
## 这个子问题到底在问什么
<一段话复述题目对问题 N 的要求>
## 已确认的假设（探索开始前）
<列出 problem_analysis 阶段已写入 thought_process.md 的假设>
EOF
```

同时确定决赛圈的量化评分标准（Track 1 会用到的 criteria 清单，例如
鲁棒性/残差/参数个数/求解耗时），先写死，不得在裁决快出结果时现改。

**Step 3 — 展开第一层分支（不 spawn Agent，Director 自己内联判断 + 记账）**

参考 `paradigm_pool_{N}.json`，选真有文献支持、互不相同的范式登记为节点（不要求
T/E/O/CM 四个全上）——**分支数量不是固定 2~3 个，是时间预算的函数**：时间紧迫
（或已判定 Skunk Works）就收敛到 2 个最有希望的；时间预算充足（同 §9.2/§13 用
的 48h 默认阈值）应该尽量多展开到 3~4 个，覆盖不同大类（比如优化类 + 预测类/
评价类各一个），而不是止步于最先想到的两个——`LOS_ALAMOS_METHOD_CATALOG.md`
就是为了让这一步有更宽的候选池，不要因为"想到两个就够用了"而提前收窄。

```bash
python scripts/los_alamos/hypothesis_tree.py expand --problem-n {N} \
  --node-id N-P{N}-001 --assumption-id A-P{N}-T-01 --seed-paradigm T --depth 1
# ……对每个第一层分支各跑一次 expand
```

**同一范式内部的技术路径分岔也可以再展开一层**（`depth` 递增、`--parent-ids`
指向父节点），不是只能在第一层比范式、范式选定后就直接一条路走到黑——比如
父节点 N-P{N}-001 选定"MILP 精确解"这个范式后，如果求解器选择、离散化粒度、
约束松弛策略之间本身就有值得比较的技术分歧，可以对它再展开：

```bash
python scripts/los_alamos/hypothesis_tree.py expand --problem-n {N} \
  --node-id N-P{N}-001-a --parent-ids N-P{N}-001 \
  --assumption-id A-P{N}-T-01a --seed-paradigm T --depth 2
# 例：N-P{N}-001-a = "HiGHS 精确求解"，N-P{N}-001-b = "分支定界+启发式热启动"
```

深层分支同样要走 Step 4 筛选、Step 5 build+verify、Step 6 红队——不因为"只是
同一范式内部的选择"就降低验证要求。是否值得展开到这一层，取决于该技术选择
本身对最终结果的影响是否足够大（如果只是求解器实现细节、结果几乎不受影响，
就不必展开，写一句理由说明"未展开"即可，不要为了"看起来更深"而硬凑分支）。

**Step 4 — Track 0 语义筛选（Director 自己内联判断，不 spawn Agent）**

对每个刚展开的节点，Director 直接读该分支的假设陈述 + Alsos 情报，给出裁定并记账
（低成本、高频，明确不额外花一次 Agent spawn）：

```bash
python scripts/los_alamos/adjudicate.py screen --problem-n {N} --node-id N-P{N}-001 \
  --coherence 0.0-1.0 --plausibility 0.0-1.0 --novelty 0.0-1.0 \
  --problem-alignment 0.0-1.0 --verdict expand|prune|merge_candidate|needs_more_intel \
  --rationale "一句话理由"
```

`verdict=prune` 的分支到此为止（归档，不再往下走）；`needs_more_intel` 先向 Alsos
补查（见下方"探索期间的情报请求"）再重新筛选；`expand` 的分支进入 Step 5。

**Step 5 — 存活分支各自 build + verify（spawn 独立子 Agent，并行）**

```bash
python scripts/los_alamos/hypothesis_tree.py status --problem-n {N}
# 前沿列出的 screened_pass 节点，才是本步真正要 spawn 的对象——以此为准，
# 不要凭 Step 3/4 时的记忆去猜"应该有哪几个"
```

对每个 `status` 报出的 `screened_pass` 节点，在**同一条消息**中并发启动：

```
Agent(description="问题N-分支node_id build+verify", prompt=<Division 子 Agent 模板（Los Alamos 版）>)
```

**Division 子 Agent 模板（Los Alamos 版，在原 AP 子 Agent 模板基础上追加 ledger + 情报记账）：**
```
你是问题 {N} 假设分支 {node_id} 的 Division，负责该分支的完整 build + verify 流程。

前置检查：
- 读取 CUMCM_Workspace/state/scope_anchor_{N}.md，确认本分支假设未越界

执行（严格按顺序，禁止跳步）：
1. python scripts/los_alamos/hypothesis_tree.py mark --problem-n {N} \
     --node-id {node_id} --state building --sender Division-{node_id}
2. 编写 CUMCM_Workspace/src/models/problem{N}_variant_{node_id}.py 并运行至无报错
3. 在 CUMCM_Workspace/memory/ledgers/problem{N}_{node_id}.json 中，为本分支用到的
   每条关键假设写一条 ledger 记录（id/statement/math_form/source/source_ref/
   citation_id/depends_on/downstream_impact/falsifiable_if/proposed_by，
   schema 见 AutoMCM_SOP.md §9.2），depends_on 正确指向父节点传下来的假设 id
4. 若建模中需要补充文献依据，先发情报请求再自行检索：
   python scripts/los_alamos/bus.py send --problem-n {N} \
     --performative INTEL_REQUEST --sender Division-{node_id} --receiver Alsos \
     --ref-assumption-id <本分支假设id或父假设id> \
     --content '{"query": "...", "justification": "..."}'
   （必须提供 --ref-assumption-id 或 --new-assumption-proposal 二选一，否则会被
   quality_gate.py message 判定违规——不得未登记直接引用未经检索的"常识性"文献）
5. 编写并运行 CUMCM_Workspace/src/verifications/verify_problem{N}_variant_{node_id}.py
   （验证清单同 AutoMCM_SOP.md §4.3，末尾打印结构化 VERIFICATION REPORT）
6. python scripts/los_alamos/hypothesis_tree.py mark --problem-n {N} \
     --node-id {node_id} --state verify_pass --sender Division-{node_id}
   （若 FAIL → 修复模型代码，重跑验证，循环直至 PASS 再执行本步）

完成后输出一行：[{node_id}] ✓ build+verify 通过，等待红队复核。
```

**Step 6 — Bletchley 红队复核（spawn 独立子 Agent，不能是原 Division 自己）**

对每个 `verify_pass` 的分支，并发启动：

```
Agent(description="问题N-分支node_id 红队复核", prompt=<Bletchley 红队 Prompt 模板>)
```

**Bletchley 红队 Prompt 模板：**
```
你是红队，任务是攻击、不是评价。你拿到的是问题 {N} 分支 {node_id}：已通过自证
（verify PASS）的模型代码、verify report、假设 ledger
（CUMCM_Workspace/memory/ledgers/problem{N}_{node_id}.json，含每条假设的
falsifiable_if 字段）。

你的目标不是判断"写得好不好"，而是主动尝试证明它是错的：
1. 对 ledger 里每条关键假设，实际检查其 falsifiable_if 条件是否真的被数据/结果
   触发（不要相信 ledger 里"未触发"的自我陈述，自己重新算一遍）；
2. 构造至少 2 个 verify_*.py 未覆盖的边界/极端场景，检查模型是否给出荒谬结果；
3. 尝试构造一个满足题目约束但会让结论方向逆转的反例。

把结果记账（无论攻破与否都要如实报告，不要为了"有产出"夸大问题）：
python scripts/los_alamos/adjudicate.py redteam --problem-n {N} --node-id {node_id} \
  --verdict survived|weakened|broken --severity none|minor|major|fatal \
  --rationale "一句话理由" \
  --attacks-json '[{"type":"...","result":"..."}, ...]'

完成后输出一行：[{node_id}] 红队裁定 = <verdict>。
```

**Step 7 — 主 Agent 汇总红队结果，处理 `broken` 分支**

```bash
python scripts/quality_gate.py red-team --problem-n {N} --node-id N-P{N}-001
# 退出码 0 → 该分支进入决赛圈；退出码 1 → broken，打回 Step 5 修复后重新 Step 6
```

**Step 8 — Groves 巡检（可随时调用，通常每轮 Step 3~7 结束后跑一次）**

```bash
python scripts/los_alamos/groves_monitor.py check --problem-n {N}
```

若 `alerts_raised > 0`，读取最新一条 `DRIFT_ALERT`/`BUDGET_ALERT`（
`python scripts/los_alamos/bus.py read --problem-n {N} --performative DRIFT_ALERT`），
自行判断是否收敛（可以书面理由 override 继续探索，但该决定本身会被记账，不是
悄悄无视）。

**Step 9 — 决赛圈：双轨裁决**

```bash
python scripts/los_alamos/hypothesis_tree.py status --problem-n {N}
# "决赛圈（in_tournament）"列出的才是真正存活到这一步的分支——凭这个判断
# 有几个要裁决，不要凭 Step 5/6 时候的记忆
```

存活分支数 ≥ 2 时才需要真正裁决（只剩 1 个分支直接晋级，跳到 Step 10）：

```bash
# Track 1：整理各分支 verify report 里的量化指标为 decision_matrix.json，见
# scripts/los_alamos/README.md 的示例格式，然后：
python scripts/los_alamos/adjudicate.py entropy-weight --problem-n {N} \
  --matrix-file decision_matrix_{N}.json

# Track 2：spawn 3~5 个独立评审子 Agent（同一条消息并发），每个都用下方模板
```

```
Agent(description="问题N 评审员1", prompt=<Track2 评审 Prompt 模板>)
Agent(description="问题N 评审员2", prompt=<Track2 评审 Prompt 模板>)
Agent(description="问题N 评审员3", prompt=<Track2 评审 Prompt 模板>)
```

**Track 2 评审 Prompt 模板：**
```
你是问题 {N} 的独立评审 judge-{k}，评审对象是以下候选分支（材料已匿名化，不含
分部代号/proposed_by 字段——请勿询问或猜测哪个分支来自哪个建模范式）：
<粘贴各存活分支的 ledger + verify report 摘要，去掉 proposed_by 字段>

你不知道其他评审的判断，也不能假设自己的判断需要与别人一致。
对每一对候选 (A, B)，针对以下维度分别给出 A>B / B>A / TIE 的偏好和一句话理由，
禁止给出绝对数值分数：
- physical_plausibility（物理/数学合理性）
- problem_fit（与题意的贴合度）
- parsimony（假设精简度）

每一对每一维度都要记账：
python scripts/los_alamos/adjudicate.py panel-vote --problem-n {N} \
  --judge-id judge-{k} --candidate-a <node_id_A> --candidate-b <node_id_B> \
  --dimension physical_plausibility|problem_fit|parsimony --preference A|B|TIE \
  --rationale "一句话理由"

完成后输出一行：[judge-{k}] ✓ 全部两两比较已提交。
```

主 Agent 等待全部评审子 Agent 返回后：

```bash
python scripts/los_alamos/adjudicate.py panel-entropy --problem-n {N} --round 1
python scripts/los_alamos/adjudicate.py combine --problem-n {N}
# 退出码 0 → 有明确冠军，进入 Step 10a
# 退出码 1 → 存疑：分歧熵超阈值时，不要直接跳 Step 10b——先试 RAND Delphi 匿名
#           收敛（AutoMCM_SOP.md §9.6，最多 2 轮）：
#   python scripts/los_alamos/adjudicate.py delphi-summary --problem-n {N} --round 1
#   （把摘要给评审小组读，重新收一轮 panel-vote --round 2，再跑
#    panel-entropy --round 2 —— 仍不收敛（含首轮共 3 轮后）才进入 Step 10b）
```

**Step 10a — 有明确冠军：映射为 canonical 产物，正常推进**

```bash
cp CUMCM_Workspace/src/models/problem{N}_variant_<champion_node_id>.py \
   CUMCM_Workspace/src/models/problem{N}_{type}.py
cp CUMCM_Workspace/src/verifications/verify_problem{N}_variant_<champion_node_id>.py \
   CUMCM_Workspace/src/verifications/verify_problem{N}_{type}.py
# 重新跑一遍确认在 canonical 路径下依然无报错，然后按原有 AP 自评流程
# advance model_{N}_build → model_{N}_verify（quality_gate.py verify/red-team 均需通过）

# 落选分支归档，作为论文"模型比较"素材：
echo "问题 {N} 落选分支：见 memory/ledgers/problem{N}_*.json 与 state/leaderboard_{N}.md" \
  >> CUMCM_Workspace/memory/alternative_approaches_{N}.md
```

**Step 10b — 存疑：强制 Checkpoint LA，AP 模式也不能自评自批**

这是**唯一一个 AP 模式下也必须真正停下来等待人类输入的环节**——"选哪个模型代表
队伍参赛"是价值判断，不该由 AI 自己拍板。执行现有 Checkpoint 命令，但**跳过"AP
模式自评自批"分支**，无论当前是 AP 还是 MANUAL 模式，都按【Checkpoint 执行模板】
里的"MANUAL 模式 — 自然语言等待人类反馈"流程处理：

```bash
python scripts/pipeline_manager.py request-review \
  --stage "model_{N}_adjudicate" \
  --summary "$(cat CUMCM_Workspace/state/leaderboard_{N}.md)" \
  --results "Track1/Track2 排名与分歧熵见上" \
  --concerns "两轨冲突或分歧熵过高，需要人类判断哪个分支更合适" \
  --next "model_{N}_build"
```

人类选定后，按 Step 10a 的方式映射产物、归档落选分支，继续正常流水线。

---

### Stage: sensitivity_analysis

```bash
python scripts/pipeline_manager.py start-stage sensitivity_analysis
```

1. 编写 `src/models/sensitivity.py`
2. 编写 `src/verifications/verify_sensitivity.py`（数值稳定性检查）
3. **发起 Checkpoint ④**

---

### Kaizen 质量自评（可选，approved 之后、latex_draft 之前）

> `AutoMCM_SOP.md` §13。每个子问题 `sensitivity_analysis` approved 后做一次：

```bash
python scripts/pipeline_manager.py kaizen-assess --problem-n {N} \
  --significance {1-5} --robustness {1-5} --assumptions {1-5} --completeness {1-5} \
  --weakest "<最弱维度一句话>"
```

- 退出码 0（PROCEED）→ 直接进入 latex_draft；
- 退出码 1（ROUND_RECOMMENDED）→ **先判断时间预算**（同 Los Alamos Step 0 的
  48h 默认阈值）：预算充足才 `kaizen-round-start --problem-n {N} --plan "..."`
  打磨一轮（针对 `--weakest` 指出的短板，改进后必须重新走 §4 验证），预算不足
  或没有时间信息就直接放行——不主动追问用户要不要打磨；
- 决定打磨前必须先用自然语言告知用户"质量自评发现 X 偏弱，时间预算允许，
  将打磨一轮"，不能静默进行。

---

### Stage: latex_draft

```bash
python scripts/pipeline_manager.py start-stage latex_draft
```

**只有在所有 model_n_verify 阶段均为 `approved` 后，方可开始此阶段。**

1. 使用对应模板（CUMCM → `latex_template.tex`，MCM → `mcm_template.tex`）
2. **按 `AutoMCM_SOP.md` §16 规划-分段-风格自查写作**：每节动笔前先在
   `thought_process.md` 写几句这一节的论证逻辑，写完一节再写下一节；每写完
   2~3 节（或全篇初稿后）跑一次风格自查，最多 2 轮：
   ```bash
   python scripts/style_check.py scan --file CUMCM_Workspace/latex/main.tex
   # 退出码 1 时按报告逐条真实改写（不是换几个同义词敷衍），不动数值结论——
   # 内容层面的问题属于 Kaizen（§13）的职权，风格打磨只改"怎么表达"
   ```
3. 插入图表时，**确认对应图片文件物理存在** `latex/images/*.png`
   - 数据/结果图 → 必须来自已运行的 Python 代码，且已用 `plot_style.apply()`
     统一风格（见【图表风格规范】）——若发现某张图不是用该模块生成的（配色随手写、
     中文可能乱码），补跑一遍再插入，不要直接引用
   - 流程图 / 概念插图 → 使用 `/draw-image` skill 生成：
     ```bash
     python scripts/draw_image.py \
       --prompt "..." \
       --output "CUMCM_Workspace/latex/images/figXX_name.png" \
       --quality high
     ```
4. 参考文献部分：先确认全部核验过（`python scripts/cite_check.py verify`，
   退出码需为 0），再导出粘贴，不要手写：
   ```bash
   python scripts/cite_check.py export-bibitems --verified-only
   # 输出直接粘贴进 main.tex 的 \begin{thebibliography}...\end{thebibliography}
   ```
   `main.tex` 里只应该有**一处**"参考文献"标题——模板的 `\section*{参考文献}`
   已经在正文里占了位，`\begin{thebibliography}` 环境自己不需要再手写一个
   `\section*{参考文献}`，否则会连续出现两次同名标题。
5. 附录代码块（`\lstinputlisting`）**必须用模板预定义的 `style=pythonstyle`**
   （`templates/latex_template.tex` 里 `\lstdefinestyle{pythonstyle}{...}` 已经
   配好 `showstringspaces=false`/语法上色/CJK 兼容），不要自己另外拼
   `basicstyle=\ttfamily...` 这类选项——那样会漏掉 `showstringspaces=false`，
   代码字符串里的空格会被显示成方块符号，也丢了语法高亮。
6. **附录代码默认写节选，不是整份塞进去**（AutoMCM_SOP.md §17.4）：每个
   model 文件只放能体现核心求解逻辑的 1 个函数（通常是最优化/核心算法那个，
   不是 `main()`/绘图/样板 `import`），用 `firstline`/`lastline` 直接从真实
   源文件截取（不要另外复制一份"节选文件"，截取范围随源文件自动同步）：
   ```latex
   \lstinputlisting[style=pythonstyle, firstline=161, lastline=186,
     caption={坐标轮换精化核心（完整文件另 407 行，含...）}]{../src/models/xxx.py}
   ```
   只有真正很短的文件（一两百行以内，比如 `sensitivity.py`）才整份收录；
   `src/verifications/` 下的验证脚本默认不进附录。写完后跑一次
   `python scripts/compile_pdf.py` 看页数提醒，CUMCM 正文目标 20~25 页
   （硬上限 30），仍超标才依次精简节选范围、再精简正文次要内容——不得删
   §4 要求的验证逻辑本身，只是不整份塞进附录。
7. **发起 Checkpoint ⑤**

---

### Stage: final_compile

**开始前先跑 Go/No-Go 发射前检查（强制，见 AutoMCM_SOP.md §12）：**

```bash
python scripts/quality_gate.py launch-check
# 退出码 1 → 按报告逐项修复（缺图/占位符残留/阶段未approved/andon未清）后重跑，
#           不得跳过直接进入 final_compile
```

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
| Los Alamos 分支 build+verify | 同一子问题内 2~3 个假设分支 | 路径 C 触发条件命中（见上）+ Track0 筛选通过 | Director 手动并发 spawn，见路径 C Step 5 |
| Los Alamos 红队复核 | 各 `verify_pass` 分支各一个红队 Agent | Step 5 通过 | 路径 C Step 6 |
| Los Alamos 评审小组 | 3~5 个独立评审 Agent | 决赛圈存活分支 ≥ 2 | 路径 C Step 9 |
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

## 【图表风格规范】

所有进入论文的图表（EDA、模型结果、灵敏度分析……）**必须**通过
`scripts/plot_style.py` 生成，不得在各自脚本里手写字体/配色。理由：论文评委看到的
第一印象往往是图表，配色随意、中文显示成方框是很容易避免却经常发生的减分项。

### 画图前先查这类问题的常规可视化方式（这是"画什么图"，`plot_style.py` 管的是"怎么画好看"）

**AutoMCM_SOP.md §18**：动笔画图前，先用运行时的网络检索工具搜一下这类子问题在
学术文献/相关领域里通常用什么图表呈现结果——不要不假思索地套用"折线图/柱状图"
这种通用默认，不同问题类型的领域惯例差异很大，随手选错图会让结果的信息密度和
专业观感明显打折：

- **轨迹/几何优化**（路径规划、拦截、投放策略）→ 通常是 3D 轨迹图 + 关键时刻
  标注（投放点/起爆点/交汇位置），或俯视投影叠加有效窗口时间轴
- **覆盖/选址/分配** → 通常是地图/散点覆盖示意图 + 甘特图式的调度时间表
- **多目标/多方案比较** → 通常是 Pareto 前沿图或雷达图，不是简单柱状图并排列
  几个数字
- **灵敏度分析** → 通常是 tornado 图（龙卷风图，参数按影响幅度排序的水平条形图）
  或多参数曲线族叠画在同一张图上，不是每个参数各画一张孤立折线图
- **分类/聚类/评价排序** → 通常是热力图或堆叠条形图，按某个排序维度重新排列
  类别顺序，不是按数据原始顺序摆放

搜索关键词按 SOP S3 抽象化（不要直接贴题目原文），例如
`"UAV trajectory optimization visualization"`、
`"facility location coverage map visualization"`、
`"sensitivity analysis tornado chart"`，找 2~3 个例子确认该领域常见呈现形式，
把判断记一笔到 `thought_process.md`（哪种问题对应哪种图、参考依据是什么），
再动手画。搜不到明确惯例、或题目类型比较小众时，退回常识判断即可，不必强求
"一定要找到文献佐证"，但要在 `thought_process.md` 里如实写"未查到明确领域惯例，
按常识选用 XX 图"，不要跳过这一步的记录。

### 标准用法

```python
import sys
sys.path.insert(0, "scripts")   # 按脚本实际相对路径调整
import plot_style
plot_style.apply()              # 一次性设置：中文字体 + 统一配色 + 网格/坐标轴规范

fig, ax = plt.subplots()
ax.plot(x, y, color=plot_style.CATEGORICAL[0], label="…")   # 分类色按固定顺序取用
...
plot_style.save(fig, "CUMCM_Workspace/latex/images/figXX_name.png")  # 300dpi、白底、裁边
```

### 配色规则（不是随手挑颜色，来自色盲安全性验证过的色板）

- **分类对比**（不同方案/不同问题/不同系列）→ `plot_style.categorical(n)`，按固定顺序
  取用，**不要超过 8 个**——超过就该合并成"其他"或改用小倍数图，而不是继续生成新颜色
- **散点图/气泡图/小倍数图**（任意两个系列都可能相邻比较）→ 只用
  `plot_style.CATEGORICAL_ALL_PAIRS_SAFE`（前 3 个色，两两配对都验证过色盲安全）
- **连续量级**（热力图等）→ `plot_style.sequential_cmap()`（单一蓝色渐变，从不用彩虹色）
- **正负偏差/相对基准**→ `plot_style.diverging_cmap()`（蓝↔红，中性灰中点）
- **状态类**（通过/警告/失败）→ `plot_style.STATUS` 字典，固定含义，不挪用作第 N 个
  分类色

### 中文字体（这是本模块存在的直接原因）

`plot_style.apply()` 内部会自动检测系统已装的中文字体（含一次系统字体目录的实时
扫描，覆盖"字体装了但 matplotlib 缓存没刷新"的情况），设置 `axes.unicode_minus =
False`（否则负号在中文字体下经常显示异常/方框——很容易被忽略的坑），并把
`font.family` 设成"中文字体 + DejaVu Sans"的显式回退列表，让中文字符走中文字体、
西文字母数字走 DejaVu Sans（只设 `font.sans-serif` 不会触发这个逐字形回退，
实测验证过）。

若检测不到中文字体，会打印按操作系统区分的安装建议（见 Step 4 按需依赖处理），此时
**图表标题/标签暂时改用英文**，不要让方框乱码进入论文。

### 硬性规则

1. **禁止**图表脚本自行 `plt.rcParams[...]` 覆盖 `plot_style.apply()` 设置的字体/
   配色（局部微调可以，比如某张图确实需要更大字号，但底色和分类色顺序不能改）
2. **禁止**跳过 `plot_style.save()` 直接用 `fig.savefig()`（会漏掉 300dpi/白底/
   裁边的标准化，输出质量不稳定）
3. 生成含中文标签的图表前，在实际需要时运行
   `python scripts/plot_style.py check` 确认字体可用

---

## 【建模质量门控】

质量门控由 `scripts/quality_gate.py` 强制执行，**不是 AI 行为规则，而是硬检查脚本**。  
在对应时机调用，退出码 1 时禁止 advance。

### 调用时机

**门控用到的临时输出文件一律写在工作区内**（`CUMCM_Workspace/state/.tmp/`），
**不要写到 `/tmp/`**——有沙盒限制的 runtime（opencode/dsh/Codex 等，实测确认
opencode 会因为 `external_directory` 权限拒绝写工作区之外的路径导致整条命令
失败）会拦截工作区外的写入，Claude Code 默认没有这层限制所以之前没暴露这个
问题，但协议本身必须假设最严格的沙盒。

```bash
mkdir -p CUMCM_Workspace/state/.tmp

# model_N_build 开始前 — 门控 1：文献引用
python scripts/quality_gate.py lit --stage model_{N}_build --problem-n {N}
# 退出码 1 → 补充文献再编码

# model_N_build 运行后 — 门控 2：数值合理性
python src/models/problem{N}_{type}.py > CUMCM_Workspace/state/.tmp/model_output.txt 2>&1
python scripts/quality_gate.py sanity --stage model_{N}_build --output-file CUMCM_Workspace/state/.tmp/model_output.txt
# 退出码 1 → 回到模型修复

# model_N_verify 运行后 — 门控 3：结构化报告解析
python src/verifications/verify_problem{N}_{type}.py > CUMCM_Workspace/state/.tmp/verify_report.txt 2>&1
python scripts/quality_gate.py verify --stage model_{N}_verify --report-file CUMCM_Workspace/state/.tmp/verify_report.txt
# 退出码 1 → 禁止 advance

# 所有 verify 完成后（并行模式）— 门控 4：多问题一致性
python scripts/quality_gate.py consist --problems {N}
# 退出码 1 → 修复后重跑受影响的 verify

# 或一次运行所有适用门控
python scripts/quality_gate.py all \
  --stage model_{N}_verify \
  --report-file CUMCM_Workspace/state/.tmp/verify_report.txt \
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
# 同样写在工作区内，不写 /tmp/
mkdir -p CUMCM_Workspace/state/.tmp
# 尝试 1
xelatex -interaction=nonstopmode main.tex 2>&1 | tee CUMCM_Workspace/state/.tmp/latex_out.txt
grep -q "! LaTeX Error\|Undefined control sequence" CUMCM_Workspace/state/.tmp/latex_out.txt && {
  # 解析错误行号 → 修复 main.tex → 尝试 2
  xelatex -interaction=nonstopmode main.tex 2>&1 | tee CUMCM_Workspace/state/.tmp/latex_out.txt
  grep -q "! LaTeX Error\|Undefined control sequence" CUMCM_Workspace/state/.tmp/latex_out.txt && {
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

---

## 【LeanGate：可选 Lean 形式化验证】

LeanGate 默认关闭；启用方式、状态契约和禁止事项以 `AutoMCM_SOP.md §19` 为准。Claude Code
只负责调用共享实现，不得自行写入证明成功状态：

```bash
python scripts/leangate.py doctor
python scripts/leangate.py --workspace CUMCM_Workspace init --policy selected
python scripts/leangate.py --workspace CUMCM_Workspace status --problem-n 1
python scripts/leangate.py --workspace CUMCM_Workspace verify --problem-n 1
python scripts/quality_gate.py formal --problem-n 1
```

LeanGate 启用后，离开 `problem_analysis` 前必须逐问题登记适用性并执行
`leangate.py seal-assessment`；安全边界、整数可行性、守恒、不变量、递推、收敛、
求解器证书或决策关键结论必须用 `--risk-category` 标注，自动成为 mandatory。

规格、证明或证书修改后必须重新语义审查、冻结和验证。Lean FAIL、UNKNOWN、STALE 或
Python FAIL 均不得写入论文为形式化结论。
LeanGate 启用后的 `model_N_verify` 推进必须传入工作区内真实验证脚本：
`pipeline_manager.py advance model_N_verify --verify-script CUMCM_Workspace/src/verifications/verify_*.py`。
`required` claim 还必须使用人类文件中的 `[APPROVED LeanGate ...]` 与 `[REQUIRED LeanGate ...]` 标记。
