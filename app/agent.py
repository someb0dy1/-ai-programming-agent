import json
import os
import requests
from dotenv import load_dotenv

from app.logger import logger
from app.tools.calculator import calculator
from app.tools.time_tool import get_current_time
from app.tools.python_tool import run_python
from app.tools.file_tool import (
    list_project_files,
    read_project_file,
    write_project_file,
)


load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat"
)

MODEL = os.getenv(
    "MODEL",
    "qwen2.5:7b"
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，例如 125 * 36 + 500",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "需要计算的数学表达式"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前系统的日期和时间。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "执行 Python 代码或直接运行项目中的真实 Python 文件，并返回运行结果。适合计算、数据处理、编程测试和 Debug。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "需要执行的 Python 代码。如果使用 entry_file 直接运行项目文件，可以为空字符串。"
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "执行 Python 代码时需要加载的项目文件列表，例如 ['test_debug.py']。"
                    },
                    "entry_file": {
                        "type": "string",
                        "description": "需要直接运行的项目 Python 文件，例如 'test_debug.py'。指定后将直接在 Docker 沙箱中执行该真实项目文件，而不是重新拼接验证代码。"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_files",
            "description": "列出 AI Agent 项目目录中的文件。用于分析项目结构。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_file",
            "description": "读取 AI Agent 项目目录中的指定文件，用于分析代码和查找问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "项目目录中的相对文件路径，例如 app/agent.py"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_project_file",
            "description": "修改 AI Agent 项目目录中的指定文件。用于修复代码或更新项目文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "项目目录中的相对文件路径，例如 app/tools/calculator.py"
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入文件的完整内容"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    }
]

def call_llm(messages, tools=None):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False
    }

    if tools:
        payload["tools"] = tools

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    print("\n========== RAW OLLAMA RESPONSE ==========")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("==========================================\n")

    return data

SYSTEM_PROMPT = """
你是一个运行在本地 Ubuntu 服务器上的 AI Programming Agent。

你的任务是帮助用户完成计算、Python 编程、项目分析、代码修改和 Debug。

工具使用规则：

1. 数学计算
- 涉及数学计算时优先使用 calculator。
- 不要凭空猜测复杂计算结果。

2. 当前时间
- 用户询问当前日期或时间时，必须使用 get_current_time。

3. Python
- 涉及 Python 编程、代码测试、数据处理或 Debug 时，可以使用 run_python。
- 如果需要验证计算结果，Python 代码必须使用 print() 输出结果。
- 不要只根据代码逻辑猜测运行结果。
- Python 执行失败后，要分析错误原因并尝试修改代码。
- Debug 最多连续尝试 3 次。
- 不要通过简单修改函数名、变量名来掩盖原始代码的问题。
- 应该修复真正的实现逻辑，并重新运行验证。
- 如果 Debug 的目标是项目中的实际文件，验证时必须优先使用 run_python 的 files 参数加载真实项目文件。
- 用户明确指定了目标文件路径后，必须始终使用用户指定的原始路径。
- read_project_file、write_project_file 和 run_python 的 entry_file 必须保持目标文件路径一致。
- 不允许因为文件名与某个目录中的文件相似，就擅自改变目标文件路径。
- 例如用户指定 test_debug.py，就必须操作 test_debug.py；不能自行改成 app/tools/test_debug.py。
- 如果目标文件不存在，必须先报告文件不存在，不允许自行创建同名文件到其他目录代替目标文件。
- 修改文件前必须确认 read_project_file 返回的文件路径与用户指定的目标路径一致。
- 修改完成后，必须使用相同的文件路径进行验证。
- 如果 Debug 的目标是一个可以直接运行的 Python 项目文件，验证时优先直接执行该真实文件，而不是在 run_python 的 code 中重新拼接验证逻辑。
- 如果需要直接验证某个项目脚本，必须确保验证代码能够实际加载并执行该脚本中的真实代码。
- 不允许在没有导入目标函数、变量或模块的情况下，直接调用项目文件中定义的函数或变量。
- 如果无法确定正确的导入方式，应先读取目标文件并根据实际代码结构确定验证方式，而不是猜测。
- 不要只把项目文件内容复制到 run_python 的 code 中，然后声称已经验证了原文件。
- 例如验证 test_debug.py 时，应使用 files: ["test_debug.py"]，并通过 import 或直接执行真实项目文件进行验证。
- 如果验证多个项目文件，可以在 files 中同时提供相关文件的相对路径。
- files 中只能提供项目目录内的文件，不得访问项目目录之外的文件。
- 如果 Debug 目标是可以直接运行的 Python 项目文件，验证时必须优先使用 run_python 的 entry_file 参数直接执行真实文件。
- 例如验证 test_debug.py 时，应使用：
  files: ["test_debug.py"]
  entry_file: "test_debug.py"
  code: ""
- 使用 entry_file 时，不要在 code 中重新调用目标文件里的函数或变量。
- 只有当目标文件不能直接运行，或者需要针对某个函数进行独立测试时，才使用 code + files 的方式验证。
- Debug 任务中，文件路径属于任务约束，不属于可以由 Agent 自由修改的内容。

4. 项目结构
- 需要了解项目有哪些文件时，使用 list_project_files。

5. 读取项目文件
- 需要查看、分析或排查项目代码时，使用 read_project_file。
- 不要假装已经读取某个文件。
- 如果需要修改文件，可以先读取文件了解当前内容。

6. 修改项目文件
- 用户明确要求创建、修改、修复、覆盖项目文件时，必须使用 write_project_file。
- 不要使用 run_python 代替 write_project_file 修改项目文件。
- write_project_file 必须写入实际需要修改的完整文件内容。
- 修改完成后必须根据工具返回结果确认写入是否成功。
- 不要声称修改成功，除非工具已经返回成功结果。

7. Debug 工作流程
当用户要求修复代码时，应遵循：

分析问题
→ 读取相关文件
→ 修改实际代码
→ 运行测试
→ 分析测试结果
→ 如果失败，继续修复
→ 再次测试
→ 最终总结

8. 工具执行
- 工具调用完成后，要根据工具返回结果继续处理任务。
- 不要忽略工具返回结果。
- 如果工具已经完成用户要求，可以直接给出最终结果。
- 如果模型没有生成文字回复，但工具已经成功完成用户要求，可以简洁说明操作已经完成。

9. 文件安全
- 只能操作 AI Agent 项目目录中的文件。
- 不要尝试访问项目目录之外的文件。
"""

