# AI 工具使用详情

## 一、所用 AI 工具名称和版本

- 工具名称：DeepSeek Harness (AutoMCM-Pro)
- 版本/型号：0.1.1-rc.2 / AutoMCM-Pro dsh 绑定
- 开发机构/公司：DeepSeek
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
[2026-08-25 15:46:34] [用户] 用户发起 2020 CUMCM C 题《中小微企业的信贷决策》完整流水线演示：AP 模式、3 个子问题、真实附件数据（123/302 家 + 利率流失率），要求跑到 final_compile 产出可编译 PDF，并按要求执行 §18 画图前惯例调研、§17 格式合规、launch-check、worklog/文献核验/风格打磨全流程
[2026-08-25 15:49:57] [Agent] problem_analysis → approved，推进至 data_preprocessing
[2026-08-25 15:53:20] [Agent] data_preprocessing → approved，推进至 model_1_build
[2026-08-25 16:02:58] [Agent] model_1_verify → approved，推进至 model_2_build
[2026-08-25 16:04:23] [Agent] model_2_verify → approved，推进至 model_3_build
[2026-08-25 16:07:06] [Agent] model_3_verify → approved，推进至 sensitivity_analysis
[2026-08-25 16:08:29] [Agent] sensitivity_analysis → approved，推进至 latex_draft
[2026-08-25 16:08:32] [Agent] Kaizen 自评 问题1 均分4.00 PROCEED，最弱：PD 模型样本量小(123家/27违约), 特征选择可更系统
[2026-08-25 16:08:32] [Agent] Kaizen 自评 问题2 均分3.75 ROUND_RECOMMENDED，最弱：迁移前提(PSI 轻度偏移)与伪评级分层是主要假设
[2026-08-25 16:08:32] [Agent] Kaizen 自评 问题3 均分3.50 ROUND_RECOMMENDED，最弱：类别为行为代理、冲击系数为情景假设
[2026-08-25 16:08:39] [Agent] Kaizen 评估：P1 PROCEED(4.0)；P2(3.75)/P3(3.50) ROUND_RECOMMENDED。判断：pipeline.json 无截止日期字段、无 >48h 时间预算信息，按 SOP §13 直接放行不启动打磨轮；两个弱点（PSI 轻度偏移、类别为行为代理/冲击系数为情景假设）属数据固有约束，非模型代码可修，改由论文假设与局限章节显式交代（与 Kaizen 目标等价）
[2026-08-25 16:19:16] [Agent] latex_draft → approved，推进至 final_compile
[2026-08-25 16:19:29] [Agent] model_1_build → approved，推进至 model_1_verify
[2026-08-25 16:19:29] [Agent] model_2_build → approved，推进至 model_2_verify
[2026-08-25 16:19:29] [Agent] model_3_build → approved，推进至 model_3_verify
[2026-08-25 16:19:34] [Agent] model_1_verify → approved，推进至 model_2_build
[2026-08-25 16:19:34] [Agent] model_2_verify → approved，推进至 model_3_build
[2026-08-25 16:19:34] [Agent] model_3_verify → approved，推进至 sensitivity_analysis
```

## 四、采纳和人工修改情况

本次流水线为 AP（AI 主导）模式：AI 在各 Checkpoint 自评自批、自动推进，人工的实质介入仅限于任务发起时的初始参数配置（题目、竞赛类型、模式选择）；过程中无人工中途介入（Andon 未被拉下）。凡触发 Los Alamos 探索层两轨冲突（Checkpoint LA）等按规则必须真人终审的环节，如实执行情况见 worklog.md 与 human_intervention.md 原始记录，不做美化。

---

*本文档由 `scripts/ai_usage_doc.py` 根据 `worklog.md` 自动生成，
依据《全国大学生数学建模竞赛人工智能工具使用规定（2025年试行）》第七条要求。*
