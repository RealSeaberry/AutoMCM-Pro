# DeepSeek Harness (dsh) 绑定说明

> 状态：**已完整执行验证（含跨 profile 排查、常驻子 Agent 全链路）**（2026-08-23，
> `npx @deepseek-ai/dsh@0.1.1-rc.2`，模型 `deepseek-v4-flash` via
> `deepseek-official` provider）——§3 表格里能测的工具全部用真实任务跑过，逐一
> 解压 `.dsh/sessions/**/session.jsonl.zstd` 核对结构化 `tool/call` 事件，不是
> 模型自述。
>
> **结论已修正（比最初判断更明确）：`ask_user_question` 和 `web_fetch` 不是
> "headless 独有的限制"，而是这个 dsh 版本（0.1.1-rc.2）随附的两个默认 profile
> 模板——`headless` 和 `web`——**都**没有把这两个工具接进默认插件树**。用
> `dsh --profile web --dump-config` 和 `dsh --profile headless --dump-config`
> 逐行比对完整插件清单（500+ 行）得到的证据：两份清单里都没有
> `tool-ask-user`（`ask_user_question` 的来源包）、也没有任何 web-fetch provider
> 包；`web` profile 里虽然有 `user-questions`/`ui-user-questions` 这两个
> **人类 UI 层**的问答基础设施，但**没有把它暴露成模型可调用的工具**——也就是说
> 人可以在 Web UI 里被问问题，但模型自己没有"主动发起提问"这个工具可用。第三个
> 可能的 profile `tui` 在这个版本里**不是预装的**（要手动
> `dsh plugin --profile tui add <package>` 建，本次没有另外建来测）。详见 §3.1。
>
> **落地过程中遇到并解决的真实环境问题（记录供他人参考）**：
> 1. DSH 硬性要求 `node ^22.19 || >=24`；Node 20 下会在插件加载阶段连环报错
>    （`node:zlib` 缺 `createZstdDecompress`、`Promise.withResolvers is not a
>    function`、`node:module` 缺 `stripTypeScriptTypes`——这三个都是 Node 22+
>    才有的运行时能力，不是 dsh 的 bug，报错信息本身具有一定误导性，容易让人
>    以为是 dsh 或网络问题）。用 `nvm install 22 && nvm use 22`（或
>    `conda install -c conda-forge "nodejs>=22.19"`）解决。
> 2. 通过工具（本 Claude Code 会话的 Bash）调用命令的 shell 环境，和用户自己
>    交互式终端的 shell 环境即使在同一台机器上也可能解析到不同的 `node` 版本
>    （典型原因：`nvm` 的 PATH 注入只在交互式 shell 的 `.bashrc` 里生效，工具
>    调用的非交互 shell 不一定会 source 到）——需要显式
>    `export PATH="$HOME/.nvm/versions/node/vX.Y.Z/bin:$PATH"` 才能让子进程用
>    对版本。这不是 dsh 特有的问题，任何用 nvm 管理 Node 版本的场景都可能遇到。

---

## 1. 定位

延续 `LOS_ALAMOS_INTEGRATION.md` §1 定下的 Spec/Binding 分层：`AutoMCM_SOP.md`
（+ 可选的 `LOS_ALAMOS_DESIGN.md`）是工具无关的协议本体（Spec），`.claude/skills/
auto-mcm/SKILL.md` 是 Claude Code 的运行时绑定（Binding），
`.dsh/skills/auto-mcm/SKILL.md` 是这次新增的 **DeepSeek Harness 绑定**——三者
描述同一套流程，Spec 只写一份，Binding 按 runtime 各写各的工具调用语法。

`scripts/` 下的所有 Python 脚本（`pipeline_manager.py`/`quality_gate.py`/
`los_alamos/*.py`/`plot_style.py`……）**零改动**——它们都是被 `bash`/`Bash` 调用的
独立进程，哪个 coding agent 在跑无所谓。

---

## 2. DeepSeek Harness 是什么（供理解绑定的背景）

dsh 是 DeepSeek 于 2026-08-13 开源的 agent harness（`@deepseek-ai/dsh`，MIT
授权，Node.js，`node ^22.19` 或 `>=24`）。核心设计是"everything is a plugin"，
底层是一个叫 **Cordis** 的插件框架：模型适配器、工具注册表、会话日志、agent loop
本身都是可替换插件，通过 `ctx.<key>` 的服务发现机制互相协作，没有"特权核心"。

对本次适配最相关的两点：

