# go-to-work-agent

AI Career Intelligence Agent / Autonomous Job Research Agent。

目标是把求职目标转换为岗位调研、技能要求统计、技能差距分析及 7 天学习计划，同时保留清楚的执行过程，便于学习和面试讲解。

**当前版本是仓库初始化与学习代码基线。职业 Agent 的 Phase 1 尚未实现；现有示例不能代表完整的求职调研能力。**

## 当前内容

```text
examples/learning_agent/    原有 Python / Tool Calling / Pydantic 学习示例
requirements.txt           已有 Python 依赖
docs/current-status.md     当前状态与后续阶段
AGENTS.md                  后续开发约定
```

旧示例包括受限 AST 计算器、工具分发、DeepSeek 工具调用、聊天记忆及 Pydantic 校验。原学习项目保留，新代码以本仓库为版本管理入口。

## 安装与离线测试

需要 Python 3.10 或以上。以下为 PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location examples/learning_agent
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试通过 fake SDK client 验证原有工具调用，不需要真实 API Key，也不调用付费 API。首次测试时出现“历史记录文件不存在”提示是正常的，因为私人聊天记录不入仓。

旧示例保留其教学时的行为：`agent.py` 导入时创建客户端，`exercise.py` 和 `structured_output_demo.py` 直接启动交互。请勿把这些文件作为新应用的业务模块导入。

## 新 Agent 的设计方向

```text
Goal → Planner → Executor → Tools → Observations → Verifier → Report
          ↓
      LLM Service → Provider Adapter → DeepSeek API
```

- 业务层只使用 `llm.generate(...)` 或 `llm.generate_structured(...)`。
- Pydantic Schema 是内部数据契约；SDK 响应和厂商差异留在适配层。
- DeepSeek 为首个真实 Provider；fake 支持无 Key 开发与测试。
- 配置抽离为 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。这些是新架构的配置目标，旧示例仍使用历史变量名。
- 结构化输出失败必须有限修复，工具执行和 Agent 循环必须有退出条件。

## 版本与隐私

本仓库用于后续可运行阶段的版本管理。每次提交前检查差异、运行相关测试，再正常推送到 `origin`；不得强制覆盖远端历史。

真实密钥仅保存在本地 `.env`，仓库只保留空值的 `.env.example`。私人聊天记忆、个人资料、本地环境和运行日志不入仓。

## 当前限制

尚无新的职业 Agent State、Planner、Executor、岗位检索/抽取、技能统计、Verifier、FastAPI 或前端。现有学习示例包含历史厂商耦合，后续新架构不得沿用这种耦合。

阶段路线及验证边界见 [当前状态](docs/current-status.md)。
