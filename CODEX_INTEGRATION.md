# OpenAI Codex CLI 绑定说明

> 状态：**部分执行验证**（2026-08-24，`codex exec`，codex-cli 0.146.0，
> ChatGPT 登录鉴权）——`.agents/skills/auto-mcm/SKILL.md` 被正确发现并读取，
> 喚醒協議 Step 1 執行成功。**但这次实测推翻了源码调研阶段的一个关键假设**，
> 见 §3.1。
>
> **落地过程实测的重要发现：Codex 模型侧只暴露一个叫 `exec` 的"代码模式"工具，
> 参数是一段 JavaScript，`exec_command` 是这段 JS 里才能调用的内部函数，不是
> 模型直接可调的顶层工具**。之前源码调研阶段从 `codex-rs/core/src/tools/
> handlers/*.rs` 里核对到的 `ToolName::plain("exec_command")` 字面量是真实存在
> 的，但那是底层 handler 的注册名，不代表模型 function-calling 时直接看到这个
> 名字——这是"读源码 vs 真的跑一次"最容易踩的一类坑，具体见 §3.1。

---

## 1. 定位

延续 `LOS_ALAMOS_INTEGRATION.md`/`DSH_INTEGRATION.md` 定下的 Spec/Binding 分层：
`AutoMCM_SOP.md`（+ 可选的 `LOS_ALAMOS_DESIGN.md`）是工具无关的协议本体（Spec），
`.claude/skills/auto-mcm/SKILL.md`、`.dsh/skills/auto-mcm/SKILL.md`、
`.agents/skills/auto-mcm/SKILL.md`（这次新增，Codex 用）是三个 runtime 各自的
绑定（Binding）——同一套流程，只是工具调用语法不同。

`scripts/` 下所有 Python 脚本零改动。

---

## 2. 这份绑定和 issue #2 原提案的差异（重要，务必读）

