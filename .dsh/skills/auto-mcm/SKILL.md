---
name: auto-mcm
description: >
  AutoMCM-Pro industrial-grade math modeling agent (DeepSeek Harness binding).
  Supports AP (AI-led) and Manual (human-spec-led) dual modes with mandatory
  GitOps checkpoints, forced self-verification of all solver code before
  LaTeX inclusion, and structured human cross-validation at each pipeline
  stage. Use for both CUMCM (Chinese) and MCM/ICM (English) competitions.
whenToUse: >
  用户提供数学建模竞赛题目（CUMCM/MCM/ICM）并希望端到端自动/半自动完成建模、
  编码验证、论文撰写时使用。
---

# AutoMCM-Pro：DeepSeek Harness (dsh) 绑定

**这是 AutoMCM-Pro 协议在 DeepSeek Harness 上的运行时绑定（Binding），不是另一套
独立协议。** 行为规范的权威来源仍是仓库根目录的 `AutoMCM_SOP.md`（工具无关，原样
复用）；可选探索层见 `LOS_ALAMOS_DESIGN.md`。Claude Code 上的对应绑定是
`.claude/skills/auto-mcm/SKILL.md`——两份文件描述同一套流程，只是把"怎么调用工具"
换成各自 runtime 的实际工具名，**流程逻辑、Checkpoint 规则、质量门控、Prompt 内容
不应该在两份文件间产生分歧**；如果你在这份文件里找不到某个步骤的细节，去
Claude Code 版本对照，工具调用按下表替换即可。

---

## 【工具映射表】—— 全文遇到左列写法，按右列替换

| Claude Code 工具 | dsh 工具 | 来源包 |
|---|---|---|
| `Agent(description, prompt)`（一次性子 Agent，等待返回） | `subagent`（`description`/`prompt`，**不传** `run_in_background` 或传 `false`） | `dsh-tool-subagent` |
| 需要背景常驻、事后可追加指令的子 Agent | `subagent` 传 `run_in_background: true`（返回 `started subagent <id>`），之后用 `send_message`（`{subagent_id, message}`）追加、`list_agents` 查看状态、`interrupt_agent`（`{agent_id}`）中断——**这个 boolean 参数是同步/常驻的唯一开关，不传或传 false 会同步执行、不产生可追踪 id，`send_message` 对不存在的 id 会报 `Error: subagent "xxx" is unavailable`**（实测踩过这个坑） | `dsh-tool-subagent-control` |
| `AskUserQuestion` | `ask_user_question` | `dsh-tool-ask-user` |
| `WebSearch` | `web_search` | `dsh-tool-web` |
<!-- ⚠ 见下方【headless profile 的重要限制】：ask_user_question / web_fetch 在
     headless profile 下实测未挂载，上面两行是 web/交互式 profile 的理论映射 -->
| `WebFetch` | `web_fetch` | `dsh-tool-web` |
| `Bash` | `bash` | `dsh-tool-bash` |
| `Read` | `read`（图片用 `read_image`） | `dsh-tool-fs` |
| `Write` | `write` | `dsh-tool-fs` |
| `Edit` | `edit` | `dsh-tool-fs` |
| `Glob` | `glob` | `dsh-tool-fs-search` |
| `Grep` | `grep` | `dsh-tool-fs-search` |
| `TodoWrite` | `todo_write` | `dsh-tool-todo` |
| （载入其他 skill） | `skill` | `dsh-tool-skill` |

以上工具名取自 dsh 仓库 `docs/tool-catalog.md` 的实际工具目录（非猜测）；具体部署
若启用了非默认 bundle（比如把 `dsh-tool-bash` 换成 `dsh-tool-bash-persistent`），
调用方式基本兼容，但建议先跑 `dsh --profile <你的 profile> --dump-config` 确认
实际挂载的工具名与本表一致。

