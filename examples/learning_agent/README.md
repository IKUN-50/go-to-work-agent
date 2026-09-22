# 原有 Python Agent 学习示例

这些文件作为原学习成果保留；新的职业 Agent 将在仓库根目录 `app/` 中开发。

| 文件 | 作用 |
| --- | --- |
| `exercise.py` | 关键词路由的假大脑与工具分发 |
| `my_first_agent.py` | 历史 DeepSeek Tool Calling 和对话记忆 |
| `structured_output_demo.py` | JSON、Pydantic 和计算路由手写练习 |
| `agent_tools.py` | 受限 AST 计算器和本地文件工具 |
| `agent.py` | 更早的 OpenAI Responses API 示例 |
| `tests/test_agent.py` | 7 项现有离线回归测试 |

安装仓库根目录依赖后，在本目录执行：

```powershell
python -m unittest discover -s tests -v
```

离线测试不需要 Key。真实调用前请注意：这些旧脚本仍从进程环境读取历史变量，没有自动加载 `.env`。如果要手动运行旧 DeepSeek 示例，可从本目录使用显式 dotenv 包装命令：

```powershell
python -c "from dotenv import load_dotenv; import runpy; load_dotenv('.env'); runpy.run_path('my_first_agent.py', run_name='__main__')"
```

本地 `.env` 可按本目录 `.env.example` 填写；不要把真实密钥写进代码或提交。模型名应按服务端当前可用型号设置，示例中的历史默认值不代表实时可用性。

`memory.json` 是运行时的个人聊天记录，本仓库不包含它。`exercise.py`、`structured_output_demo.py` 在加载时直接进入交互；`agent.py` 在加载时创建 SDK 客户端，因此不要批量 import 这些文件做检查。旧示例的通用文件工具也不适合直接复用为新 Agent 的个人资料读取器。
