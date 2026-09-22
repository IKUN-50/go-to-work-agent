# Phase 0 audit

日期：2026-09-22。范围：既有 Agent 学习项目的原地升级；保留旧成果，在当前仓库新增职业 Agent。本文记录实施前的基线；基线审计自身不代替 Phase 1 运行验收。

实施后补记：Phase 0/1 工程已完成分层验收，新增 73 项测试与 7 项旧回归通过；6 个历史 Python/测试文件与原件 SHA-256 一致。完整结果与真实模型、缓存公开来源的边界见 [current-status.md](current-status.md)。以下基线审计保留，不回写为实施后的全部功能描述。

## 已有能力

- Python 工具模块与注册/分发；受限 AST 计算器、问候、目录内文件读取和聊天记忆。
- DeepSeek 工具调用循环、最大轮数、最近消息窗口及常见 API 错误处理。
- JSON 与 Pydantic 入门示例，包括 BaseModel、Literal、model_validate 和条件校验。
- 原主 Agent 的 7 项离线测试。仓库初始化时迁移副本已通过该测试集；它们不覆盖新职业 Agent。
- 既有本地练习网站和学习记录。题库不并入新运行时，本轮不新增前端。

## 保留与复用

`examples/learning_agent/` 保存历史代码与测试；原项目目录也保留。迁移时只复制源码、测试、依赖和安全配置样例，未复制私人聊天记忆、真实环境文件、机器配置或缓存。

| 旧成果 | 处理方式 | 理由 |
| --- | --- | --- |
| 受限 calculator 与工具参数检查 | 保留示例，可复用设计思路 | 计算不是 Phase 1 核心任务，不为工具数量接入新流程 |
| 工具调用、记忆与错误处理 demo | 保留为学习对照 | 已有学习价值，但聊天 memory 不是职业任务 State |
| Pydantic 练习 | 保留并用新 Schema 承接学习 | 从“校验后仍用字典”进到明确的业务对象契约 |
| 旧测试 | 独立运行 | 不让交互脚本进入新测试发现路径 |
| 历史 README/审查/环境记录 | 保留日期与历史属性 | 旧 OpenAI 结果、旧变量名和旧测试数字不代表新实现 |

`agent.py` 导入时创建客户端，`exercise.py` 和 `structured_output_demo.py` 含直接交互入口；不能把这些历史模块直接导入新运行时。

## 应重构的边界

1. 模型 SDK、厂商配置和响应格式集中到 LLM Service/Adapter，业务不创建 SDK Client。
2. 以 Pydantic Plan、TaskStep、State 和阶段结果替代自由文本控制流。
3. 工具输入输出与执行错误有统一契约，观察保留来源；执行和重试均有界。
4. 配置统一为 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。真实 Key 仅在 `.env`，版本库只有空 Key 的样例。
5. 旧长期学习路线换为功能驱动的阶段交付，不沿用已经过期的 45 天日历承诺。

## 缺失模块与本轮计划

Phase 1 新增 State、Planner、Executor、最小 workflow、CLI、统一 LLM Service、fake/DeepSeek 适配，以及两个只读工具 `read_profile`、`search_jobs`。

这次任务的闭环是：提出求职目标 → 生成经过校验的收集计划 → 读取技能资料与搜索来源 → 保存 observations → 返回明确的 Phase 1 收集结果。

后续仍缺岗位全文提取、技能聚合、Gap Analysis、7 天计划、独立 Verifier、完整 Trace 与恢复策略、正式导出 approval、FastAPI 及前端。基础错误处理/trace 先服务当前可运行性，不提前将后续阶段登记完成。

## 数据和验证边界

- sample 搜索使用 synthetic 合成样本，只用于演示和测试，不能引用为当前招聘市场事实。
- 可选 web 搜索使用公开岗位源，具体覆盖与时效限制见工具 warnings；岗位条目/摘要不等于已经读取并核验岗位全文。无明确初级证据时不能将 Senior 岗位算作 junior 命中。
- Profile 样例不冒充用户经过确认的完整能力评估；私人 Profile 不入仓、不写入执行日志。
- Schema 通过、工具成功、外部数据可信、用户本人掌握是不同结论。
- 离线测试、CLI 合成 demo、web 实际入口和真实 DeepSeek 请求分别验收。当前最终结果以 [current-status.md](current-status.md) 为准。

## 文档审计来源

已完整读取工作区 AGENTS、三份全局入口文件；项目管理 README/启动检查/任务/决策/聊天交接；范围及两份 Python 练习任务；历史路线；两个子项目 README；两份测试说明；迁移清单；前端与 Python 环境复盘。另核对本仓库 AGENTS、README 和 current-status。没有读取私人 memory.json、真实 .env 或环境清理的注册表备份。