**continuable subagent 是 dsh 相对 Claude Code 绑定的一个真实增强**：Los Alamos
设计里把"Alsos/Groves 常驻服务"标注为"仅 Claude Code 可选优化、不是可移植基线"
（见 `LOS_ALAMOS_INTEGRATION.md` §2 的可选增强说明），是因为当时假设的运行时是
Claude Code；在 dsh 上，`send_message`/`list_agents` 是一等公民 API，如果你在 dsh
上落地 Los Alamos 探索层，**可以**把 Alsos 做成真正的常驻 continuable 子 Agent，
而不必退化成"每次查询都重新建立上下文"的文件轮询模式——但这是可选优化，本文件
的基线流程依然按文件+消息日志的方式描述，保证两个 runtime 的基线行为一致。

---

## 【唤醒协议】每次被调用时必须首先执行

每个新的智能体会话首次触发本 Skill 时，先分别询问是否安装核心 Python 建模依赖，
以及是否准备可选的 LeanGate / Lean 4。只询问，不预扫描、不静默安装；用户同意后
才调用 `bash install.sh --with-python-deps` 和/或 `--with-lean`，拒绝后本会话不再
重复询问。headless profile 无法等待回答时，显示问题并暂停，不得把沉默当作同意。

与 Claude Code 版本完全一致的三步判断，只是命令执行工具换成 `bash`：

```
bash: python scripts/pipeline_manager.py status
```

- 退出码 0（已初始化）→ 读取当前阶段和状态，跳到【流水线执行】
- 退出码非 0（未初始化）→ 执行下面的首次启动协议

**首次启动协议（全程自然语言，用户零命令）：**

1. 用 `ask_user_question` 询问：题目文件路径、附件数据位置、AP/MANUAL 模式（默认 AP）
2. 用 `read` 读取题目（PDF 走 `bash` 调 `pdfplumber`/`pypdf`），自动推断竞赛类型/子问题数/数据情况
3. 静默执行初始化：
   ```
   bash: python scripts/setup_workspace.py
   bash: python scripts/pipeline_manager.py init --mode {AP|MANUAL} --contest {CUMCM|MCM|ICM} --problems {N} --git
   bash: cp PROBLEM_PATH CUMCM_Workspace/data/
   ```
4. 自然语言告知用户就绪状态，随后按【按需依赖处理】和【流水线执行】继续

**按需依赖处理：**不要在唤醒时扫描或安装。实际命令因缺少 Python 包、LaTeX 或字体
而失败时，报告缺失项；只有用户明确同意后才安装。

---

## 【Checkpoint 执行模板】

与 Claude Code 版本语义完全一致：

```
bash: python scripts/pipeline_manager.py request-review \
  --stage "<stage>" --summary "..." --results "..." --concerns "..." --next "<next-stage>"
```

- **AP 模式**：`request-review` 会自动写入绑定阶段与轮次的自评批准；随后用 `bash`
  执行 `pipeline_manager.py advance <stage>`，自然语言汇报成果并直接开始下一阶段
- **MANUAL 模式**：展示汇报摘要，用 `ask_user_question`（而不是终端等待输入）明确
  询问"继续，还是需要修改？"，拿到回复后再决定 approve 还是 rework

**Checkpoint LA 例外**（仅 Los Alamos 模式，见 `AutoMCM_SOP.md` §9.2 第 4 条）：即使
当前锁定 AP 模式，遇到两轨冲突/分歧熵超阈值时，**必须**用 `ask_user_question` 真正
等待人类输入，不得走 AP 自评自批分支——这条规则在两个 runtime 上都不可变通。

---

## 【流水线执行】

