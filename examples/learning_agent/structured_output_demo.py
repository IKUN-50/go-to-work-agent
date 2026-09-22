import json
import os

from typing import Literal
from pydantic import BaseModel, ValidationError
from openai import OpenAI

from agent_tools import calculator

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
class AnalysisResult(BaseModel):
    intent: Literal["chat", "calculator"]
    expression: str | None = None

def analyze_user_input(user_input):
    api_key = os.getenv("DEEPSEEK_API_KEY")

    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL
    )

    messages = [
        {
            "role": "system",
            "content": """
分析用户的请求，只返回 json。

返回格式：
{
    "intent": "chat 或 calculator",
    "expression": "数学表达式，没有则为 null"
}
""".strip()
        },
        {
            "role": "user",
            "content": user_input
        }
    ]

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}}
    )

    content = response.choices[0].message.content
    data = json.loads(content)

    return data

def validate_analysis(data):
    try:
        analysis = AnalysisResult.model_validate(data)

    except ValidationError as error:
        return False, str(error)

    if analysis.intent == "calculator":
        if analysis.expression is None:
            return False, "计算任务必须包含 expression"

        if not analysis.expression.strip():
            return False, "计算任务的 expression 不能为空字符串"

    return True, None



user_input = input("请输入问题：")
result = analyze_user_input(user_input)

print("完整结果：", result)

valid, error = validate_analysis(result)

if not valid:
    print("结构化结果无效：", error)
elif result["intent"] == "calculator":
    expression = result["expression"]

    try:
        calculation_result = calculator(expression)
        print("意图：", result["intent"])
        print("数学表达式：", expression)
        print("计算结果：", calculation_result)
    except (SyntaxError, ValueError, ZeroDivisionError) as error:
        print("计算失败：", error)
else:
    print("意图：", result["intent"])
    print("程序决定：这是普通聊天")
