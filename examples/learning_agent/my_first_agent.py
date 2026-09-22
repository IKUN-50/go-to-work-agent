import json
import os
from pathlib import Path

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from agent_tools import calculator, read_file, say_hello


BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memory.json"
DEEPSEEK_BASE_URL = "https://api.deepseek.com" #请求服务器
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash") #模型名称("环境变量名称"，"默认值")
MAX_TOOL_ROUNDS = 5
SYSTEM_PROMPT = """
你是一个运行在本地 Python 程序中的 AI Agent。
普通问题可以直接回答；需要计算、读取本地文件、打招呼或查看历史记录时，可以调用相应工具。
不要声称自己执行了没有实际调用的工具。
工具返回失败信息时，请向用户简洁说明原因。
回答使用中文，清楚、自然，不要暴露内部工具调用格式。
""".strip()

def load_memory():#查看并提取历史记录
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print("历史记录文件不存在，创建一个新的历史记录文件。")
        return []
    except json.JSONDecodeError:
        print("历史记录文件内容无效，创建一个新的历史记录文件。")
        return []

def save_memory(memory):#保存历史记录
    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, ensure_ascii=False, indent=2)
# 显示历史记录函数
def show_memory():
    if len(memory) == 0:
        return "没有历史记录"
    
    text = ""

    for item in memory:
        text = text + item["role"] + ": " + item["content"] + "\n"

    return text


def build_model_tools():
    model_tools = []

    for tool_name, tool_info in tools.items():
        parameters = {
            **tool_info["parameters"],
            "additionalProperties": False  #模型不允许传入未定义的参数
        }

        model_tool = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_info["description"],
                "parameters": parameters
            }
        }

        model_tools.append(model_tool)

    return model_tools


def build_model_messages():
    recent_memory = memory[-12:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [
        {
            "role": item["role"],
            "content": item["content"]
        }
        for item in recent_memory
    ]

    return messages


def serialize_execution(execution):
    return json.dumps(execution, ensure_ascii=False, default=str)


def explain_status_error(error):
    if getattr(error, "status_code", None) == 402:
        return "DeepSeek API 余额不足，请先到 DeepSeek 开放平台充值。"

    return f"DeepSeek API 调用失败：{error}"


def run_deepseek_ai():
    api_key = os.getenv("DEEPSEEK_API_KEY")  # 获取 DeepSeek API 密钥

    if not api_key:
        return "没有找到 DEEPSEEK_API_KEY，请先配置 DeepSeek API 密钥。"

    # DeepSeek 兼容 OpenAI SDK，实际服务商由 base_url 决定，创建客户端
    client = OpenAI(  #使用openai库创建客户端
        api_key=api_key,  #告诉客户端使用哪个api_key
        base_url=DEEPSEEK_BASE_URL  #告诉客户端把请求发给哪个服务器
    )
    messages = build_model_messages()

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=model_tools,
                extra_body={"thinking": {"type": "disabled"}}
            )

            message = response.choices[0].message
            messages.append(message)
            tool_calls = message.tool_calls

            if not tool_calls:
                if message.content:
                    return message.content
                return "模型没有生成可显示的回答。"

            for tool_call in tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    decision = {
                        "tool_name": tool_call.function.name,
                        "arguments": arguments
                    }
                    execution = execute_tool(decision)
                except json.JSONDecodeError:
                    execution = {
                        "success": False,
                        "result": None,
                        "error": "模型生成的工具参数不是有效 JSON。"
                    }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": serialize_execution(execution)
                })

        return "工具调用轮数过多，本次任务已停止。"

    except AuthenticationError:
        return "DeepSeek API 密钥无效，请检查 DEEPSEEK_API_KEY。"
    except RateLimitError:
        return "DeepSeek API 请求过快，已达到速率上限，请稍后重试。"
    except APIConnectionError:
        return "无法连接 DeepSeek API，请检查网络或代理设置。"
    except APIStatusError as error:
        return explain_status_error(error)
    except APIError as error:
        return f"DeepSeek API 调用失败：{error}"



SCHEMA_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict
}

def execute_tool(decision):
    if not isinstance(decision, dict):
        return {
            "success": False,
            "result": None,
            "error": "大脑返回的决定必须是字典。"
        }

    tool_name = decision.get("tool_name")
    arguments = decision.get("arguments", {})

    if tool_name is None:
        return {
            "success": False,
            "result": None,
            "error": "大脑没有选择工具。"
        }

    if tool_name not in tools:
        return {
            "success": False,
            "result": None,
            "error": f"工具不存在：{tool_name}"
        }

    if not isinstance(arguments, dict):
        return {
            "success": False,
            "result": None,
            "error": "工具参数必须是字典。"
        }

    tool_info = tools[tool_name]

    parameters_schema = tool_info["parameters"]
    required_parameters = parameters_schema.get("required", [])

    for parameter_name in required_parameters:
        if parameter_name not in arguments:
            return {
                "success": False,
                "result": None,
                "error": f"缺少必填参数：{parameter_name}"
            }
    properties = parameters_schema.get("properties", {})

    for parameter_name, parameter_value in arguments.items():
        if parameter_name not in properties:
            return {
                "success": False,
                "result": None,
                "error": f"工具不接受参数：{parameter_name}"
            }

        parameter_schema = properties[parameter_name]
        schema_type = parameter_schema.get("type")

        python_type = SCHEMA_TYPE_MAP.get(schema_type)

        if python_type is not None:
            if not isinstance(parameter_value, python_type):
                actual_type = type(parameter_value).__name__

                return {
                    "success": False,
                    "result": None,
                    "error": (
                        f"参数 {parameter_name} 类型错误："
                        f"需要 {schema_type}，实际是 {actual_type}"
                    )
                }

    tool_function = tool_info["function"]

    try:
        tool_result = tool_function(**arguments)

        return {
            "success": True,
            "result": tool_result,
            "error": None
        }

    except TypeError as error:
        return {
            "success": False,
            "result": None,
            "error": f"工具参数错误：{error}"
        }

    except Exception as error:
        return {
            "success": False,
            "result": None,
            "error": f"工具执行失败：{error}"
        }



# 工具字典
tools = {
    "calculator":{                              #工具名
        "function": calculator,                 #函数名
        "description": "计算数学表达式",          #工具描述
        "parameters":{                          #使用这个工具前需要提供的参数
            "type": "object",                   #提供参数的类型是对象
            "properties": {                     #字典中允许有哪些参数
                "expression": {
                    "type": "string",
                    "description": "数学表达式"
                }
            },
            "required": ["expression"]          # 哪些参数必须提供
        }
    },
    "say_hello": {
        "function": say_hello,
        "description": "打招呼",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "show_memory": {
        "function": show_memory,
        "description": "显示历史记录",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "read_file": {
        "function": read_file,
        "description": "读取文件",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "文件名"
                }
            },
            "required": ["filename"]
        }
    }
}

# 历史记录
memory = load_memory()


model_tools = build_model_tools()


def run_agent():
    while True:
        user_input = input("你想问什么：")

        if user_input == "exit":
            print("agent: 再见！")
            break

        # 将用户输入添加到历史记录中
        memory.append({"role": "user", "content": user_input})
        save_memory(memory)  # 保存历史记录到文件

        final_answer = run_deepseek_ai()

        print("agent:", final_answer)

        # 将最终回答添加到历史记录中
        memory.append({"role": "assistant", "content": final_answer})
        save_memory(memory)  # 保存历史记录到文件


if __name__ == "__main__":
    run_agent()
