# Phase 1 验证记录

日期：2026-09-22。环境：Windows，CPython 3.13.9；openai 2.44.0、pydantic 2.13.4、python-dotenv 1.2.2。没有新增运行依赖。

## 已核对的边界

| 验证 | 状态 | 证据与限制 |
| --- | --- | --- |
| 新架构离线测试 | PASS | 最终 73 项：23 项 LLM、34 项工具、16 项集成；0.168 秒，真实 exit 0；修复前的 61 项为中间记录 |
| 原有学习测试 | PASS | 7 项，真实 exit 0；原例程没有进入新 app 调用链 |
| 原源码保护 | PASS | 5 个 Python 学习文件和原 test_agent.py 与原目录 SHA-256 全部一致 |
| 离线 CLI | PASS | fake + sample，状态 completed；明确脚本化规划与 synthetic 数据 |
| 故障恢复 CLI | PASS | 一次无效 JSON、一次模拟超时；记录失败后有限恢复；见 demo-recovery.txt |
| DeepSeek 真实调用 | PASS | deepseek-flash；关闭传输重试和格式修复，恰好一次 HTTP 请求；模型生成 3 步 Plan，执行 read_profile 和两次 sample 搜索，得到 3 个去重来源；Planner 约 2.53 秒 |
| 真实调用数据边界 | VERIFIED | 只发送公开演示目标与 Schema；没有将 Profile 内容发送给模型；Key 不记录、不复制到代码/日志 |
| 原通用搜索质量 | FAILED / 已触发修复 | 接口连通但返回与求职无关的写真馆网页，不算岗位检索验收；改用公开岗位源与相关性规则 |
| 新岗位来源质量回归 | PASS | Remotive 公开岗位记录 Schema + 本地关键词和岗位标题/初级证据检查；写真馆、Rails 岗位仅正文提 AI、Senior 提及 mentor junior 等误命中均有回归测试 |
| 公开源实际抓取 | PASS | 实际获取 Remotive 公开快照 18 条，2026-09-22T09:34:29Z；只含公开数据，原始快照在 runtime 内且不入仓 |
| fake + web CLI | PASS | AI Engineer 得到 2 条标题相关来源；cache hit，exit 0；不冒称模型真实规划或每次新抓取 |
| 精确 Junior 查询 | PASS（预期失败） | Junior AI Agent Engineer Python jobs 没有匹配，NO_SEARCH_RESULTS，exit 1；不拿 Senior 岗位补数，不回退合成数据 |
| DeepSeek + 公开源完整 CLI | PASS | 第二次受限真实模型请求，同样关闭传输重试/修复；约 5.71 秒生成 4 步，3 次搜索命中上述公开缓存，2 个去重来源；sample Profile，completed，exit 0 |
| Phase 2–6 | NOT_IMPLEMENTED | 没有岗位全文抽取/统计/Gap/7天计划、独立语义Verifier、审批写入、API或前端 |
| 用户独立讲解 | NOT_RUN | 工程通过不能替代学习验收 |

一次模型 HTTP 请求产生 provider.complete 和 generate_structured 两条事件，分别表示请求返回和 Schema 校验，不代表两次付费调用。

本轮 DeepSeek 验证共两个 HTTP 请求：先验证真实规划 + sample 资料，再验证真实规划 + 公开来源缓存；没有声称只靠 fake 就完成真实模型验收。

Remotive 来源只覆盖有限远程岗位，公开数据有 24 小时延迟，应用另缓存最多 6 小时。`AI Engineer` 的两条匹配为 Senior AI Engineer 和 Senior Independent AI Engineer / Architect，它们不是 Junior 匹配。结果保持 Remotive 归属与原始链接；未验证当前仍在招或适合用户。

## 可复现命令

```powershell
python -m unittest discover -s tests -v
python -m app --provider fake
python -m app --provider fake --demo-recovery
python -m app --provider fake --json
python -m app --provider fake --search-mode web --goal "AI Engineer"
python -m app --provider fake --search-mode web --goal "Junior AI Agent Engineer Python jobs"
```

原有测试需进入 `examples/learning_agent` 另行运行。真实 Provider 和 web 公开数据验证单独执行；单元测试不依赖 Key 或网络。

## 验收结论的含义

Phase 1 是受约束的资料收集流程。Schema 检查数据形状；本地搜索规则筛掉明显无关/资历不符的条目；二者均不能证明岗位仍在招、能力真实、建议合理或整个求职目标已完成。最终应用只返回本阶段的结果，不提前生成未经支撑的分析结论。
