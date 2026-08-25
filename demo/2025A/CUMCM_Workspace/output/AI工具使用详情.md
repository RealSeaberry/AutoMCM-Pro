# AI 工具使用详情

## 一、所用 AI 工具名称和版本

- 工具名称：AutoMCM-Pro (DeepSeek Harness 绑定)
- 版本/型号：SOP v2.1 / dsh 0.1.1-rc.2
- 开发机构/公司：AutoMCM-Pro 流水线 Agent
- 使用日期：2026-08-25

## 二、具体使用目的和环节

本次任务为 CUMCM（全国大学生数学建模竞赛）建模全流程，AI 工具参与的环节包括：

- 问题分析/文献调研
- 数据预处理
- 建模与验证（model_* 各阶段）
- 灵敏度分析
- 论文写作
- 最终编译

流水线模式：AP；子问题数：3。

## 三、关键交互记录

以下摘自 `CUMCM_Workspace/memory/worklog.md`（完整记录见该文件原文，此处摘录
用户消息与关键决策/推进节点，门控逐条 PASS/FAIL 明细从略）：

```
[2026-08-25 12:23:17] [用户] 验收测试(第二次)：按 README Demo 重跑 2025 CUMCM A 题完整流水线至 final_compile，重点验证 §17.4 附录代码节选与正文页数控制；题目在 CUMCM_Workspace_seed_data/A题.pdf，结果模板 result*.xlsx，AP 模式，problems=3 归并 5 个子问题
[2026-08-25 12:23:17] [Agent] 唤醒协议：工作区已初始化(AP/CUMCM/A/3 problems/--git)；未检测到时间紧迫信号，判定不触发 Skunk Works，按全套严谨模式执行
[2026-08-25 12:23:47] [Agent] Los Alamos 触发判定(题目复杂度初判)：本题为确定性轨迹几何优化，物理模型唯一(视线遮挡+弹道运动学)，不同求解器属实现细节而非范式分歧，不触发路径C探索层；Skunk Works 不触发(无时间紧迫信号)
[2026-08-25 12:26:55] [Agent] problem_analysis → approved，推进至 data_preprocessing
[2026-08-25 12:28:38] [Agent] data_preprocessing → approved，推进至 model_1_build
[2026-08-25 12:46:26] [Agent] model_1_verify → approved，推进至 model_2_build
[2026-08-25 13:05:49] [Agent] model_1_build → approved，推进至 model_1_verify
[2026-08-25 13:05:49] [Agent] model_2_build → approved，推进至 model_2_verify
[2026-08-25 13:05:58] [Agent] model_1_verify → approved，推进至 model_2_build
[2026-08-25 13:05:58] [Agent] model_2_build → approved，推进至 model_2_verify
[2026-08-25 13:06:20] [Agent] model_2_verify → approved，推进至 model_3_build
[2026-08-25 13:18:27] [Agent] model_3_build → approved，推进至 model_3_verify
[2026-08-25 13:18:55] [Agent] model_3_verify → approved，推进至 sensitivity_analysis
[2026-08-25 13:19:57] [Agent] sensitivity_analysis → approved，推进至 latex_draft
[2026-08-25 13:20:04] [Agent] Kaizen 自评 问题1 均分3.75 ROUND_RECOMMENDED，最弱：假设合理性：点-线段视线判据与无风/无阻力弹道为竞赛级简化
[2026-08-25 13:20:04] [Agent] Kaizen 自评 问题2 均分3.75 ROUND_RECOMMENDED，最弱：假设合理性：多弹共用航向速度限制了三弹时间链的进一步拉长
[2026-08-25 13:20:04] [Agent] Kaizen 自评 问题3 均分3.75 ROUND_RECOMMENDED，最弱：假设合理性：Q5 贪心分配为启发式，不保证全局最优
[2026-08-25 13:20:09] [Agent] Kaizen 自评：3 个槽位均 3.75/5 → ROUND_RECOMMENDED；但按 SOP §13.3 时间预算是唯一闸门，任务未提供截止时间信息 → 直接放行进入 latex_draft，不主动开打磨轮（避免无谓消耗）；最弱维度均为假设合理性（竞赛级简化，已在论文局限性中如实讨论）
```

## 四、采纳和人工修改情况

本次流水线为 AP（AI 主导）模式：AI 在各 Checkpoint 自评自批、自动推进，人工的实质介入仅限于任务发起时的初始参数配置（题目、竞赛类型、模式选择）；过程中无人工中途介入（Andon 未被拉下）。凡触发 Los Alamos 探索层两轨冲突（Checkpoint LA）等按规则必须真人终审的环节，如实执行情况见 worklog.md 与 human_intervention.md 原始记录，不做美化。

---

*本文档由 `scripts/ai_usage_doc.py` 根据 `worklog.md` 自动生成，
依据《全国大学生数学建模竞赛人工智能工具使用规定（2025年试行）》第七条要求。*