[issue #2](https://github.com/RealSeaberry/AutoMCM-Pro/issues/2) 里 kyrie21z 提议
Codex 入口放在 `.codex/skills/auto-mcm/`。这次实测查证 Codex 官方文档
（`developers.openai.com/codex/skills`，重定向到
`learn.chatgpt.com/docs/build-skills`）后发现：

> Codex 实际扫描的路径是 **`.agents/skills`**（仓库范围：cwd 向上找到仓库根；
> 另外还有用户级 `$HOME/.agents/skills`、admin 级 `/etc/codex/skills`、系统内置
> 四级），**不是** `.codex/skills`。Frontmatter 要求与 Claude Code 完全一致：
> 必填 `name` + `description`。

这不是 kyrie21z 提案的错——那是 issue 提出时（2026-07）的合理推测，Codex 当时
或许确实用别的路径，也可能是对 Claude Code 命名习惯的类比推测。这次是在
DeepSeek Harness 适配时顺带查证了官方文档才发现的。**`.agents/skills` 这个路径
同时被 dsh（次优先级 rank 200）和 Codex 共用**——这也是为什么 DSH 绑定改放到了
`.dsh/skills/`（dsh 自己的最高优先级路径），把 `.agents/skills/` 留给 Codex 用，
避免两边工具名不同却读同一个文件的冲突（详见 `DSH_INTEGRATION.md` §2 的坑记录）。

显式调用方式：Codex CLI 用 `$skill-name`（例如 `$auto-mcm`），ChatGPT 里用
`@skill-name`。

---

## 3. Codex 的工具哲学：窄而不是宽（而且比表面看到的更窄）

和 dsh/opencode/Claude Code 给每种操作分配专用工具（Read/Write/Edit/Glob/Grep/
WebSearch/WebFetch 各一个）不同，Codex 只给模型暴露极少数顶层工具，大部分能力
通过其中一个"代码模式"工具间接调用。

### 3.1 实测发现：`exec` 是"代码模式"工具，`exec_command` 是 JS 里的内部函数

解压 `~/.codex/sessions/**/rollout-*.jsonl`（Codex 的会话记录，JSONL 格式，不
压缩，比 dsh 的 zstd 压缩日志更好读）里的 `custom_tool_call` 事件，实测跑喚醒
協議 Step 1 时看到的真实调用是：

```
name: "exec"
input: "const r = await tools.exec_command({\"cmd\":\"python scripts/pipeline_manager.py status 2>/dev/null\",\"workdir\":\"~/projects/AutoMCM-Pro\",...});\ntext(JSON.stringify({exit_code:r.exit_code,output:r.output}));"
```

也就是说：模型 function-calling 时看到的顶层工具只有一个叫 `exec` 的东西，参数
是一段 **JavaScript 代码**；`tools.exec_command(...)` 是这段 JS 代码执行环境里
才能调用的异步函数，不是模型能直接在 function-calling 层面单独调用的工具。
之前源码调研阶段核对到的 `ToolName::plain("exec_command")` 字面量确实存在于
`codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`，但那是这个
内部函数在 handler 层的注册名，跟模型 function-calling schema 里实际看到的
顶层工具名是两回事——**读源码只能告诉你"这个能力存在"，不能告诉你"模型会用
哪一层接口去调用它"，这正是这次要实测而不是只读文档/源码的原因**。

同一次实测里，模型还用这套机制读取了 skill 文件本身：`tools.exec_command({cmd:
"sed -n '1,240p' .agents/skills/auto-mcm/SKILL.md", ...})`——**没有看到任何
"skill" 或 "load_skill" 类型的独立工具调用**，Codex（至少这次实测的配置下）
似乎把 skill 内容当成普通文件，让模型自己用 shell 命令读，不像 opencode/dsh
那样有专门的 `skill` 工具包一层。这与本文档最初依据源码推断的情况不同，已
在此修正。

### 3.2 尚未在这次实测中确认的部分

`apply_patch`/`view_image`/`update_plan`/用户输入请求/多代理协同这几个，源码里
确认过字面量或模块名存在，但这次的任务没有触发到文件编辑/看图/建 todo/问人类/
派子代理，**不知道它们是像 `exec_command` 一样被包进 `exec` 这个 JS 代码模式
工具里，还是作为独立的顶层工具直接暴露**。下次验证时应该设计专门触发这几类
操作的任务，用同样"解压 session jsonl 找 `custom_tool_call`/`function_call`
类型事件"的方法核实。

## 4. 工具映射表（`✅ JS 内部函数` 表示只能通过 `exec` 这个顶层工具的 JS 代码间接调用，不是独立顶层工具）

| Claude Code | Codex 工具 | 核对状态 |
|---|---|---|
| `Bash` | `exec`（顶层，JS 代码）→ `tools.exec_command(...)`（JS 内部函数） | ✅ 实测确认（§3.1，喚醒協議 Step 1 跑通） |
| （载入 skill） | 无独立工具，走 `exec` 里 `sed`/`cat` 读文件 | ✅ 实测确认（§3.1） |
| `Read`（文本） | 无独立工具，走 `exec` 里 `cat`/`sed` | ✅ 实测确认（同上，读 SKILL.md 本身就是这么做的） |
| `Glob`/`Grep` | 无独立工具，走 `exec` 里 `rg`/`find` | ⬜ 未直接测试，但机制推断同上 |
| `Write`/`Edit` | `apply_patch` | ⚠ 源码字面量确认，未测试是否为独立顶层工具还是走 `exec` |
| `Read`（图片） | `view_image` | ⚠ 源码字面量确认，未测试 |
| `TodoWrite` | `update_plan` | ⚠ 源码字面量确认，未测试 |
| `AskUserQuestion` | 用户输入请求工具（模块 `request_user_input`） | ⚠ 仅核对到模块名，未测试 |
| `Agent(description, prompt)` | 多代理协同工具（模块 `multi_agents`/`multi_agents_v2`） | ⚠ 仅核对到模块名，未测试 |
| `WebSearch`/`WebFetch` | **无确认到的第一方工具**，需自配 MCP | ❌ 见 §5 |

---

## 5. 已知能力缺口与应对

`AutoMCM_SOP.md` 硬性要求"文献调研至少 5 篇"（`problem_analysis` 阶段）以及
Los Alamos 探索层的 Alsos 情报组，都依赖网络检索能力。Codex 上这项能力**不是
开箱即用的**，需要用户自行配置支持网络搜索的 MCP server 才能满足这条硬性要求。
`.agents/skills/auto-mcm/SKILL.md` 里已经写明：确认没有检索能力时不得静默跳过，
必须在 Checkpoint①里如实告知用户"当前环境无网络检索工具"，交由人类决定。

---

## 6. 已完成与仍待验证

**已实测（2026-08-24，codex-cli 0.146.0）**：`.agents/skills/auto-mcm/` 被正确
发现，`codex exec` 单次任务模式跑通，喚醒協議 Step 1 成功执行并拿到正确的
`pipeline_manager.py status` 输出（退出码 0）。核对方式：解压
`~/.codex/sessions/**/rollout-*.jsonl`（JSONL，明文不压缩）里的
`custom_tool_call` 事件，不是只看 CLI 的人类可读输出。

**仍待验证**：

1. `apply_patch`/`view_image`/`update_plan`/用户输入请求/多代理协同——这几个
   要专门设计任务（写文件、看图、建 todo、需要人类确认、需要委派子任务）才能
   触发，确认它们是独立顶层工具还是也被包进 `exec` 的 JS 代码模式；
2. 网络检索能力（MCP 配置）——没有的话先决定要不要配，还是接受"本阶段建模
   假设未经文献交叉验证"这条降级路径；
3. `codex mcp`/`codex plugin` 子命令可以配置外部 MCP server/插件，如果要补上
   `WebSearch`/`WebFetch` 缺口，这是官方文档的路径，这次没有实际配置测试。

---

## 7. 参考资料

- [openai/codex](https://github.com/openai/codex)（Apache-2.0）
- [Codex Skills 官方文档](https://learn.chatgpt.com/docs/build-skills)
- [Codex AGENTS.md 官方文档](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
