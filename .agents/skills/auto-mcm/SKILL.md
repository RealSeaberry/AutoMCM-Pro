---
name: auto-mcm
description: >
  AutoMCM-Pro industrial-grade math modeling agent (Codex CLI binding).
  Supports AP (AI-led) and Manual (human-spec-led) dual modes with mandatory
  GitOps checkpoints, forced self-verification of all solver code before
  LaTeX inclusion, and structured human cross-validation at each pipeline
  stage. Use for both CUMCM (Chinese) and MCM/ICM (English) competitions.
---

# AutoMCM-Pro：Codex CLI 绑定

**这是 AutoMCM-Pro 协议在 OpenAI Codex CLI 上的运行时绑定（Binding），不是另一套
独立协议。** 行为规范权威来源仍是仓库根目录的 `AutoMCM_SOP.md`（工具无关，原样
复用）；可选探索层见 `LOS_ALAMOS_DESIGN.md`。Claude Code 绑定是
`.claude/skills/auto-mcm/SKILL.md`，DeepSeek Harness 绑定是
`.dsh/skills/auto-mcm/SKILL.md`——三份文件描述同一套流程，只是把"怎么调用工具"
换成各自 runtime 的实际工具，**流程逻辑、Checkpoint 规则、质量门控、Prompt 内容
不应该在几份文件间产生分歧**。完整背景见
[`CODEX_INTEGRATION.md`](../../../CODEX_INTEGRATION.md)。

## 【触发时的依赖安装询问】

每个新的 Codex 会话首次触发本 Skill 时，先询问用户是否安装核心 Python 建模依赖
（pdfplumber、scipy、numpy、matplotlib、pandas、openpyxl），以及是否准备可选的
LeanGate / Lean 4。不得预扫描或静默安装；用户同意后才调用
`bash install.sh --with-python-deps` 和/或 `--with-lean`。拒绝后同一会话不重复询问。
非交互执行无法取得回答时，显示问题并暂停，不得把沉默当作同意。

---

## 【与其他 runtime 最大的差异：Codex 只给模型一个"代码模式"工具，实测确认】

**这不是源码调研的推测，是实跑一次任务、解压
`~/.codex/sessions/**/rollout-*.jsonl` 核对过的**：Codex 模型端 function-calling
只看得到一个叫 `exec` 的顶层工具，参数是一段 **JavaScript 代码**；
`tools.exec_command({cmd, workdir, ...})` 是这段 JS 代码**内部**能调用的异步
函数，不是模型能单独调用的顶层工具。也就是说，`Bash`/`Read`（文本）在 Codex
上都是：模型写一段 JS，里面调用 `tools.exec_command({cmd: "..."})`，再用
`text(r.output)` 把结果吐出来——不是直接的 `{"tool": "exec_command", "cmd":
"..."}` 这种扁平 function call。

实测时甚至连读 `SKILL.md` 本身也是这样做的：模型用
`tools.exec_command({cmd: "sed -n '1,240p' .agents/skills/auto-mcm/SKILL.md"})`
直接读档，**没有专门的 skill 载入工具**——这点跟 opencode/dsh 都不一样（它们有
独立的 `skill` 工具）。

这件事对 AutoMCM-Pro **反而是天然契合**——本项目的流水线绝大部分工作本来就是
"用 `bash` 调 Python 脚本"，很少直接依赖结构化文件工具，翻译成 Codex 的
JS-in-exec 模式没有额外损失。

## 【工具映射表】

| Claude Code | Codex 工具 | 说明 |
|---|---|---|
| `Bash` | 顶层工具 `exec`（参数是一段 JS），内部调 `tools.exec_command({cmd,...})` | ✅ 实测确认（喚醒協議 Step 1 跑通）。万能工具：跑 Python 脚本、`cat` 读文件、`rg`/`grep`/`find` 搜索、`curl` 抓网页，本文件后续所有"执行 `python scripts/...`"都是这个模式，不是直接的扁平 function call |
| `Read` | 同上，`exec` 里的 JS 调 `tools.exec_command({cmd: "cat ..."})` | ✅ 实测确认（读 SKILL.md 本身就是这么做的） |
| `Read`（图片） | `view_image` | 专用图片查看工具，读图表/PDF 截图用它，不要用 `cat` |
| `Write`/`Edit` | `apply_patch` | 结构化 diff 应用工具，写/改模型代码、`.tex` 文件优先用它（比 shell heredoc 更可靠地保留缩进/编码） |
| `Glob`/`Grep` | `exec_command` 里 `rg`/`find` | 没有专用搜索工具 |
| `TodoWrite` | `update_plan` | 语义对应 |
| `AskUserQuestion` | 请求用户输入的工具（模块 `request_user_input`，**确切工具名未逐字核对**，见下方核验清单） | 语义对应 |
| `Agent(description, prompt)` | 多代理协同工具家族（模块 `multi_agents`/`multi_agents_v2`，**确切工具名未逐字核对**） | Codex 有原生多代理能力，但这次没有把确切的工具调用 schema 读完，接入前务必先跑一个最小测试确认参数格式 |
| `WebSearch`/`WebFetch` | **没有确认到的第一方工具** | 见下方【已知能力缺口】 |

