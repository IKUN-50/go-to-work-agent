# go-to-work-agent

AI Career Intelligence Agent / Autonomous Job Research Agent。

这是一个面向求职调研的 Python Agent 项目，同时保留学习示例与面试解释材料。最终目标是从求职目标出发，收集岗位、统计技能、分析差距并生成 7 天冲刺计划。

**当前交付 Phase 1：规划 → 读取技能档案 → 检索来源 → 输出阶段报告。岗位全文抽取、技能统计、差距分析和 7 天计划属于 Phase 2，尚未实现。**

## Architecture

```text
User goal
    ↓
Planner ──→ LLMService ──→ Provider adapter ──→ DeepSeek API / Fake
    ↓          JSON parsing + Pydantic validation + bounded repair
Validated Plan (2–4 steps)
    ↓
Executor ──→ read_profile / search_jobs
    ↓          schema validation + bounded tool retry
Observations + State + Trace
    ↓
Phase 1 collection report
```

新业务代码中没有厂商 SDK Client。当前只有适配层使用 OpenAI SDK 访问 DeepSeek；这不意味着使用 OpenAI 的模型或服务。

## How to Run

Python 3.10+。以下命令在仓库根目录执行，示例使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app --provider fake
```

已有安装了依赖的 Python 环境时，直接用该解释器执行 `-m app` 即可。

默认离线 demo 无需 Key，不访问网络；Planner 使用脚本化假响应，岗位来源使用明确标记的合成样例，不是当前招聘市场证据。

### 演示失败恢复

```powershell
.\.venv\Scripts\python.exe -m app --provider fake --demo-recovery
```

这个开关明确注入一次坏 JSON 和一次工具超时，用于演示真实执行的校验/重试路径。终端输出包含：

```text
generate_structured failed  retry=0 (invalid_json)
generate_structured success retry=1
Planner      success
read_profile success
search_jobs  failed  retry=0 (SIMULATED_TIMEOUT)
search_jobs  success retry=1
Report       success
```

这是故障注入演示，不声称外部服务真的发生故障或已自动切换来源。可查看一次实际运行保存的 [输出](docs/demo-recovery.txt)。

### 使用 DeepSeek

复制根目录 `.env.example` 为 `.env`，填写自己的本地配置：

```dotenv
LLM_PROVIDER=deepseek
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
```

`LLM_API_KEY` 在本地填写真实值；不要贴进代码、文档、日志或 Git。再运行：

```powershell
.\.venv\Scripts\python.exe -m app --provider deepseek --goal "研究 Junior AI Agent Engineer 岗位并读取我的技能档案"
```

DeepSeek 模式会发送真实模型请求。配置只读取仓库根目录的 `.env`，不向父目录搜索；进程环境优先，并兼容历史 `DEEPSEEK_*` 名称。Planner 当前只接收目标与工具/输出 Schema，不接收本地 Profile 内容。

`LLM_TIMEOUT_SECONDS` 控制 SDK 网络超时；`LLM_MAX_TOKENS` 限制输出长度。`LLM_TRANSPORT_RETRIES` 和 `LLM_MAX_REPAIR_ATTEMPTS` 默认各为 1，上限均为 1；最坏至多 4 次模型 HTTP 尝试。设为 0 可使一次规划至多请求一次。没有 Key 时返回明确错误，不自动假装使用真实模型。

### 单独启用在线搜索

```powershell
.\.venv\Scripts\python.exe -m app --provider fake --search-mode web --goal "AI Engineer"
```

Provider 与搜索模式独立，可将 `fake` 替换为 `deepseek`。web 模式从 [Remotive 公开岗位 API](https://github.com/remotive-com/remote-jobs-api) 读取真实岗位快照，并在本地按查询关键词筛选，保留来源归属与原始岗位链接。每次网络请求超时 10 秒，响应最多 1 MiB。

该源只覆盖部分远程岗位，公开发布有延迟；应用将公开快照在已忽略的 `runtime/` 中缓存 6 小时以遵守请求频率建议。它不是全网实时搜索，也不验证岗位仍在招。严格的 `Junior AI Agent Engineer Python` 查询可能没有结果：此时流程明确失败，不拿 Senior 岗位补数，不回退到合成样例。

### JSON 与个人档案

`--json` 输出结构化 State，含 `run_mode`、计划、观察、错误、Trace 和最终阶段报告。它可能包含用户资料，仅用于本地查看，勿提交或自动上传。

默认 `data/profile.json` 是虚构学习档案。使用个人资料时放进已忽略的 `data/private/profile.json`，将 `sample` 设为 `false`，保留 Schema 要求的字段，并传入 `--data-dir data/private`。若使用 sample 搜索，还需要将 `data/job_samples.json` 复制到该目录。不要把个人资料填入被 Git 跟踪的示例文件。

当前工具对用户资料和外部岗位源只读；唯一运行时写入是 `runtime/` 内可重建的公开数据缓存，不含个人档案或查询。没有修改用户文档或导出正式求职材料的动作；此类动作的 approval 机制留到 Phase 3。

## Agent Design / Engineering Decisions

- **State**：目标、计划、当前步骤、Observations、错误、Trace、最终结果显式保存在 `AgentState`；每次运行独立创建。
- **Structured Output**：Pydantic 是内部契约。Planner 只能输出已知工具与各自的参数 Schema，最多 4 步，先读取 Profile，再执行 1–3 次搜索。
- **Planning 与 Tool Calling**：新流程通过结构化 Plan 驱动应用分发工具；没有依赖厂商原生 Tool Calling 协议。旧示例中的原生 Tool Calling 继续保留供学习。
- **Provider**：`LLMService.generate_structured(..., Plan)` 返回模型对象；DeepSeek 原始响应、SDK 和请求参数留在适配层。未来换厂商只需实现小型 `Provider.complete` 接口并更新工厂，不重写 Planner/Executor。
- **Retry**：连接/限流等暂时错误可重试；认证/余额错误不重试。坏 JSON/Schema 至多修复一次；工具暂时失败默认重试一次，失败耗尽后停止。每次失败均保留安全的错误码与 Trace。
- **Observation 与报告**：没有搜索来源时返回失败，不生成完成报告。最后只检查收集结构与完整性，不冒充独立语义 Verifier。
- **可解释性**：本阶段不用 LangGraph 或其他编排框架。一个有界 Python 循环直接展示执行过程。

## Tech Stack

Python、Pydantic、python-dotenv、OpenAI Python SDK（作为 DeepSeek 的 HTTP 客户端）、标准库 unittest/urllib。

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Set-Location examples/learning_agent
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

新测试覆盖 Schema、Provider 请求构造、安全错误、坏输出修复、工具输入输出、重试上限、完整 Workflow 与 CLI 边界。全部自动测试离线运行，网络验收与模型调用单独记录，见 [验证报告](docs/phase1-verification.md)。

## Code & Learning

```text
app/
  schemas/       Plan、工具、Profile、阶段报告的数据契约
  agent/         State、Planner、Executor、Workflow
  services/      LLMService、配置、DeepSeek Adapter、Fake
  tools/         只读 Profile 与岗位来源搜索
  cli.py         命令行入口