def run_agent(user_input, event_callback=None):
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": user_input
        }
    ]

    debug_count = 0
    max_debug_count = 3

    def emit(event_type, message):
        if event_callback:
            event_callback({
                "type": event_type,
                "message": message
            })

    while True:
        emit("thinking", "Agent 正在分析任务")

        if debug_count >= max_debug_count:
            emit(
                "limit",
                f"已达到最大 Debug 次数限制（{max_debug_count} 次），停止继续执行 Python。"
            )

            final_messages = messages + [
                {
                    "role": "system",
                    "content": (
                        "Debug 次数已达到上限。"
                        "请根据目前已经完成的工具执行结果，"
                        "直接总结当前任务的最终状态。"
                        "不要再调用任何工具。"
                    )
                }
            ]

            final_data = call_llm(final_messages)
            final_message = final_data.get("message", {})
            final_content = final_message.get("content", "")

            emit("answer", "Agent 已停止 Debug 并生成最终总结")

            return final_content or "已达到 Debug 次数上限，请检查当前任务结果。"

        data = call_llm(messages, tools=TOOLS)
        message = data.get("message", {})

        emit("thinking", "Agent 收到模型响应")

        tool_calls = message.get("tool_calls")

        if not tool_calls:
            content = message.get("content", "")

            # 兼容 <tool_call>...</tool_call> 格式
            if "<tool_call>" in content:
                try:
                    tool_text = content.split(
                        "<tool_call>", 1
                    )[1].split(
                        "</tool_call>", 1
                    )[0].strip()

                    tool_data = json.loads(tool_text)

                    tool_calls = [
                        {
                            "function": {
                                "name": tool_data["name"],
                                "arguments": tool_data.get(
                                    "arguments", {}
                                )
                            }
                        }
                    ]

                    emit(
                        "tool_call",
                        f"检测到 Tool Call：{tool_data['name']}"
                    )

                except Exception as e:
                    logger.error(
                        f"解析 Qwen Tool Call 失败：{e}"
                    )
                    emit(
                        "error",
                        "Tool Call 格式解析失败"
                    )
                    return content

            # 兼容 Qwen 直接输出 JSON Tool Call
            else:
                try:
                    json_start = content.find("{")
                    json_end = content.rfind("}")

                    if json_start != -1 and json_end > json_start:
                        possible_json = content[
                            json_start:json_end + 1
                        ]

                        tool_data = json.loads(
                            possible_json
                        )

                        if (
                            isinstance(tool_data, dict)
                            and "name" in tool_data
                            and "arguments" in tool_data
                        ):
                            tool_calls = [
                                {
                                    "function": {
                                        "name": tool_data["name"],
                                        "arguments": tool_data.get(
                                            "arguments", {}
                                        )
                                    }
                                }
                            ]

                            emit(
                                "tool_call",
                                f"检测到 JSON Tool Call："
                                f"{tool_data['name']}"
                            )

                except Exception as e:
                    logger.debug(
                        f"未检测到 JSON Tool Call：{e}"
                    )

            # JSON / XML Tool Call 解析成功后，
            # 跳过普通最终回答逻辑，继续执行工具
            if not tool_calls:
                if not content.strip():
                    emit(
                        "success",
                        "工具执行完成，模型未生成文字回复"
                    )
                    return (
                        "操作已完成，相关项目文件已经成功修改。"
                    )

                action_keywords = [
                    "将修复",
                    "我要修复",
                    "现在修复",
                    "开始修复",
                    "将修改",
                    "我要修改",
                    "现在修改",
                    "使用 run_python",
                    "使用 Python 沙箱",
                    "进行验证",
                    "继续验证",
                ]

                needs_action = any(
                    keyword in content
                    for keyword in action_keywords
                )

                if needs_action:
                    emit(
                        "thinking",
                        "Agent 表示需要继续执行，但未调用工具，要求继续执行"
                    )

                    messages.append({
                        "role": "assistant",
                        "content": content
                    })

                    messages.append({
                        "role": "user",
                        "content": (
                            "请不要只描述下一步操作。"
                            "请立即执行你刚才计划的操作。"
                            "如果需要修改项目文件，请调用 write_project_file。"
                            "如果需要运行和验证 Python，请调用 run_python。"
                            "必须实际执行工具后再继续回答。"
                        )
                    })

                    continue

                emit(
                    "answer",
                    "Agent 生成最终答案"
                )
                return content

        messages.append(message)

        for tool_call in tool_calls:
            function_data = tool_call.get("function", {})
            tool_name = function_data.get("name")
            arguments = function_data.get("arguments", {})

            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}

            emit(
                "tool_call",
                f"Agent 调用工具：{tool_name}"
            )

            try:
                if tool_name == "calculator":
                    result = calculator(
                        arguments.get("expression", "")
                    )

                elif tool_name == "get_current_time":
                    result = get_current_time()

                elif tool_name == "run_python":
                    if debug_count >= max_debug_count:
                        result = (
                            f"错误：已达到最大 Debug 次数限制 "
                            f"({max_debug_count} 次)，禁止继续运行 Python。"
                        )
                        emit("limit", result)
                    else:
                        debug_count += 1

                        emit(
                            "sandbox",
                            f"Python 沙箱执行第 {debug_count}/{max_debug_count} 次"
                        )

                        result = run_python(
    arguments.get("code", ""),
    arguments.get("files", []),
    arguments.get("entry_file", "")
)

                elif tool_name == "list_project_files":
                    result = list_project_files()

                elif tool_name == "read_project_file":
                    result = read_project_file(
                        arguments.get("file_path", "")
                    )

                elif tool_name == "write_project_file":
                    result = write_project_file(
                        arguments.get("file_path", ""),
                        arguments.get("content", "")
                    )

                else:
                    result = f"错误：未知工具：{tool_name}"

                emit(
                    "result",
                    f"{tool_name} 执行结果：{result}"
                )

            except Exception as e:
                logger.error(
                    f"工具 {tool_name} 执行失败：{e}"
                )

                result = f"工具执行失败：{e}"

                emit(
                    "error",
                    f"{tool_name} 执行失败"
                )

            messages.append(
                {
                    "role": "tool",
                    "content": result
                }
            )

