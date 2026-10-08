def calculator(expression: str) -> str:
    try:
        allowed = "0123456789+-*/(). "

        if not all(char in allowed for char in expression):
            return "错误：表达式包含不允许的字符"

        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)

    except Exception as e:
        return f"计算错误：{e}"
