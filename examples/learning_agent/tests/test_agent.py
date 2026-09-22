import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import my_first_agent as agent
from agent_tools import calculator, read_file


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.original_memory = agent.memory

    def tearDown(self):
        agent.memory = self.original_memory

    def test_safe_calculator_accepts_math(self):
        self.assertEqual(calculator("2 * (3 + 4)"), 14)

    def test_safe_calculator_rejects_function_calls(self):
        with self.assertRaises(ValueError):
            calculator("open(1)")

    def test_read_file_rejects_parent_escape(self):
        result = read_file(str(Path("..") / ".." / "全局工作台.md"))
        self.assertIn("只能读取", result)

    def test_model_tools_use_chat_completions_format(self):
        self.assertEqual(len(agent.model_tools), 4)

        for model_tool in agent.model_tools:
            self.assertEqual(model_tool["type"], "function")
            function_schema = model_tool["function"]
            self.assertIn("name", function_schema)
            self.assertFalse(
                function_schema["parameters"]["additionalProperties"]
            )

    def test_explains_insufficient_balance(self):
        error = SimpleNamespace(status_code=402)
        message = agent.explain_status_error(error)
        self.assertIn("余额不足", message)

    def test_deepseek_ai_can_return_text_without_a_tool(self):
        message = SimpleNamespace(content="这是模型直接回答。", tool_calls=None)
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        fake_client = FakeClient([response])
        agent.memory = [{"role": "user", "content": "解释什么是 Agent"}]

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            with patch.object(agent, "OpenAI", return_value=fake_client):
                answer = agent.run_deepseek_ai()

        self.assertEqual(answer, "这是模型直接回答。")
        self.assertEqual(len(fake_client.chat.completions.calls), 1)

    def test_deepseek_ai_executes_tool_and_returns_result_to_model(self):
        tool_call = SimpleNamespace(
            id="call-123",
            function=SimpleNamespace(
                name="calculator",
                arguments='{"expression": "2 + 3"}'
            )
        )
        tool_message = SimpleNamespace(content=None, tool_calls=[tool_call])
        tool_response = SimpleNamespace(
            choices=[SimpleNamespace(message=tool_message)]
        )
        final_message = SimpleNamespace(content="计算结果是 5。", tool_calls=None)
        final_response = SimpleNamespace(
            choices=[SimpleNamespace(message=final_message)]
        )
        fake_client = FakeClient([tool_response, final_response])
        agent.memory = [{"role": "user", "content": "帮我计算 2 + 3"}]

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            with patch.object(agent, "OpenAI", return_value=fake_client):
                answer = agent.run_deepseek_ai()

        self.assertEqual(answer, "计算结果是 5。")
        self.assertEqual(len(fake_client.chat.completions.calls), 2)

        second_messages = fake_client.chat.completions.calls[1]["messages"]
        tool_outputs = [
            item
            for item in second_messages
            if isinstance(item, dict) and item.get("role") == "tool"
        ]

        self.assertEqual(len(tool_outputs), 1)
        self.assertEqual(tool_outputs[0]["tool_call_id"], "call-123")

        execution = json.loads(tool_outputs[0]["content"])
        self.assertTrue(execution["success"])
        self.assertEqual(execution["result"], 5)


if __name__ == "__main__":
    unittest.main()
