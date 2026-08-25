# opencode 绑定说明

> 状态：**已完整执行验证**（2026-08-23，opencode v1.18.18，`opencode/big-pickle`
> 模型）——§3 表格里全部 12 个工具 id 都用真实任务跑过，逐一导出 session 的
> 结构化工具调用日志核对，不是文档推断。唯一的例外和最重要的发现记在 §3.1。

---

## 1. 定位

延续 Spec/Binding 分层：`AutoMCM_SOP.md`（+ 可选的 `LOS_ALAMOS_DESIGN.md`）是
工具无关的协议本体（Spec），`.claude/skills/auto-mcm/SKILL.md`、`.dsh/skills/
auto-mcm/SKILL.md`、`.agents/skills/auto-mcm/SKILL.md`（Codex）、`.opencode/
skills/auto-mcm/SKILL.md`（这次新增）是四个 runtime 各自的绑定（Binding）。
`scripts/` 下所有 Python 脚本零改动。

---

## 2. opencode 是什么（供理解绑定的背景）

[opencode](https://github.com/sst/opencode)（`sst/opencode`，MIT 授权）是一个
开源的终端编码 agent，多语言 README（26 种）说明其社区规模不小。核心用
TypeScript 写成，工具注册在 `packages/opencode/src/tool/`，每个工具是一个独立
文件（`Tool.define(id, ...)`），配套一个同名 `.txt` 文件放模型可见的工具说明
文案。

对本次适配最相关的两点：

1. **Skill/Agent/Command 三种配置文件分离，且路径和自己的仓库自举一致**——
   `sst/opencode` 自己的仓库里就有 `.opencode/skills/`（技能）、
   `.opencode/agent/`（子代理人格，frontmatter 支持 `mode`/`hidden`/`model`/
   `tools` 白名单黑名单）、`.opencode/command/`（slash command，支持
   `` !`shell命令` `` 语法在渲染时内联执行 shell 输出）。这次适配只用到 skill
   这一层。
2. **工具 id 和 Claude Code 高度重合**——语义和命名基本一一对应，是三个适配里
   工具映射最直接的一个（实测证实，见 §3）。

---

## 3. 工具映射表（全部 12 项已用真实任务验证，非文档推断）

| Claude Code | opencode 工具 id | 验证方式 |
|---|---|---|
| `Read`（载入 skill） | `skill` | 实测：载入 auto-mcm skill |
| `Read` | `read` | 实测：子代理读取文件内容 |
| `Bash` | `bash`（`shell.ts` 里 `ShellID.ToolID` 常量） | 实测：执行 `pipeline_manager.py status` |
| `TodoWrite` | `todowrite`（**不是** `todo`，虽然源文件叫 `todo.ts`） | 实测：两项待办清单 + 逐项打勾 |
| `Write` | `write` | 实测：创建 `hello.txt` |
| `Edit` | `edit` | 实测：修改 `hello.txt` 内容 |
| `Glob` | `glob` | 实测：`*.txt` 匹配 |
| `Grep` | `grep` | 实测：搜索文件内容 |
| `Agent(description, prompt)` | `task` | 实测：委派子代理读文件并汇报（首次因跨目录访问触发工作区边界限制卡住，改成目录内任务后正常完成，见 §3.1） |
| `WebSearch` | `websearch`（实测走的是 Exa 提供商） | 实测：搜索 Python 3.13 发布日期 |
| `WebFetch` | `webfetch` | 实测：抓取 python.org 官方发布页确认日期 |
| `AskUserQuestion` | `question` | **工具名确认存在，但见 §3.1——headless 模式下无法真正问到答案** |

---

### 3.1 最重要的发现：`question` 在 `opencode run`（headless）模式下默认权限是 deny

用 `--print-logs --log-level DEBUG` 跑一次强制模型提问的任务，日志显示每个新建
session 的默认权限里明确包含：

```
permission=[{"permission":"question","pattern":"*","action":"deny"}, ...]
```

模型确实**尝试**提问（组织出了问题文本），但工具调用被权限系统挡下，没有留下
`question` 类型的工具调用记录，模型退化成把问题当成普通文字打印出来——**在
`opencode run` 单次任务模式下，没有人能在同一次运行里回答这个问题，这条 run
就卡在"问了但没人回"的状态，不会真正暂停等待**。

**这对 AutoMCM-Pro 的实际影响（务必写进 `.opencode/skills/auto-mcm/SKILL.md`
使用说明）：**

- 【唤醒协议】Step 2a（首次启动询问题目路径/数据位置/AP或MANUAL模式）依赖
  `question` 工具真正等到人类回复。**用 `opencode run` 跑首次启动会问不出来**，
  必须用交互式的 `opencode`（TUI）或 `opencode web` 来做首次启动这一步；
- 后续 AP 模式下的自评自批、以及 MANUAL 模式的逐阶段确认，同样需要交互式
  session 才能让 `question` 真正生效；
- 一旦首次启动、工作区已经 `init` 完成，后续某些**不需要人类介入的**阶段
  （比如 AP 模式下已经不需要再问什么、纯粹在推进流水线）理论上可以用
  `opencode run` 做单次调用，但只要流程中会走到需要 `question` 的分支
  （Checkpoint LA 就是一个例子——见 `AutoMCM_SOP.md` §9.2 第 4 条，这条规则
  明确不能自评自批），`opencode run` 就不适用，必须切回交互模式。

`.opencode/skills/auto-mcm/SKILL.md` 已经补充了这条使用限制。

### 3.2 `task` 的边界限制（附带发现，非 bug）

子代理委派的第一次测试指向了当前工作目录之外的绝对路径，`task` 调用卡在
`running` 状态直到超时；把目标换成当前工作目录内的文件后立刻正常完成（子代理
标注为 "Explore Agent"）。推测是工作区边界策略对子代理生效，跨目录访问会触发
一个同样等不到答案的权限确认。**结论**：opencode 上的子代理委派应尽量使用相对
路径 / 工作目录内路径，不要委派子代理去操作项目工作区之外的绝对路径。

---

## 4. 安装与运行前提

```sh
opencode          # 交互式 TUI（question 工具能正常工作，首次启动用这个）
opencode web       # 交互式 Web UI
opencode run "task"   # 单次任务模式（question 工具会卡住问不出来，见 §3.1，不要用来跑首次启动）
```

具体安装方式（npm/brew/curl 脚本）以
[opencode README](https://github.com/sst/opencode#readme) 当前版本为准，本次
未验证安装步骤本身（本机已预装 v1.18.18）。

---

## 5. 三个 Binding 的横向对比小结

| | dsh | Codex | opencode |
|---|---|---|---|
| Skill 发现路径 | `.dsh/skills/` | `.agents/skills/` | `.opencode/skills/` |
| 工具面宽度 | 宽（专用工具齐全） | 窄（重度依赖单一 shell 工具） | 宽（与 Claude Code 几乎一一对应，**唯一完整实测过的一个**） |
| 工具名与 Claude Code 相似度 | 中（多数改名，如 `ask_user_question`） | 低（哲学不同，非一一对应） | 高（`task`/`read`/`write`/`glob`/`grep` 同名或近似） |
| 常驻子 Agent 追问能力 | 有（`send_message`/`list_agents`），一等公民 | 有多代理模块但细节未核实 | `task` 是一次性委派；headless 下 `question` 权限默认 deny，交互模式下未知细节 |
| 内置网络检索 | 有（`web_search`/`web_fetch`） | **无**，需自配 MCP | 有（`websearch`/`webfetch`，实测走 Exa） |
| 验证程度 | 文档验证，未执行 | 文档验证，未执行 | **已完整执行验证**（本文件） |

dsh 和 Codex 仍停留在"文档验证"，落地前需要按各自 `*_INTEGRATION.md` 末尾的
【验证步骤】在真实环境跑一遍——opencode 这次的经验（`question`/`task` 的
headless 权限行为）说明单靠读源码推断工具名是不够的，权限/运行模式这类只有
真跑一遍才会暴露的问题，dsh/Codex 落地时也应该同样留意。