1. **Skill 发现机制和 Claude Code 几乎同构**——本地文件 provider
   （`@deepseek-ai/dsh-skill-filesystem`）按固定优先级扫描
   `<project>/.dsh/skills`（rank 100，**我们用的就是这一层**）、
   `<project>/.agents/skills`（rank 200，次优先级）、自定义目录、用户级目录，
   识别 `<name>/SKILL.md`（目录 bundle）或 `<name>.md`（单文件）。Frontmatter 是
   YAML，必填 `name`（kebab-case）和 `description`，可选 `whenToUse`/`metadata`/
   `disable-model-invocation`/`user-invocable`——比 Claude Code 多两个调用策略
   开关，核心字段完全对应。
   > **命名坑（已避开）**：`.agents/skills` 这个路径不是 dsh 独有的——OpenAI Codex
   > CLI 文档确认的 skill 发现路径**也是** `.agents/skills`（仓库根向上找到
   > `.git` 为止）。如果 DSH 绑定放在 `.agents/skills/auto-mcm/`，Codex 会读到
   > 同一个文件，但里面写的是 dsh 专属工具名（`ask_user_question`/`subagent`/
   > `web_search`……），Codex 找不到这些工具会报错。所以这次改用 dsh 自己更高
   > 优先级、不与其他 runtime 共享的 `.dsh/skills/` 路径，把 `.agents/skills/`
   > 留给 Codex 绑定（见 [`CODEX_INTEGRATION.md`](./CODEX_INTEGRATION.md)）。
2. **子 Agent 能力比 Claude Code 更细分**——`dsh-tool-subagent` 提供一次性委派
   （对应 `Agent()`），`dsh-tool-subagent-control` 额外提供 `send_message`/
   `list_agents`/`interrupt_agent`，用于**常驻、可持续追加指令**的子 Agent，这是
   一等公民 API，不是变通实现。

---

## 3. 工具映射表（与 `.dsh/skills/auto-mcm/SKILL.md` 同步维护，改一处务必两边同改）

| Claude Code | dsh 工具名 | 核对状态 |
|---|---|---|
| （载入 skill） | `skill` | ✅ 实测：headless 加载 auto-mcm |
| `Bash` | `bash` | ✅ 实测：执行 `pipeline_manager.py status`、版本检查等 |
| `TodoWrite` | `todo_write` | ✅ 实测：两项待办清单 + 逐项打勾 |
| `Write` | `write` | ✅ 实测：创建 `hello.txt` |
| `Edit` | `edit` | ✅ 实测：修改 `hello.txt` 内容 |
| `Glob` | `glob` | ✅ 实测：`*.txt` 匹配 |
| `Grep` | `grep` | ✅ 实测：搜索文件内容 |
| `Agent(description, prompt)` | `subagent` | ✅ 实测：委派子代理读文件并汇报 |
| `WebSearch` | `web_search` | ✅ 实测：搜索 Python 3.13 发布日期 |
| `Read` | `read` / `read_image` | ✅ `read` 实测（子代理读取任务）；`read_image` 未测试 |
| `AskUserQuestion` | `ask_user_question` | ❌ **`headless` 与 `web` 两个默认 profile 都未挂载此工具**，见 §3.1 |
| `WebFetch` | `web_fetch` | ❌ **`headless` 与 `web` 两个默认 profile 都未挂载 fetch provider**，见 §3.1 |
| （常驻可追问的子 Agent） | `subagent`（`run_in_background: true`）+ `send_message` / `list_agents` / `interrupt_agent` | ✅ 实测：创建后台子代理→追加消息→查状态→中断，全部跑通，见 §3.3 |

### 3.1 最重要的发现：两个默认 profile 模板都没接 `web_fetch`/`ask_user_question`，不是 headless 独有的限制

从某次 headless 请求的 `request/header.tools` 字段拿到的**权威、完整**工具清单
（不是文档推断）：

```
bash, create_goal, edit, exit_plan_mode, get_goal, glob, grep, interrupt_agent,
job_kill, job_list, job_output, list_agents, ralph, read, read_image,
send_message, skill, str_replace_editor, subagent, subagent_fork, todo_write,
update_goal, web_search, workflow, write
```

（`ralph`/`workflow`/`str_replace_editor`/`subagent_fork`/`*_goal`/`job_*` 是
`docs/tool-catalog.md` 里记录过、但本次适配没有对应到 Claude Code 工具、原设计
没用上的额外工具，先按下不表。）

**最初以为是 headless 的限制，后来用 `--dump-config` 逐行比对 `web` profile 的
完整插件树（500+ 行）才发现结论要修正**：`dsh --profile headless --dump-config`
和 `dsh --profile web --dump-config` 两份配置里都**没有 `tool-ask-user`
（`ask_user_question` 的来源包），也没有任何 web-fetch provider 包**。`web`
profile 里有 `user-questions`/`ui-user-questions` 两个插件，但那是给**人类在
Web UI 里被问问题**用的基础设施（比如批准/确认对话框），**没有把这个能力包装成
模型可调用的工具**——模型自己没有"主动发起提问"这个选项，跟 headless 是同一个
结论。第三个可能的 profile `tui` 在这个版本**不是预装的**（提示 "profile 'tui'
does not exist; create it with 'dsh plugin --profile tui add <package>'"），
本次没有额外建来测。

