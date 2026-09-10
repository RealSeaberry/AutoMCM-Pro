# LeanGate — Lean 4 形式化验证 Addon 设计

> 状态：v0.3.1 已实现
>
> 更新：2026-09-11
>
> 适用项目：AutoMCM-Pro v0.3.1 及后续版本

## 1. 定位

LeanGate 是 AutoMCM-Pro 的可选 Lean 4 形式化验证 Addon。它为适合
形式化的关键数学结论提供由 Lean 内核裁决的独立验证通道。

LeanGate 不替代：

- Python、SciPy、OR-Tools 等建模和求解工具；
- `verify_*.py` 数值验证、交叉求解和灵敏度分析；
- 数据真实性、经验假设、现实适用性和价值判断的人工审查。

它只证明：在已登记的形式化定义与假设下，目标结论可由 Lean
内核检查通过。不得将局部定理的通过表述为“整个模型或论文已被证明正确”。

```text
数据 / 题意 / 假设 ──建模──▶ Python 求解结果
       │                         │
       └──规格化──▶ Lean 定义  └──精确证书──▶ Lean 证明
                                                   │
                                                   ▼
                                         Lean 内核 + 公理审计
```

## 2. 最适合 LeanGate 的内容

### 2.1 高价值对象

- 可行性：容量、覆盖、互斥、非负性和边界条件；
- 守恒与不变量：流量守恒、资源总量、状态转移不变式；
- 精确代数性质：恒等式、不等式、单调性、范围与界；
- 模型变换：变量替换、归一化、缩放、单位换算和归约等价性；
- 证书检查：资源分配、网络流、调度、最短路等候选解的精确证书；
- 决策关键安全条件、收敛前提和可机检的风险边界。

### 2.2 不应由 LeanGate 单独裁决的内容

- 原始数据是否真实、完整、具有代表性；
- 题意理解和现实世界因果关系是否正确；
- 统计估计、浮点轨迹或随机模拟的经验有效性；
- 权重、政策偏好和价值选择是否合理；
- 大规模黑箱求解器的完整内部实现。

这些内容仍应由数据检查、文献、Python 验证、红队分析和人工判断处理。

## 3. 启用策略

LeanGate 默认关闭，支持三种策略：

| 策略 | 行为 |
|---|---|
| `off` | 不创建形式化门禁，保持 v0.3.0 行为 |
| `selected` | 对已登记且标记为 `ELIGIBLE` 的声明执行门禁 |
| `required` | 每个问题必须至少有一项预先人工批准的 required 义务，并对这些义务执行门禁 |

```bash
python scripts/setup_workspace.py --lean-policy selected
python scripts/pipeline_manager.py init --mode AP --contest cumcm --lean-policy selected
python scripts/leangate.py --workspace CUMCM_Workspace init --policy selected
```

## 4. 声明与证据模型

每项形式化声明必须登记在 `formal/claims.json`，至少包含：

- 稳定的 claim ID 和所属子问题；
- 声明类型与适用性分类；
- Lean 规格、定理和源文件；
- 显式假设、数据边界和证明范围；
- 如为证书声明，必须绑定精确的 JSON 证书文件；
- 规格语义审查、冻结状态与新鲜度摘要；
- 证明状态、保证级别、验证快照和错误原因；详细审计结果写入 `reports/`。

```text
CUMCM_Workspace/formal/
├── claims.json
├── lean-toolchain
├── lakefile.toml
├── lake-manifest.json
├── LeanGate.lean
├── LeanGate/
├── Specs/
├── Proofs/
├── Certificates/
├── reports/
├── schemas/
└── snapshots/
```

## 5. 流水线集成

### 5.1 问题分析

离开 `problem_analysis` 前，对每个子问题完成形式化适用性分类并封存。
安全性、可行性、守恒律、不变量、收敛性、证书和决策关键风险类声明
会触发强制形式化。未完成分类时，`pipeline_manager.py advance` 拒绝推进。

### 5.2 规格审查与冻结

Lean 内核只能检查“定理是否由形式规格推出”，不能自动保证规格忠实于
题意。因此规格在证明前必须经过语义审查并冻结。冻结后任何定义、假设、
证书或证明文件变化都会使旧证据失效。

### 5.3 求解与证书

Python 继续负责数值计算和搜索。适合证书验证的结果需转换为精确数据，
并在 `scaling_policy` 中记录数值如何被缩放为精确整数。LeanGate 不默认把
浮点值当作精确实数；若使用舍入或误差界，需由新的证书 schema 另行显式定义。

