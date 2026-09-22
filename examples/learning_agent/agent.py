import ast
import json
import operator
from pathlib import Path

from openai import OpenAI


MODEL = "gpt-4.1-mini"
PROJECT_DIR = Path(__file__).resolve().parent

client = OpenAI()


def calculate(expression: str) -> str:
    """Safely calculate simple math expressions like 12 * (3 + 4)."""
    allowed_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    def eval_node(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](eval_node(node.operand))
        raise ValueError("Only basic math is supported.")

    tree = ast.parse(expression, mode="eval")
    return str(eval_node(tree.body))


def list_files() -> str:
    """List files in this starter project."""
    files = [p.name for p in PROJECT_DIR.iterdir() if p.is_file()]
    return "\n".join(files) if files else "No files found."


def read_file(filename: str) -> str:
    """Read a text file from this starter project."""
    path = (PROJECT_DIR / filename).resolve()
    if PROJECT_DIR not in path.parents and path != PROJECT_DIR:
        return "I can only read files inside this starter project."
    if not path.exists() or not path.is_file():
        return f"File not found: {filename}"
    return path.read_text(encoding="utf-8")[:4000]


TOOLS = [
    {
        "type": "function",
        "name": "calculate",
        "description": "Calculate a basic math expression.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A simple math expression, such as 2*(3+4).",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_files",
        "description": "List files in this starter project.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file from this starter project.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to read, for example README.md.",
                }
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
]


TOOL_FUNCTIONS = {
    "calculate": calculate,
    "list_files": list_files,
    "read_file": read_file,
}


def run_agent(user_message: str, previous_response_id: str | None = None):
    response = client.responses.create(
        model=MODEL,
        instructions=(
            "You are a friendly Python learning assistant. "
            "Explain agent ideas simply, and use tools when they help."
        ),
        input=user_message,
        tools=TOOLS,
        previous_response_id=previous_response_id,
    )

    while True:
        tool_outputs = []

        for item in response.output:
            if item.type != "function_call":
                continue

            tool_name = item.name
            args = json.loads(item.arguments or "{}")
            result = TOOL_FUNCTIONS[tool_name](**args)

            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": result,
                }
            )

        if not tool_outputs:
            return response.output_text, response.id

        response = client.responses.create(
            model=MODEL,
            input=tool_outputs,
            tools=TOOLS,
            previous_response_id=response.id,
        )


def main():
    print("Python Agent Starter")
    print("Type 'exit' to quit.\n")

    previous_response_id = None
    while True:
        user_message = input("You: ").strip()
        if user_message.lower() in {"exit", "quit", "q"}:
            print("Agent: See you next time.")
            break

        try:
            answer, previous_response_id = run_agent(user_message, previous_response_id)
            print(f"Agent: {answer}\n")
        except Exception as exc:
            print(f"Agent error: {exc}\n")


if __name__ == "__main__":
    main()