**两个具体现象、两种不同的"问不出/抓不到"（headless 下观察到的行为，web
profile 配置层面结论相同但未做同等的行为级实测）：**

- **`ask_user_question` 直接不在工具清单里**——不是被权限挡下（跟 opencode 那次
  不一样，opencode 的 `question` 工具确实挂载了，只是权限 deny），dsh 这边模型
  拿到的工具 schema 里根本没有这个选项。强制要求模型提问时，模型自己判断出
  "没人能答"，直接把问题写成一段纯文字回复，**没有任何工具调用记录**（`tool/
  call` 事件类型完全没出现在那次 session 里）。
- **`web_fetch` 同样不在工具清单里**——第一次自然任务（"打开一个网页确认日期"）
  时，模型自己选了 `bash` + `curl` 去抓页面（还因为 gzip 压缩绕了一圈：下载下来
  发现是压缩内容，用 `read` 检查、确认是 gzip 后再用 `bash` 里的 `gzip -dc`
  解压）；第二次显式禁止 bash/curl、明确要求用"webfetch 专用工具"时，模型直接
  在回复里说"如果你需要页面精确全文…需要在一个提供 webfetch 工具的环境中操作"
  ——模型自己承认拿不到这个工具，最终只基于 `web_search` 的搜索片段给了摘要，
  没有抓取原文。

**这对 AutoMCM-Pro 的实际影响（结论比最初更明确，不是"换个 profile 就好"）：**

- `AutoMCM_SOP.md` 硬性要求"文献调研结果（至少 5 篇）"——`web_search` 能用，
  但需要**打开某篇具体文献的网页读取全文**时，这个 dsh 版本的两个默认 profile
  都做不到，只能走 §【headless profile 的重要限制】里写的 `bash`+`curl`
  正式 fallback，不是"换个 profile 就解决"；
- `AskUserQuestion` 等价物在这个 dsh 版本里**两个默认 profile 都不可用**，跟
  opencode 的结论方向一致（虽然失败机制不同）：**首次启动的用户问答环节、
  MANUAL 模式的逐阶段确认、Checkpoint LA 的强制人类终审，目前在任何一个默认
  profile 下都做不到**，需要按 SKILL.md 里"一次性把信息塞进任务指令"的协议
  改法处理，或等 dsh 后续版本把 `tool-ask-user` 接进默认 bundle；
- `send_message`/`list_agents`/`interrupt_agent` 这三个"常驻子 Agent"工具名
  虽然出现在 headless 的工具清单里，但 headless 本身是"答一个任务就退出"的
  一次性运行模式，这类工具在这种模式下能不能真正发挥"常驻可持续追问"的价值，
  存疑，需要在交互式 profile 下另测。

`.dsh/skills/auto-mcm/SKILL.md` 已经补充了这条使用限制。

### 3.2 已知会因部署 profile 不同而变化的地方

- §3.1 的 25 个工具清单是 `headless` profile 的**行为级**实测结果（真的跑任务、
  解压 session 日志核对）；`web` profile 用 `--dump-config` 做了**配置级**核对
  （比对插件树里有没有 `tool-ask-user`/fetch provider 包），两种方法结论一致
  （都缺这两个工具），但 `web` 没有做等同 headless 的行为级验证（web 是长驻
  server，不像 headless 能一次性拿到完整 session 日志，需要走 API/前端才能测
  行为，这次没做）；
- `dsh --profile <name> --dump-config` 是比"跑一个任务再看日志"更快的核对方式，
  不需要真的花模型调用成本，适合先做一轮快速排查，再挑需要深入的地方做行为级
  实测；
- 这个结论只对**这次实测的 dsh 版本（0.1.1-rc.2，developer preview，仓库自己
  标注兼容性可能变化）**有效，版本升级后 `tool-ask-user`/fetch provider 有可能
  被加进默认 bundle，建议重跑一遍 `--dump-config` 核对。

### 3.3 常驻子 Agent（`send_message`/`list_agents`/`interrupt_agent`）实测通过，关键在 `subagent` 的 `run_in_background` 参数

`subagent` 工具本身带一个 `run_in_background`（boolean）参数，这个参数在
`docs/tool-catalog.md` 里有记录，但之前没意识到它是"一次性 vs 常驻"的开关，这轮
连续跑了两次任务才摸清楚：