data/            明确标识的合成样例
tests/           新架构离线测试
examples/learning_agent/  原样保留的旧教学代码
```

先读 [学习交接](docs/learning-handoff.md)，只学这一阶段最重要的 5 个点。更多说明：[Phase 0 审计](docs/phase0-audit.md)、[架构](docs/architecture.md)、[当前状态](docs/current-status.md)。

## Limitations / Future Work

- Phase 1 只交付资料收集闭环；不能把它描述为已经实现完整职业顾问。
- 当前岗位源覆盖有限，保守关键词规则会漏检；Phase 2 需要扩大可靠来源、读取原始岗位页并处理数据质量。
- 本阶段没有独立 Verifier、自动换源、持久化任务队列或 Human-in-the-loop 写入动作。
- 后续依次完成 Phase 2 分析、Phase 3 验证/恢复/审批、Phase 4 FastAPI、Phase 5 前端、Phase 6 求职展示。没有登录、支付、微服务或通用 LLM SDK。
- 用户能够独立解释代码需要单独教学验收，测试通过不等于已掌握。

## Version Control

保留原学习项目和远端历史。版本经测试与差异检查后普通提交、推送到 `origin`；不强推。密钥、个人 Profile、聊天记录、运行输出与本地环境不入仓。

DeepSeek 请求参数依据 [官方 JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)；模型与服务可用性以 [官方说明](https://api-docs.deepseek.com/quick_start/pricing/) 和单独的实跑记录为准。
