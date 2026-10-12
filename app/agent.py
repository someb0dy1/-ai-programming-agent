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
    write_project_file_result,
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
            "description": "仅用于简单四则运算和括号表达式，例如 125 * 36 + 500、(100 + 50) / 2。只允许数字、+、-、*、/、括号和小数点。不要传入 sum、range、变量、函数调用或 Python 代码。遇到求和、循环、数据处理或需要执行 Python 代码的任务时，改用 run_python。",
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
            "description": "在 Docker 隔离沙箱中执行 Python 代码，并返回标准输出和错误信息。用于 Python 编程、循环、求和、数据处理、代码测试和 Debug。需要计算 1 到 N 的整数之和、使用 sum() 或 range() 等 Python 功能时，必须使用此工具。若需要验证数值结果，代码必须使用 print() 输出结果，不要只写表达式。简单四则运算优先使用 calculator。不得声称获得了某个执行结果，除非工具实际返回了该结果。",
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
                "required": []
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
        "stream": False,
        "options": {
            "num_predict": 512
        }
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
- 简单四则运算、括号表达式优先使用 calculator。
- calculator 不支持函数调用、变量、sum()、range() 或 Python 语法。
- 涉及循环求和、复杂数据处理或需要执行 Python 代码时，必须使用 run_python。
- 不要猜测计算结果，必须依据工具实际返回的结果回答。


2. 当前时间
- 用户询问当前日期或时间时，必须使用 get_current_time。

