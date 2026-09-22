# Phase 1 learning handoff

本阶段只学五件事。工程实现和测试情况以 [current-status.md](current-status.md) 为准；这些材料不代表学习者已经独立掌握。

Phase 0/1 工程验收 PASS：73 项新测试、7 项旧回归与分层运行验证通过。用户解释验收 NOT_RUN。真实模型结合缓存公开来源只完成资料收集；精确 junior 目标的无结果被明确报告为失败。

| 必须会解释 | 为什么需要 | 代码在哪里 | 程序如何流转 | 面试官可能怎么问 |
| --- | --- | --- | --- | --- |
| Pydantic Schema 是内部数据契约 | JSON 语法合法仍可能字段错误 | `app/schemas/plan.py`、`report.py` | 模型文本 → 解析/校验 → Plan 对象 | 字典和模型对象有什么不同？Schema 能保证事实正确吗？ |
| State 是一次任务的运行记录 | 知道进度、结果和失败原因 | `app/agent/state.py`、`workflow.py` | 目标 → 计划 → 观察 → completed/failed | 步骤完成和任务完成有什么区别？ |
| Planner 与 Executor 各司其职 | 模型建议不能绕过工具约束 | `app/agent/planner.py`、`executor.py` | Plan → TaskStep → 输入校验 → 工具 → Observation | 模型提出了未知工具怎么办？ |
| LLM Service/Adapter 隔开厂商 | 换模型不重写业务，无 Key 也能测试 | `app/services/llm.py` 及适配模块 | 服务 → fake/DeepSeek → 原始响应 → 校验/有限修复 | fake 测试能证明什么，不能证明什么？ |
| 错误与来源有明确边界 | 防止无限重试或把样本当成事实 | `app/tools/`、`app/agent/executor.py` | 失败 → 记录 → 有限恢复/结束；成功 → 阶段结果 | 为什么 sample 成功不等于招聘调研完成？ |

## 按这个顺序看代码

1. 先看 Plan 的字段，预测缺一个必填字段时会发生什么。
2. 打开 workflow，用中文写下调用顺序。
3. 跟踪一次 read_profile，再跟踪一次 search_jobs。
4. 看 LLM Service 如何把坏输出变成安全错误或修复后的对象。
5. 阅读一条失败测试，解释它保护哪种真实风险。

下一次教学从第 1 项开始，每次一个概念、一个预测题和一个小改动。当前不补前端、FastAPI 或 LangGraph 的完整课程。

## 讲项目时必须说清

Phase 1 完成的是计划和资料收集闭环。sample 是 synthetic；web 使用公开岗位源，其条目/摘要不等于已核验岗位全文，覆盖与时效限制见工具 warnings。岗位抽取、统计、Gap 和 7 天计划属于 Phase 2；独立 Verifier、完整 Trace/恢复和正式导出 approval 属于 Phase 3。

仓库内置 Profile 是虚构样例，工具只读选定目录中的固定 `profile.json`；用户可用 `--data-dir` 选择不入仓的私人资料，标记 `sample: false`。自述数据不等于经过验证的实际能力。新流程执行经过 Schema 校验的 Plan，没有调用 Provider 原生 Tool Calling API。永久工具失败会明确结束任务，目前不会自动换来源。

从仓库根目录运行 `python -m app --provider fake --demo-recovery`，观察明确注入的坏 JSON 与工具超时如何先失败、有限重试后完成。`--json` 输出完整状态，含 `run_mode`，也可能含私人 Profile，不要将个人运行结果提交到仓库。