阶段定义、状态机、Checkpoint 编号（①~⑤）、质量门控（`quality_gate.py`）、
Los Alamos 探索层（路径 C）、图表风格规范（`plot_style.py`）、Andon 紧急停止
（`pipeline_manager.py andon-pull/andon-clear/andon-status`）、Go/No-Go 发射前检查
（`quality_gate.py launch-check`，final_compile 前强制）、Skunk Works 轻量模式
（`pipeline_manager.py init --skunk-works`）、Track2 的 RAND Delphi 多轮收敛
（`adjudicate.py delphi-summary`）、Kaizen 质量打磨循环
（`pipeline_manager.py kaizen-assess/kaizen-round-start/kaizen-status`）、工作日志
（`worklog.py append/tail`，单文件简体中文完整记录，唤醒协议 Step 0）、文献引用
真实性核验+共享池（`cite_check.py register/verify/list/export-bibitems`）、写作
风格打磨（`style_check.py scan`，latex_draft 固有规范非可选 addon）、官方格式
合规（`quality_gate.py anon-check`、`ai_usage_doc.py generate/cite-format/
mcm-entry`、`compile_pdf.py` 编译后页数提醒，AutoMCM_SOP.md §17）、画图前先查
领域惯例（AutoMCM_SOP.md §18）
**全部内容与 Claude Code 版本一致**，只替换工具调用：

- `problem_analysis` → `data_preprocessing` → `model_{n}_build/verify`
  → `sensitivity_analysis` → `latex_draft` → `final_compile`，各阶段的具体工作内容、
  验证清单、Checkpoint 触发时机，见 `.claude/skills/auto-mcm/SKILL.md` 对应小节
  （标题相同，按【工具映射表】替换调用）
- **路径 A（多子问题并行）**：原文里每个 `Agent(description="问题N build+verify",
  prompt=<模板>)` 调用，改为对每个子问题分别调用 `subagent`（`prompt` 字段内容
  完全不变，模板本身是工具无关的自然语言指令）；等待方式改为等待各 `subagent`
  调用返回
- **路径 B（顺序执行）**：无子 Agent 调用，直接照搬
- **路径 C（Los Alamos 探索模式）**：Step 1（Alsos 普查）、Step 5（Division
  build+verify）、Step 6（Bletchley 红队）、Step 9（Track 2 评审小组）里的
  `Agent(...)` 调用同样按上表替换为 `subagent`；`scripts/los_alamos/*.py` 系列
  命令、`quality_gate.py` 新增门控、消息报文协议**完全不变**（这些是 `bash` 调用
  的 Python 脚本，与 runtime 无关）。四套 Prompt 模板（Alsos 普查 / Division /
  Bletchley 红队 / Track2 评审）文字内容原样复用，不需要因为换了 runtime 而重写

---

## 【Manual 模式附加规程】与【Rework 执行规程】

与 Claude Code 版本一致，唯一差异：人类确认环节一律用 `ask_user_question` 收集
自然语言回复，而不是等待终端输入。

---

## 【安全规程】

`AutoMCM_SOP.md` 里的 S1~S5 规则原样适用。S3（外部服务调用告知）在 dsh 上对应
`web_search`/`web_fetch` 调用前的关键词抽象化处理，规则不变。

---

## 【headless profile 的重要限制，实测确认，务必读】

**这不只是 headless 的限制——`dsh --profile web`（交互式 Web UI）用
`--dump-config` 核对过完整插件树，同样没有 `tool-ask-user`（`ask_user_question`
的来源包），也没有任何 web-fetch provider 包。** `web` profile 里有
`user-questions`/`ui-user-questions` 两个插件，但那是给人类在 Web UI 里被问
问题用的（比如批准/确认对话框），**没有包装成模型可调用的工具**——模型自己
仍然没有"主动发起提问"这个选项。`tui` profile 这个版本没有预装。也就是说，
**这个 dsh 版本（0.1.1-rc.2）目前没有任何一个默认 profile 能让模型真正调用
`ask_user_question`/`web_fetch`**，不是"切去交互式就好"，需要下面两条协议层面
的应对（完整判定依据见 [`DSH_INTEGRATION.md`](../../../DSH_INTEGRATION.md)
§3.1）：

