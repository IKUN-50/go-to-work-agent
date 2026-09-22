from agent_tools import calculator, read_file, say_hello
import json
MEMORY_FILE = "memory.json"

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



def fake_ai_brain(user_input):
    # 计算类判断
    if "计算" in user_input or "算" in user_input or looks_like_math(user_input):
        return {
            "tool_name": "calculator",
            "arguments": {
                "expression": extract_expression(user_input)
            }
        }
    # 打招呼类判断
    if "你好" in user_input or "hello" in user_input:
        return {
            "tool_name": "say_hello",
            "arguments": {}
        }
    # 历史记录类判断
    if "历史" in user_input or "记录" in user_input or "刚刚" in user_input:
        return {
            "tool_name": "show_memory",
            "arguments": {}
        }
    # 文件读取类判断
    if "读取" in user_input or "帮我" in user_input or "文件" in user_input:
        return {
            "tool_name": "read_file",
            "arguments": {
                "filename": extract_filename(user_input)
            }
        }
    return {
        "tool_name": None,
        "arguments": {}
    }

# 生成最终回答
def fake_ai_answer(user_input, tool_name, tool_result):
    if tool_name == "calculator":
        return f"我帮你算好了，结果是: {tool_result}"
    
    if tool_name == "say_hello":
        return tool_result
    
    if tool_name == "show_memory":
        return tool_result
    
    if tool_name == "read_file":
        return tool_result
    
    return "直接回答：俺不知道用哪个工具"



#文件名提取函数
def extract_filename(user_input):
    user_input = user_input.replace("读取", "")
    user_input = user_input.replace("帮我", "")
    user_input = user_input.replace("文件", "")
    user_input = user_input.strip()
    return user_input

# 判断是否是数学表达式
def looks_like_math(user_input):
    allowed_chars = "0123456789+-*/(). "
    has_number = False

    for char in user_input:
        if char in "0123456789":
            has_number = True  
        elif char not in allowed_chars:
            return False
        
    return has_number


# 提取数学表达式
def extract_expression(user_input):
    allowed_chars = "0123456789+-*/(). "
    expression = ""

    for char in user_input:
        if char in allowed_chars:
            expression = expression + char

    expression = expression.strip()
    return expression



# 显示历史记录函数
def show_memory():
    if len(memory) == 0:
        return "没有历史记录"
    
    text = ""

    for item in memory:
        text = text + item["role"] + ": " + item["content"] + "\n"

    return text


def build_tool_schemas():
    tool_schemas = []

    for tool_name, tool_info in tools.items():
        tool_schema = {
            "name": tool_name,
            "description": tool_info["description"],
            "parameters": tool_info["parameters"]
        }

        tool_schemas.append(tool_schema)

    return tool_schemas



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


tool_schemas = build_tool_schemas()



while True:
    user_input = input("你想问什么：")

    if user_input == "exit":
        print("agent: 再见！")
        break

    # 将用户输入添加到历史记录中
    memory.append({"role": "user", "content": user_input})
    save_memory(memory)  # 保存历史记录到文件

    # 调用 AI 大脑来决定使用哪个工具
    decision = fake_ai_brain(user_input)

    execution = execute_tool(decision)

    if execution["success"]:
        tool_name = decision["tool_name"]
        tool_result = execution["result"]

        final_answer = fake_ai_answer(
            user_input,
            tool_name,
            tool_result
        )
    else:
        final_answer = execution["error"]

    print("agent:", final_answer)

    # 将最终回答添加到历史记录中
    memory.append({"role": "assistant", "content": final_answer})
    save_memory(memory)  # 保存历史记录到文件

