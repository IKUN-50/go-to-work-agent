# Architecture

更新：2026-09-22。本文描述 Phase 1 的最小职业资料收集架构；阶段验收结果单列于 [current-status.md](current-status.md)。

## 主流程

```text
Goal
  ↓
Planner ───→ LLM Service ───→ Provider Adapter ───→ fake / DeepSeek
  ↓                 ↑            │
Pydantic Plan       └── 解析 + Pydantic 校验 + 有限修复
  ↓
Agent State
  ↓
Executor → read_profile / search_jobs
  ↓                │
Observation ←──────┘
  ↓
Phase 1 collection result / explicit failure
```

内部 Schema 属于项目，不属于厂商。Planner 产出经过验证的对象；Executor 只执行注册的只读工具，并保存工具观察与错误。

当前 Plan 限定 2–4 步：先读取一次 Profile，再进行 1–3 次岗位来源搜索；步骤 ID 连续，新计划只能包含 pending 步骤。TaskStep 依据 tool 字段选择对应的参数 Schema。Goal 保存在 AgentState，执行步骤中的运行状态与提出的计划分开更新。`current_step` 使用从 0 开始的位置，等于计划长度时表示步骤已全部执行。

## 模块职责

| 模块 | 职责 | 依赖边界 |
| --- | --- | --- |
| `app/schemas/plan.py` | Plan/TaskStep 与控制字段约束 | 不依赖 SDK |
| `app/schemas/report.py` | Phase 1 阶段结果 | 不将收集结果包装成完整求职分析 |
| `app/agent/state.py` | 目标、计划、进度、观察、错误与终态 | 一次任务自己的状态 |
| `app/agent/planner.py` | 调用统一 LLM Service 生成计划 | 不构造厂商客户端 |
| `app/agent/executor.py` | 参数校验、工具分发、有限重试与结果记录 | 不执行模型给出的任意函数或命令 |
| `app/agent/workflow.py` | 将规划与执行组织成有终点的流程 | 保持业务控制流可读 |
| `app/services/llm.py` | generate/structured 接口、解析校验与有限修复 | 隔离厂商响应和错误 |
| `app/tools/` | read_profile 与 search_jobs | 明确输入输出 Schema，来源标记随结果保留 |
| `app/cli.py` | CLI 参数与运行入口 | 只调用应用流程，避免导入副作用 |

## 为什么暂不用大型框架

Phase 1 只有清楚的规划和顺序工具执行，用普通 Python 可以直接看见 State、步骤和失败路径。后续确有复杂分支、持久化或恢复需求时，再评估 LangGraph；当前不开发通用 LLM SDK。

## Provider 与结构化输出

配置使用 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。fake 让无 Key 的本地运行和测试可复现；DeepSeek Adapter 负责真实访问及必要厂商差异。未来 OpenAI-compatible 或本地接口可以通过配置/小适配器接入，当前不承诺所有厂商已完成真实兼容验收。

模型原始响应先解析，再使用 Pydantic 校验。失败时提供受控反馈并有限修复；耗尽次数后交回明确错误。业务不直接处理 SDK 响应对象，也不记录原始 SDK 异常、Key 或私人内容。

## 工具与来源

- `read_profile`：只读取选定数据目录中的 `profile.json`；输入及返回结构要通过校验。仓库内置资料标记 `sample: true`，用户资料可标记 `sample: false`。`--data-dir` 可指向已被 Git 忽略的 `data/private`；工具仍只接受固定文件名，以白名单、大小限制与路径检查保护读取边界。指定数据目录且使用 sample 搜索时，该目录还需要合成的 `job_samples.json`。
- `search_jobs`：按目标寻找岗位相关来源。sample 模式明确标记 synthetic；web 模式使用公开岗位源并按目标职位过滤，具体覆盖与时效限制见工具 warnings。当前仅收集来源条目/摘要，没有进行岗位全文提取与语义核验。初级目标缺乏初级证据时返回空结果，不能用 Senior 岗位补数。

