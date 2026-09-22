# 当前状态

更新：2026-09-22。Phase 0 / Phase 1 工程验证已完成；用户独立讲解尚待教学验收。

## 已完成

- 保留远端历史、旧学习源码与测试；原 5 个 Python 文件和测试文件 SHA-256 仍一致。
- Pydantic Plan、TaskStep、AgentState、Observation、工具契约和阶段报告。
- 独立 Planner / Executor / Workflow，2–4 步有界执行。
- LLM Service、DeepSeek Adapter、Fake Provider；坏输出最多修复一次，模型传输默认最多重试一次。
- 两个工具：固定文件名的 Profile Reader，以及 sample / Remotive 公开岗位来源搜索。
- 明确错误、基本 Trace、有限工具恢复、CLI 与合成故障演示。
- 新架构 73 项离线测试、旧代码 7 项测试全部通过。
- DeepSeek + 真实公开岗位缓存的 CLI 全流程通过；不同来源和验证边界分别记录。

## 分阶段状态

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 0 | 现状、保留边界、架构、项目计划 | PASS |
| Phase 1 | Schema、State、Planner、Executor、2 Tools、workflow、LLM、CLI | PASS（工程）；讲解验收 NOT_RUN |
| Phase 2 | 岗位全文/结构化抽取、统计、Gap、7 天计划 | NOT_IMPLEMENTED |
| Phase 3 | 独立 Verifier、自动换源、完整 Trace、写入 approval | NOT_IMPLEMENTED（已有基础错误/重试/Trace） |
| Phase 4 | FastAPI | NOT_IMPLEMENTED |
| Phase 5 | 前端 | NOT_IMPLEMENTED |
| Phase 6 | 完整求职演示与复盘 | 未完成；阶段 README/测试/学习交接已具备 |

## 真实验证究竟证明了什么

2026-09-22 的受限 DeepSeek 请求成功产生合法 Plan，调用本地样例 Profile 和 Remotive 公开快照，返回 2 个去重岗位来源。快照于 09:34:29 UTC 从公开 API 获取，完整 CLI 使用其 6 小时缓存，不是每次查询都重新联网。

宽泛 `AI Engineer` 能匹配两条 Senior AI 岗位；精确 Junior 查询没有符合条件的数据，程序以 `NO_SEARCH_RESULTS` 明确失败。不能声称已经为初级求职者找到合适工作，也不能把本阶段输出称为完整市场分析或 7 天计划。

完整细节见 [验证记录](phase1-verification.md)，可重现的故障演示见 [demo-recovery.txt](demo-recovery.txt)。

## 下一步

按 [学习交接](learning-handoff.md) 先理解 Schema → LLMService → Workflow 三处代码，用一次运行解释状态与失败路径。然后再进入 Phase 2 的岗位提取与分析，不提前堆前端或框架。