### 1. Step 2a 改成"一次性把信息塞进任务指令"，而不是指望中途能问

**在 headless 下，【首次启动协议】Step 2a 不得调用 `ask_user_question`**——用户
发起 `dsh --profile headless "<task>"` 时，`<task>` 字符串本身就必须包含题目
路径、数据位置、AP/MANUAL 模式这三项信息（例如："题目在
CUMCM_Workspace/data/problem.pdf，数据在同目录，用 AP 模式"）。若用户第一句任务
指令没给全这三项，Agent 应该：

- 在纯文字回复里列出缺的字段，**不调用任何工具**，让本次 headless 调用直接
  结束（不要瞎猜、也不要卡住等一个不会来的回答）；
- 用户补全信息后再发起一次新的 `dsh --profile headless "<补全后的task>"`。

MANUAL 模式的逐阶段确认、Checkpoint LA 强制人类终审，这两类"必须等流程中途
出现的、无法提前塞进第一句话的信息"，在这个 dsh 版本里**目前没有任何默认
profile 能可靠支持**（`web` profile 虽然是交互式产品，但模型侧同样没有
`ask_user_question` 工具）——如果确实需要在中途暂停等人类批准，现阶段只能靠
`user-questions`/`ui-user-questions` 这层人类 UI 基础设施在 Web UI 里手动介入
（比如批准/权限对话框），而不是指望模型主动发起结构化提问；或者等 dsh 后续
版本把 `tool-ask-user` 接进默认 bundle 后重新验证。

### 2. web_fetch 缺失时，正式认可的替代路径：`bash` + `curl`，附处理清单

不再是"模型自己想办法"的临时应急，而是协议认可的正式 fallback——遇到需要读取
某个具体网页全文时：

```bash
curl -sL --compressed --max-time 30 -o /tmp/fetch_target.html "<URL>"
# --compressed 让 curl 自动处理 gzip/deflate/br 压缩，跳过手动 gzip -dc 这一步
file /tmp/fetch_target.html   # 确认拿到的是文本而不是仍被压缩/是二进制
```

拿到纯文本后再用 `read`/`grep` 处理。这条路径在这轮验证里实测跑通过（虽然当时
没加 `--compressed`，绕了一圈手动解压才成功——这里直接把踩过的坑写进正式做法，
下次不用重踩）。

---

## 【运行方式】（dsh 特有，Claude Code 绑定没有这部分）

```sh
# 交互式（Web UI）
npx @deepseek-ai/dsh web

# 零命令/单次任务模式（对应 Claude Code 的 `claude --print`）
pnpm dsh --profile headless "读取 problem.pdf 并开始建模"
```

需要 Node.js `^22.19` 或 `>=24`，以及 `DEEPSEEK_API_KEY`（或部署配置的其他模型
provider）。Python 依赖（`pdfplumber`/`scipy`/`numpy`/……）与 Claude Code 绑定
完全一样，只在用户对触发时的询问明确同意后调用安装器准备。

详细的架构对照与已知差异见 [`DSH_INTEGRATION.md`](../../../DSH_INTEGRATION.md)。

---

## 【LeanGate：可选 Lean 形式化验证】

LeanGate 默认关闭；共享规范见 `AutoMCM_SOP.md §19`。DSH 用 `bash` 调用同一实现：

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

不得直接编辑权威状态或用 runtime 审查意见升级 `FORMALLY_PROVED`。输入变化后必须重新
审查、冻结和验证；Lean FAIL、UNKNOWN、STALE 或 Python FAIL 都是 NO-GO。
LeanGate 启用后的 `model_N_verify` 推进必须传入工作区内真实验证脚本：
`pipeline_manager.py advance model_N_verify --verify-script CUMCM_Workspace/src/verifications/verify_*.py`。
`required` claim 还必须使用人类文件中的 `[APPROVED LeanGate ...]` 与 `[REQUIRED LeanGate ...]` 标记。