- **`run_in_background: false`（或不传）** → 同步执行，工具调用直接返回最终文字
  结果，**不产生可追踪的 id**，`list_agents` 查不到，`send_message` 对它无效
  （实测：模型自己编了一个不存在的 id 去发消息，报错
  `Error: subagent "xxx" is unavailable`）；
- **`run_in_background: true`** → 异步执行，工具调用立刻返回
  `started subagent <id>`，这个 id 才是**真正可持续追问**的子代理：
  `list_agents` 能查到 `[running]`/`[ready]` 状态、`send_message` 能给它排队
  下一轮任务、`interrupt_agent` 能中途叫停。

**实测过程**（供理解，不是操作步骤）：第一次测试里模型前两次调用 `subagent` 都没
传 `run_in_background: true`，两次都同步返回、白跑；第三次才传对，之后
`send_message`/`list_agents` 全部按预期工作，子代理状态从 `[running]` 正确转成
`[ready]`。第二次测试（专门测 `interrupt_agent`）模型一次就传对了参数，创建
后台子代理→立刻 `interrupt_agent`→返回 `interrupt requested for agent <id>`→
`list_agents` 显示 `[ready]`→系统追加一条"Background subagent ... was stopped
before it finished"通知，整条链路一次成功。

**结论**：`send_message`/`list_agents`/`interrupt_agent` 三个工具的调用行为
**已完整验证**，不是理论上存在而已；但 `.dsh/skills/auto-mcm/SKILL.md` 里
Los Alamos 相关的 Prompt 模板如果要用到这个能力（比如把 Alsos/Groves 做成真正
常驻的子 Agent），**必须显式传 `run_in_background: true`**，不能假设默认行为
是常驻的。

---

## 4. 安装与运行前提

与 Claude Code 绑定完全独立的一套依赖，两者互不冲突：

```sh
# Node.js ^22.19 || >=24，以及 dsh CLI
npx @deepseek-ai/dsh web          # 交互式 Web UI，默认 http://127.0.0.1:3080
npx @deepseek-ai/dsh --profile headless "task"  # 单次任务模式（零命令，类似 claude --print）
# 在克隆的 dsh 源码仓库内开发时用 pnpm dsh 代替 npx @deepseek-ai/dsh，两者等价
```

需要 `DEEPSEEK_API_KEY`（或部署自行配置的其他模型 provider）。Python 依赖
（`pdfplumber`/`scipy`/`numpy`/`matplotlib`/`pandas`/`openpyxl`）与 Claude Code
绑定共用同一条【依赖自检】命令，不需要重复配置。

---

## 5. 仍待验证的部分

1. `web` profile 的 `ask_user_question`/`web_fetch` 缺失结论目前只做了**配置级**
   核对（`--dump-config` 比对插件树），没有像 headless 那样做**行为级**实测
   （真的启动 `dsh web`、通过前端或 API 发一个任务、解压对应 session 日志核对
   `tool/call`）——web profile 是长驻 server，行为级测试需要额外走一层 API/
   前端，这次没做，理论上配置级证据已经足够确定结论，但没有闭环到行为级；
2. `tui` profile 这个版本没有预装，需要先 `dsh plugin --profile tui add
   <package>` 手动建，这次没建，不确定建出来会不会不一样；
3. dsh 目前是 developer preview（`0.1.1-rc.2`），版本升级后 `tool-ask-user`/
   web-fetch provider 有可能被加进默认 bundle，建议版本升级后重跑一遍
   `--dump-config` 核对，不要假设这次的结论长期有效。

`send_message`/`list_agents`/`interrupt_agent` 已经实测过（见 §3.3），不再列在
这里。

---

## 6. 与 issue #2（Codex 适配提案）的关系

issue #2 里 kyrie21z 提议的结构是"新增独立的 `AutoMCM_SOP_CODEX.md` +
`.codex/skills/auto-mcm/`，尽量复用 `scripts/`/`templates/`"。这次 DSH 绑定用了
更精简的做法——**没有新建 `AutoMCM_SOP_DSH.md`**，因为核查后 `AutoMCM_SOP.md`
本身已经是工具无关的（唯一一处 `WebSearch`/`WebFetch` 字样已改成通用表述），
不需要复制一份。

Codex 绑定在同一轮迭代里也做了（见 [`CODEX_INTEGRATION.md`](./CODEX_INTEGRATION.md)），
同样没有新建 SOP 分支——但目录不是 issue #2 提议的 `.codex/skills/`，而是
Codex 官方文档（`developers.openai.com/codex/skills`）实测确认的 `.agents/skills/`
（仓库根向上找 `.git`）。`.codex/skills/` 是 issue 提案时的合理推测，但 Codex
实际没有走这条路径；这次按官方文档订正了，避免落地后发现目录选错、skill 根本没被
发现。