v0.3.1 内置的端到端案例是可分资源分配：Python 生成精确 JSON 证书，
Lean 检查非负性、容量、总量和目标值等性质。

### 5.4 验证与门禁

LeanGate 重新执行：

1. 声明 schema、路径安全、禁止词和不安全逃生口检查；
2. 规格、证明、证书、项目配置与批准证据的新鲜度检查；
3. Lean 编译；
4. `#print axioms` 公理审计；
5. 声明范围、证书摘要和审查状态核对。

当 LeanGate 已启用时，`model_N_verify` 阶段不能仅依赖 Agent 撰写的 PASS
文本。`pipeline_manager.py advance` 会调用 `quality_gate.py formal`，失败则拒绝推进。

### 5.5 论文与导出

论文只能引用已通过且未过期的声明，并必须同时说明假设和证明范围。
导出包包含工具链与 Lake 配置、声明清单、Lean 源码、证书、审计报告和
`checksums.json`；复现时使用本文的 `lake build` 命令。

## 6. 命令接口

```bash
python scripts/leangate.py doctor
python scripts/leangate.py --workspace CUMCM_Workspace init --policy selected
python scripts/leangate.py --help
# doctor, init, generate-resource, register, seal-assessment,
# semantic-review, require, freeze, verify, audit, status, export

python scripts/quality_gate.py formal --problem-n 1
python scripts/quality_gate.py all --stage model_1_verify --problem-n 1
python scripts/quality_gate.py launch-check
```

形式化报告应同时提供人类可读结果与程序可解析的 JSON。
任何一项必要检查失败时，总状态必须为 FAIL。

## 7. 信任边界与安全规则

最小可信基础由固定版本的 Lean 工具链、Lean 内核、本地声明源码和
LeanGate 的非 LLM 门禁脚本组成。Agent 可生成证明，但不得自行宣布通过。

LeanGate 拒绝：

- `sorry`、`admit`、`unsafe` 和被声明审计捕获的自定义公理；
- 通过 `#print axioms` 发现的任何已使用且不在白名单中的公理；
- 不可解析的公理报告；
- 路径穿越与符号链接的 Lean 输入、目录或 `.lake`；
- 未绑定精确证书文件的 certificate 声明；
- 过期的语义审查、冻结摘要或验证报告；
- 声明、义务注册表和证明范围的未授权修改。

规格、证明、证书、Lean 配置、claim 范围、适用性分类和批准证据均参与
新鲜度摘要。任一输入变化都必须重新编译、审计和冻结，不得复用旧 PASS。

## 8. Lean 项目与可复现性

```text
addons/leangate/
├── lean-toolchain
├── lakefile.toml
├── lake-manifest.json
├── LeanGate.lean
├── LeanGate/Core/
├── LeanGate/Examples/
└── schemas/claims.schema.json
```

v0.3.1 固定工具链为 `leanprover/lean4:v4.32.0`。当前核心示例仅依赖 Lean
标准库，使用精确整数，避免未声明的浮点语义。

```bash
cd addons/leangate
lake build
```

## 9. 安装、更新与卸载

LeanGate 是可选依赖，不得静默安装。

```bash
bash install.sh --with-lean
bash install.sh --with-python-deps --with-lean
bash update.sh
bash uninstall.sh
# 仅当回执证明工具链由本安装器创建时才允许：
bash uninstall.sh --purge-toolchain --yes
```

每个新的 Agent 会话首次触发 AutoMCM Skill 时，应询问是否准备核心
Python 依赖和可选 LeanGate。询问前不预扫描、不联网安装；用户拒绝后
同一会话不再询问。Headless 运行时显示问题并暂停，不自行选择。

## 10. 验收标准

- 固定工具链下 `lake build` 成功；
- 至少一个 Python 证书到 Lean 内核检查的端到端案例；
- 失败证明、禁止词、已使用的非白名单公理、符号链接和过期证据被拒绝；
- `selected` 和 `required` 策略下的阶段门禁不可由 PASS 文本绕过；
- 导出前重新执行编译和公理审计；
- 安装、更新和卸载不损坏用户管理的 Lean 工具链；
- 无 Lean 环境时返回可操作的诊断，而不是伪造验证成功。

## 11. 扩展边界

后续应优先增加可复用的精确证书检查器和模型变换定理，而不是试图
形式化整个求解器或所有经验模型。新模板必须同时定义：

- 输入语义与精度策略；
- 可检查的定理和明确假设；
- Python 证书格式与 Lean 解码边界；
- 失效条件、公理白名单与回归测试；
- 论文中允许引用的最大结论范围。
