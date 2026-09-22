# 当前状态

更新：2026-09-22。

## 已完成

- 克隆远端 `IKUN-50/go-to-work-agent`，保留原 `main` 历史。
- 从已有学习项目复制 Python 示例与现有测试；原项目源码保留。
- 源码和测试复制后以 SHA-256 核对一致；README 改成可移植的启动说明。
- 排除真实密钥、私人 `memory.json`、本地环境及运行产物。
- 原学习代码的 7 项离线测试在迁移副本运行通过。

## 尚未完成

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 0 | 已有能力、保留边界、架构审计 | 只读盘点已完成，完整项目计划待更新 |
| Phase 1 | Schema、State、Planner、Executor、1–2 个 Tool、最小 workflow、LLM Service | 待实现 |
| Phase 2 | 岗位抽取、统计、Gap Analysis、7 天计划 | 待实现 |
| Phase 3 | Verifier、恢复、完整 Trace、approval | 待实现 |
| Phase 4 | FastAPI | 待实现 |
| Phase 5 | 前端 | 待实现 |
| Phase 6 | 完整 demo、求职 README、面试材料与复盘 | 待实现 |

## 下一步

恢复 Phase 1 时首先建立 `app/` 中的 schema/state 和统一 LLM Service；DeepSeek 为首个真实 Provider，无 Key 时仍能通过 fake 完成流程测试。不要把旧教学示例中的直接 SDK 调用复制到 Planner/Executor。

职业 Agent 的新适配器真实调用、岗位数据与完整流程均未验证。本次基线不代表 Phase 1 已完成，也不代表用户已能独立解释全部代码。
