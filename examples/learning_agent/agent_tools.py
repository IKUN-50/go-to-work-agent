import ast
import operator
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


# 文件读取函数
def read_file(filename):
    file_path = (BASE_DIR / filename).resolve()

    if file_path != BASE_DIR and BASE_DIR not in file_path.parents:
        return "只能读取 Agent 项目目录内的文件"

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return "文件不存在"


def evaluate_math_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("算式中只能包含数字")
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY_OPERATORS:
        left = evaluate_math_node(node.left)
        right = evaluate_math_node(node.right)

        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("指数过大")

        result = ALLOWED_BINARY_OPERATORS[type(node.op)](left, right)

        if abs(result) > 1e100:
            raise ValueError("计算结果过大")

        return result

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPERATORS:
        value = evaluate_math_node(node.operand)
        return ALLOWED_UNARY_OPERATORS[type(node.op)](value)

    raise ValueError("算式包含不允许的内容")


# 工具函数
def calculator(expression):
    if len(expression) > 200:
        raise ValueError("算式过长")

    expression_tree = ast.parse(expression, mode="eval")
    return evaluate_math_node(expression_tree.body)


# 打招呼函数
def say_hello():
    return "你好，我现在可以和你打招呼！"