当前公开源适配为 Remotive 远程岗位 API，输出 `source_kind: public_job_listing`，并在本地按目标词保守过滤。公开快照缓存在已被 Git 忽略的 `runtime/`，缓存有效期为 6 小时，用来减少重复请求。这个可重建的公开数据缓存不修改用户 Profile，也不是正式求职材料导出；“只读工具”描述的是业务权限边界。

LLM 输出的工具名和参数不能绕过注册表或输入校验。两个工具都只读；当前无需为它们增加写入审批。修改资料与正式导出的 approval 在 Phase 3 实现。

Phase 1 使用“结构化 Plan + 应用自行分发工具”。它没有调用 Provider 的原生 Tool Calling API；旧示例里的原生工具调用仍作为独立学习成果保留。

## 错误、轨迹与退出

Schema 错误、配置错误、工具失败和网络失败以安全摘要进入运行结果。修复/重试有次数上限与适用的超时，最终进入 completed 或 failed。基础执行事件帮助观察当前流程，不宣称已具备完整可观测平台。

LLM Service 默认最多修复一次结构化输出；DeepSeek Adapter 默认最多重试一次可恢复传输失败，并关闭 SDK 自带的隐式重试。Executor 默认最多重试一次可恢复工具失败，配置上限为两次重试。不可重试错误立即结束当前操作，工具永久失败时整个收集任务进入 failed；当前没有自动换来源或跳过失败步骤的策略。

Trace 记录 node、step_id、工具名、字段名/结果摘要、duration_ms、success、retry_count 和安全 error_code，不写入完整提示词、响应或私人资料。收集阶段还会检查输出结构和至少一个搜索结果；该检查不是独立的语义 Verifier。

Phase 1 完成意味着计划和资料收集结束。它不意味着实现岗位全文提取、技能频次、Gap Analysis、7 天计划或独立 Verifier；这些仍在后续阶段。

## 验证方法

测试应覆盖结构合法/非法、修复成功/耗尽、未知工具、坏参数、工具成功/失败、状态终止和完整离线流程。CLI 实跑使用与文档一致的入口。真实 DeepSeek 和 web 模式分别报告，不能用 fake 测试或 synthetic demo 替代。

本轮最终验证：73 项新测试（23 LLM、34 工具、16 集成）与 7 项旧回归通过，正常和 recovery CLI 通过。公开快照于 `2026-09-22T09:34:29Z` 实际抓取，后续运行命中缓存。宽泛 AI Engineer 目标获得两个相关 Senior AI 条目，精确 junior 目标返回 `NO_SEARCH_RESULTS` 并以失败终止。

两次受限 DeepSeek 验证各仅发一个请求，均关闭传输重试与格式修复。最终 DeepSeek + web CLI 使用真实模型和缓存公开来源，约 5.71 秒，4 步计划、3 次搜索、2 个去重来源；Profile 为样例。这里的 PASS 限于 Phase 1 资料收集和失败处理，不证明每次都重新联网，不证明找到 junior 岗位或用户已经掌握代码。

## 从 CLI 观察执行

在仓库根目录、完成依赖安装后运行：

```powershell
python -m app --provider fake
python -m app --provider fake --demo-recovery
python -m app --provider fake --json
```

第一个命令使用假模型和合成搜索来源。第二个明确注入一次坏 JSON 和一次工具超时，用于演示有界修复；它只允许 fake + sample。第三个输出完整状态，`run_mode` 标明 Provider、搜索模式和是否注入失败。JSON 可能包含用户 Profile，因此结果不得提交到仓库。

`--provider deepseek` 单独启用真实模型，`--search-mode web` 单独启用真实搜索；两者互不等价。DeepSeek + sample 仍然只有合成岗位来源，fake + web 的计划仍然是预设计划。实际联网状态以验证报告为准。
