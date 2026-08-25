---
name: auto-mcm
description: >
  AutoMCM-Pro industrial-grade math modeling agent (opencode binding).
  Supports AP (AI-led) and Manual (human-spec-led) dual modes with mandatory
  GitOps checkpoints, forced self-verification of all solver code before
  LaTeX inclusion, and structured human cross-validation at each pipeline
  stage. Use for both CUMCM (Chinese) and MCM/ICM (English) competitions.
---

# AutoMCM-Pro：opencode 绑定

**这是 AutoMCM-Pro 协议在 [opencode](https://github.com/sst/opencode)（`sst/opencode`，
MIT 授权）上的运行时绑定（Binding），不是另一套独立协议。** 行为规范权威来源仍是
仓库根目录的 `AutoMCM_SOP.md`（工具无关，原样复用）；可选探索层见
`LOS_ALAMOS_DESIGN.md`。Claude Code 绑定是 `.claude/skills/auto-mcm/SKILL.md`，
DeepSeek Harness 绑定是 `.dsh/skills/auto-mcm/SKILL.md`，Codex 绑定是
`.agents/skills/auto-mcm/SKILL.md`——几份文件描述同一套流程，只是把"怎么调用
工具"换成各自 runtime 的实际工具名。完整背景见
[`OPENCODE_INTEGRATION.md`](../../../OPENCODE_INTEGRATION.md)。

---

## 【工具映射表】—— opencode 的工具名和 Claude Code 几乎一一对应

| Claude Code | opencode 工具 |
|---|---|
| `Agent(description, prompt)` | `task` |
| `AskUserQuestion` | `question` |
| `Bash` | `bash` |
| `Read` | `read` |
| `Write` | `write` |
| `Edit` | `edit` |
| `Glob` | `glob` |
| `Grep` | `grep` |
| `WebSearch` | `websearch` |
| `WebFetch` | `webfetch` |
| `TodoWrite` | `todowrite` |
| （载入其他 skill） | `skill` |

以上 12 个工具 id **全部用真实任务实测过**（不是文档推断），详见
[`OPENCODE_INTEGRATION.md`](../../../OPENCODE_INTEGRATION.md) §3。

**⚠ 关键限制：`question` 在 `opencode run`（单次任务/headless）模式下默认权限
是 deny**——模型会尝试提问，但工具调用被权限系统挡下，退化成打印文字、没人能
回答。**【唤醒协议】Step 2a、MANUAL 模式的逐阶段确认、Checkpoint LA 的强制人类
终审，这几个环节都依赖 `question` 真正等到回复，必须用交互式的 `opencode`
（TUI）或 `opencode web` 跑，不能用 `opencode run`。** 工作区初始化完成后，如果
某一段流程确定不会触发任何需要人类介入的分支，才可以考虑用 `opencode run` 做
单次调用。

`task`（子代理委派）实测发现：委派子代理访问项目工作区之外的绝对路径会触发
工作区边界限制、卡在 running 状态问不到答案；委派子代理操作工作目录内的相对
路径则正常。Los Alamos 路径 C 用 `task` 派发 Division/红队/评审子代理时，
prompt 里给的路径应该是当前工作区内的相对路径，不要用跨目录的绝对路径。

## 【运行方式】（opencode 特有）

```sh
opencode          # 交互式 TUI
opencode run "task"   # 单次任务模式
```

Skill 发现路径是 `.opencode/skills/<name>/SKILL.md`（opencode 自己的仓库
`sst/opencode` 就用这个路径放它自己的内部 skill，`.opencode/skills/auto-mcm/`
是同一套约定）。opencode 额外还有 `.opencode/agent/*.md`（子代理人格定义，
frontmatter 支持 `mode`/`tools` 白名单/黑名单）和 `.opencode/command/*.md`
（slash command，支持 `` !`shell命令` `` 内联执行）两种配置文件类型，本次绑定
用不到，仅供后续想做更深度定制时参考。

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
按上方【工具映射表】逐一替换调用方式即可——由于工具名高度对应，这份绑定的
替换规则比 dsh/Codex 都更直接：几乎是把 `Agent(` 换成 `task(`、
`AskUserQuestion` 换成 `question`，其余照搬。

`scripts/*.py` 系列命令（`pipeline_manager.py`/`quality_gate.py`/
`los_alamos/*.py`/`plot_style.py`）**完全不变**，全部通过 `bash` 调用。

---

## 【安全规程】

`AutoMCM_SOP.md` 的 S1~S5 原样适用。