上表里 `exec_command`/`apply_patch`/`view_image`/`update_plan` 四个工具名是从
`codex-rs/core/src/tools/handlers/` 源码里的 `ToolName::plain(...)` 字面量直接
核对过的（不是猜的）；`request_user_input`、`multi_agents`/`multi_agents_v2` 是
从模块/文件命名推断，**没有找到对应的字符串字面量**，接入前务必先用一个最简单的
任务实测一次，确认真实暴露给模型的工具名。

## 【已知能力缺口：网络搜索】

Codex 核心代码里没找到独立的 `web_search`/`web_fetch` 工具（`dsh`/opencode 都有，
Codex 没有内置）。看到的只有 MCP（Model Context Protocol）相关模块，猜测 Codex
把网络检索能力交给用户自行配置的 MCP server，而不是内置。这意味着：

- `AutoMCM_SOP.md` 里"文献调研至少 5 篇"这条硬性要求，**在 Codex 上落地前必须先
  确认有可用的网络检索能力**（配置一个 MCP 网络搜索 server，或者退化成
  `exec_command` 里 `curl` 调用一个你自己有权限的搜索 API）；
- 若确认没有任何网络检索能力，**不要静默跳过文献调研**——按 `AutoMCM_SOP.md`
  第 7 节"禁止静默跳过验证失败"的同一精神，在 Checkpoint①里如实告知用户"当前
  环境无网络检索工具，本阶段建模假设未经文献交叉验证"，让人类决定要不要补充
  MCP 配置或人工提供文献。
- 同样的缺口也影响 `AutoMCM_SOP.md` §18"画图前先查领域惯例"——判断某类问题的
  常规可视化形式本质上也是一次网络检索。**不要因为查不到就直接静默退化成随手
  选个图表类型**：先按上面同一套办法确认有没有可用的检索能力；确实没有的话，
  在 `thought_process.md` 里如实记录"当前环境无网络检索工具，图表形式选择依据
  建模者常识判断、未经领域惯例检索确认"，而不是不留痕迹地直接画图。

## 【运行方式】（Codex 特有）

```sh
codex           # 交互式
codex exec "task"   # 单次任务模式，类似 claude --print / dsh --profile headless
```

Skill 发现路径是 `.agents/skills/auto-mcm/SKILL.md`（仓库根向上找 `.git`，Codex
官方文档确认），显式调用用 `$auto-mcm`，或让模型按 `description` 隐式匹配。

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
领域惯例（AutoMCM_SOP.md §18）全部内容
与 Claude Code 版本一致，见
`.claude/skills/auto-mcm/SKILL.md` 对应小节（标题相同），
按上方【工具映射表】替换调用方式：

- **子 Agent 调用**：原文里每个 `Agent(description=..., prompt=<模板>)`，改为
  Codex 的多代理工具调用，`prompt` 字段内容完全不变（先按【已知能力缺口】小节的
  提醒实测确认参数格式，再套用到 Los Alamos 路径 C 的四套 Prompt 模板）
- **人类确认环节**：`ask_user_question` 换成 Codex 的用户输入请求工具
- **文件读写**：模型代码/验证脚本/LaTeX 文件优先用 `apply_patch`，图表结果查看用
  `view_image`
- `scripts/*.py` 系列命令（`pipeline_manager.py`/`quality_gate.py`/
  `los_alamos/*.py`/`plot_style.py`）**完全不变**，全部通过 `exec_command` 调用

---

## 【安全规程】

`AutoMCM_SOP.md` 的 S1~S5 原样适用。S3（外部服务调用告知）在 Codex 上尤其重要——
既然网络检索要靠用户自配的 MCP server，调用前更要做好关键词抽象化，不要把题目
原文整段发给一个你不确定信任边界的外部 MCP server。

---

## 【LeanGate：可选 Lean 形式化验证门禁】

LeanGate 默认关闭；行为规范见 `AutoMCM_SOP.md §19`。Codex 通过 `exec` 内的
`tools.exec_command` 调用共享命令：

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

不得直接编辑 `claims.json` 或报告来制造 PASS。任何输入变化后重新执行语义审查、冻结
与验证；Lean FAIL、UNKNOWN、STALE 或 Python FAIL 都是 NO-GO。
LeanGate 启用后的 `model_N_verify` 推进必须传入工作区内真实验证脚本：
`pipeline_manager.py advance model_N_verify --verify-script CUMCM_Workspace/src/verifications/verify_*.py`。
`required` claim 还必须使用人类文件中的 `[APPROVED LeanGate ...]` 与 `[REQUIRED LeanGate ...]` 标记。