3. Python
- 涉及 Python 编程、代码测试、数据处理或 Debug 时，使用 run_python。
- 如果需要验证计算结果，Python 代码必须使用 print() 输出结果。
- 不要只根据代码逻辑猜测运行结果。
- 如果工具返回“程序没有输出内容”，不得声称已经获得了计算结果。
- 工具执行成功后，必须检查实际输出是否满足用户的要求。
- 如果已经获得正确结果，直接给出最终答案，不要重复执行无必要的操作。
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
- 必须区分工具执行状态与程序输出的业务内容。
- 当工具返回“执行成功”时，说明程序正常退出；不能仅因为输出中包含“错误”二字，就认定程序执行失败。
- 如果程序输出“错误：除数不能为 0”，应结合代码逻辑判断这是否为预期的业务提示。
- 只有工具实际返回“执行失败”、非零退出码或明确的运行时异常时，才能据此判断程序执行失败。
- 如果用户要求验证代码修复，必须同时检查实际执行状态和实际输出是否符合测试预期。
- 如果实际输出符合预期，应直接报告验证通过，不要再次要求修复。
- 如果执行结果不能证明任务完成，应明确说明验证尚未通过，不得直接宣称修复成功。

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

    # 防止模型反复请求或持续要求执行操作
    failed_write_paths = set()
    model_turn_count = 0
    max_model_turns = 8

    def emit(event_type, message):
        if event_callback:
            event_callback({
                "type": event_type,
                "message": message
            })

    while model_turn_count < max_model_turns:
        model_turn_count += 1
        emit(
            "thinking",
            f"Agent 正在分析任务（第 {model_turn_count}/{max_model_turns} 轮）"
        )

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

            if failed_write_paths:
                failed_paths = ", ".join(sorted(failed_write_paths))
                emit(
                    "error",
                    f"Debug 上限前存在文件写入失败：{failed_paths}"
                )
                return (
                    "任务状态需要检查：以下文件写入失败："
                    f"{failed_paths}。达到 Debug 次数上限，"
                    "无法确认这些文件已修改成功。"
                )

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
                        "error",
                        "模型返回了空内容，且没有调用工具；"
                        "无法确认任务是否完成。"
                    )
                    return (
                        "操作未能确认完成：模型返回了空内容，"
                        "且没有执行任何工具。请重试或检查模型响应。"
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

                if failed_write_paths:
                    success_claims = (
                        "文件已成功修改",
                        "文件修改成功",
                        "写入成功",
                        "修改已完成",
                        "已经处理好了",
                        "已处理好",
                        "处理完成",
                        "已经完成",
                        "已完成",
                        "任务完成",
                        "可以直接使用",
                        "已成功创建",
                        "创建成功",
                        "修改好了",
                        "已经修改",
                    )
                    if any(claim in content for claim in success_claims):
                        failed_paths = ", ".join(sorted(failed_write_paths))
                        emit(
                            "error",
                            f"检测到写入失败后的成功声明：{failed_paths}"
                        )
                        return (
                            "无法确认任务成功：以下文件写入失败："
                            f"{failed_paths}。请检查写入错误并重试。"
                        )

                emit(
                    "answer",
                    "Agent 生成最终答案"
                )
                return content
        # 识别本批次中写入文件与 Python 执行之间的依赖。

        def normalize_tool_path(value):
            """将项目内路径统一转换为相对路径，用于比较文件依赖。"""
            if not isinstance(value, str) or not value.strip():
                return ""

            normalized = value.strip().replace("\\", "/")

            # Windows 盘符路径不能参与依赖匹配。
            if len(normalized) >= 2 and normalized[1] == ":":
                return ""

            project_root = os.path.realpath(
                os.path.expanduser("~/ai-agent")
            )

            if os.path.isabs(normalized):
                absolute_path = os.path.realpath(normalized)
            else:
                absolute_path = os.path.realpath(
                    os.path.join(project_root, normalized)
                )

            try:
                relative_path = os.path.relpath(
                    absolute_path, project_root
                )
            except ValueError:
                return ""

            # 排除项目目录之外的路径。
            if (
                relative_path == ".."
                or relative_path.startswith(".." + os.sep)
                or os.path.isabs(relative_path)
            ):
                return ""

            return relative_path.replace("\\", "/")

        write_paths = set()
        python_dependencies = set()

        for pending_call in tool_calls:
            pending_fn = pending_call.get("function", {})
            pending_name = pending_fn.get("name")
            pending_args = pending_fn.get("arguments", {})

            if isinstance(pending_args, str):
                try:
                    pending_args = json.loads(pending_args)
                except Exception:
                    pending_args = {}

            if not isinstance(pending_args, dict):
                continue

            if pending_name == "write_project_file":
                path = normalize_tool_path(pending_args.get("file_path", ""))
                if path:
                    write_paths.add(path)

            elif pending_name == "run_python":
                for item in pending_args.get("files", []) or []:
                    path = normalize_tool_path(item)
                    if path:
                        python_dependencies.add(path)

                path = normalize_tool_path(pending_args.get("entry_file", ""))
                if path:
                    python_dependencies.add(path)

        dependent_write_paths = write_paths & python_dependencies

        # 只在存在明确文件依赖时，将相关写入操作提前。
        if dependent_write_paths:
            def tool_priority(pending_call):
                pending_fn = pending_call.get("function", {})
                pending_name = pending_fn.get("name")
                pending_args = pending_fn.get("arguments", {})

                if isinstance(pending_args, str):
                    try:
                        pending_args = json.loads(pending_args)
                    except Exception:
                        pending_args = {}

                if not isinstance(pending_args, dict):
                    return 1

                path = normalize_tool_path(pending_args.get("file_path", ""))
                if (
                    pending_name == "write_project_file"
                    and path in dependent_write_paths
                ):
                    return 0

                return 1

            tool_calls = sorted(tool_calls, key=tool_priority)


        # 保存助手的原始响应，使下一轮模型请求能够看到工具调用。
        # 兼容测试响应中缺少 role 的情况，并保留原生 tool_calls 的 ID。
        assistant_message = dict(message)
        assistant_message.setdefault("role", "assistant")

        # 如果执行顺序经过调整，同步工具调用顺序，保持与工具结果一致。
        if assistant_message.get("tool_calls"):
            assistant_message["tool_calls"] = tool_calls

        messages.append(assistant_message)

        for tool_call in tool_calls:
            function_data = tool_call.get("function", {})
            tool_name = function_data.get("name")
            arguments = function_data.get("arguments", {})

            invalid_arguments = False

            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    invalid_arguments = True

            if not isinstance(arguments, dict):
                invalid_arguments = True

            if invalid_arguments:
                result = "错误：工具参数必须是有效的 JSON 对象。"
                emit("error", f"{tool_name} 参数无效")

                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": result,
                })
                continue

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
                    code = arguments.get("code", "")
                    files = arguments.get("files", [])
                    entry_file = arguments.get("entry_file", "")

                    # 先校验参数，避免非法类型参与依赖检查。
                    if not isinstance(code, str):
                        result = "错误：code 必须是字符串。"
                        emit("error", result)

                    elif not isinstance(entry_file, str):
                        result = "错误：entry_file 必须是字符串。"
                        emit("error", result)

                    elif not isinstance(files, list) or not all(
                        isinstance(item, str) and item.strip()
                        for item in files
                    ):
                        result = (
                            "错误：files 必须是非空字符串组成的列表。"
                            "如果没有依赖文件，请传入空列表 []。"
                        )
                        emit("error", result)

                    else:
                        dependencies = {
                            normalize_tool_path(item)
                            for item in files
                        }
                        entry_path = normalize_tool_path(entry_file)

                        if entry_path:
                            dependencies.add(entry_path)

                        blocked_paths = dependencies & failed_write_paths

                        if blocked_paths:
                            result = (
                                "已跳过 Python 执行：本批次依赖的文件写入失败："
                                + ", ".join(sorted(blocked_paths))
                            )
                            emit("limit", result)

                        elif debug_count >= max_debug_count:
                            result = (
                                f"错误：已达到最大 Debug 次数限制 "
                                f"({max_debug_count} 次)，禁止继续运行 Python。"
                            )
                            emit("limit", result)

                        else:
                            debug_count += 1

                            emit(
                                "sandbox",
                                f"Python 沙箱执行第 "
                                f"{debug_count}/{max_debug_count} 次"
                            )

                            result = run_python(
                                code,
                                files,
                                entry_file
                            )


                elif tool_name == "list_project_files":
                    result = list_project_files()

                elif tool_name == "read_project_file":
                    result = read_project_file(
                        arguments.get("file_path", "")
                    )

                elif tool_name == "write_project_file":
                    write_result = write_project_file_result(
                        arguments.get("file_path", ""),
                        arguments.get("content", "")
                    )
                    result = write_result["message"]
                    written_path = normalize_tool_path(
                        arguments.get("file_path", "")
                    )
                    if written_path and not write_result["success"]:
                        failed_write_paths.add(written_path)

                else:
                    result = f"错误：未知工具：{tool_name}"

                emit(
                    "result",
                    f"{tool_name} 执行结果：{result}"
                )


            except Exception as e:
                logger.exception(
                    "工具 %s 执行失败",
                    tool_name,
                )

                result = (
                    f"工具 {tool_name} 执行失败。"
                    "详细错误已记录在服务器日志中。"
                )


                # 写入工具发生未预期异常时，也记录失败路径。
                if tool_name == "write_project_file":
                    failed_path = normalize_tool_path(
                        arguments.get("file_path", "")
                    )
                    if failed_path:
                        failed_write_paths.add(failed_path)

                emit(
                    "error",
                    f"{tool_name} 执行失败"
                )


            if (
                tool_name == "run_python"
                and "执行成功" in result
                and "程序没有输出内容" in result
            ):
                result += (
                    "\n\n提示：本次运行没有产生任何标准输出，"
                    "不能据此判断计算结果。"
                    "如果任务需要返回计算结果，请重新调用 run_python，"
                    "并使用 print() 显式输出结果。"
                    "例如：print(sum(range(1, 101)))。"
                )

            messages.append(
                {
                    "role": "tool",
                    "content": result
                }
            )

    emit("limit", f"已达到 Agent 最大请求轮数（{max_model_turns} 轮），停止继续执行。")

    if failed_write_paths:
        failed_paths = ", ".join(sorted(failed_write_paths))
        emit(
            "error",
            f"达到最大请求轮数时仍存在文件写入失败：{failed_paths}"
        )
        return (
            "任务未能在最大请求轮数内完成。"
            f"以下文件写入失败：{failed_paths}。"
            "请检查写入错误后重试。"
        )

    return "任务未能在最大请求轮数内完成。请检查前面的工具执行记录，再决定是否继续。"

