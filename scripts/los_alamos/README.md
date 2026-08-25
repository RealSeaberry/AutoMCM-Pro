# Los Alamos 探索层 — addon 脚本包

实现 [`LOS_ALAMOS_DESIGN.md`](../../LOS_ALAMOS_DESIGN.md) 的可选执行层。**默认不参与
主流水线**——不调用这些脚本，AutoMCM-Pro（Project Apollo）的行为和之前完全一样。

## 架构原则：报文总线是唯一真相来源，其余都是可替换 addon

```
                     ┌─────────────────────────────────┐
                     │  bus.py — 消息总线（唯一真相来源） │
                     │  CUMCM_Workspace/state/messages/ │
                     │  problem{N}.jsonl                │
                     └────────────────┬──────────────────┘
              读/写 via append_message() / read_messages()
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼              ▼
 groves_monitor.py  adjudicate.py  hypothesis_tree.py  quality_gate.py  (未来的
 （预算/漂移监控）   （Track0/R/1/2） （树物化视图）    （硬性校验门控）   新 addon…）
```

每个 addon 只依赖 `bus.py` 提供的 `append_message()` / `read_messages()` 两个函数
读写状态，互相之间不直接调用彼此的内部实现（除了 `quality_gate.py` 复用
`adjudicate.red_team_verdict()` 这一处，因为门控 7 的语义本来就是"问 Track R 要一个
verdict"）。这意味着：

- **想换掉 Track 1 的算法**（比如换成别的 MCDA 方法而不是熵权-TOPSIS）？只改
  `adjudicate.py` 的 `entropy_weight_topsis()`，输入输出接口（JSON 决策矩阵 → 排名+
  分数）不变，其他脚本无感知。
- **想加一个新角色**（比如设计里提到过、暂未采纳的 Delphi 多轮收敛）？新建一个
  `delphi.py`，读写同一份 `messages.jsonl`，追加一个新的 `performative`，不需要改
  任何现有文件。
- **想临时关掉红队**？不调用 `adjudicate.py redteam` 和 `quality_gate.py red-team`
  即可，`hypothesis_tree.py` 的状态机在没有 `RED_TEAM_REPORT` 消息时，节点会一直停
  在 `verify_pass`——这是预期行为，不是 bug（决赛圈晋级本来就该卡在这里，直到有人
  显式决定"这次不做红队，手动 mark 成 in_tournament"）。

## 脚本一览

| 脚本 | 角色 | 是否需要 LLM |
|---|---|---|
| `bus.py` | 报文总线核心（envelope schema、校验、CLI 收发） | 否 |
| `groves_monitor.py` | Groves 自我状态监控（漂移比例/预算/回溯/红队破解率） | 否，纯脚本 |
| `adjudicate.py` | Track 0 筛选记录、Track R 红队记录、Track 1 熵权-TOPSIS、Track 2 投票+Copeland+分歧熵 | `entropy-weight`/`panel-entropy` 否；`screen`/`redteam`/`panel-vote` 的**判断内容**来自调用方 Agent，脚本只负责记账 |
| `hypothesis_tree.py` | 假设树/DAG 状态机的物化视图（重放消息日志） | 否 |

`quality_gate.py`（仓库根 `scripts/` 下，不在本目录）新增了 `message`/`ledger`/
`red-team` 三个子命令，复用本目录的 `bus.py`/`adjudicate.py`。

## 快速上手

```bash
# 1. Director 展开根节点下的第一层分支
python scripts/los_alamos/hypothesis_tree.py expand --problem-n 1 \
  --node-id N-P1-001 --assumption-id A-P1-T-01 --seed-paradigm T --depth 1

# 2. 筛选者（Track 0）给出裁定
python scripts/los_alamos/adjudicate.py screen --problem-n 1 --node-id N-P1-001 \
  --coherence 0.85 --plausibility 0.7 --novelty 0.9 --problem-alignment 0.95 \
  --verdict expand --rationale "延续排队论假设，兄弟分支都在做数据驱动路线"

# 3. Division 汇报建造/验证进度
python scripts/los_alamos/hypothesis_tree.py mark --problem-n 1 \
  --node-id N-P1-001 --state building --sender T-Division
python scripts/los_alamos/hypothesis_tree.py mark --problem-n 1 \
  --node-id N-P1-001 --state verify_pass --sender T-Division

# 4. Bletchley 红队复核
python scripts/los_alamos/adjudicate.py redteam --problem-n 1 --node-id N-P1-001 \
  --verdict survived --severity none --rationale "falsifiable_if 未触发，边界场景均正常"

# 5. quality_gate 校验后才允许进决赛圈
python scripts/quality_gate.py red-team --problem-n 1 --node-id N-P1-001

# 6. Track 1（决赛圈候选量化排序）
python scripts/los_alamos/adjudicate.py entropy-weight --problem-n 1 \
  --matrix-file decision_matrix.json

# 7. Track 2（评审小组两两比较，重复多次不同 judge/维度）
python scripts/los_alamos/adjudicate.py panel-vote --problem-n 1 \
  --judge-id judge-1 --candidate-a N-P1-001 --candidate-b N-P1-014 \
  --dimension physical_plausibility --preference A --rationale "..."
python scripts/los_alamos/adjudicate.py panel-entropy --problem-n 1

# 8. 汇总，产出 leaderboard，判断是否需要 Checkpoint LA
python scripts/los_alamos/adjudicate.py combine --problem-n 1

# 9. 全程报文格式校验（可随时跑，通常在每个 Checkpoint 前跑一次）
python scripts/quality_gate.py message --problem-n 1
python scripts/quality_gate.py ledger  --problem-n 1

# 10. Groves 巡检
python scripts/los_alamos/groves_monitor.py check --problem-n 1
```

`decision_matrix.json` 示例（Track 1 输入）：

```json
{
  "candidates": ["N-P1-001", "N-P1-014"],
  "criteria": {
    "robustness":    {"direction": "positive", "values": {"N-P1-001": 0.82, "N-P1-014": 0.65}},
    "residual":      {"direction": "negative", "values": {"N-P1-001": 0.12, "N-P1-014": 0.05}},
    "param_count":   {"direction": "negative", "values": {"N-P1-001": 5,    "N-P1-014": 9}}
  }
}
```

## 落地阶段

对应 [`LOS_ALAMOS_INTEGRATION.md`](../../LOS_ALAMOS_INTEGRATION.md) §6：本目录目前
覆盖 **Phase 0 + Phase 1** 的脚本面（消息总线、Groves、Track0/R 记录、Track1 完整
实现、Track2 完整实现、树的单层展开）。多层展开的 best-first 调度逻辑（DESIGN §8.6，
"读前沿状态 → 选动作"的循环）目前由 Director（主 Agent）在 `SKILL.md` 的 Prompt
指引下手动调用以上 CLI 完成，**尚未**封装成自动循环脚本——这是有意为之：调度策略
本身是 §0.1 定义的"弹性策略层"，不适合硬编码成脚本，应该保留由 Agent 临场判断。
