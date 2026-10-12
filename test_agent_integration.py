import unittest
from unittest.mock import patch

from app import agent


def tool_call(name, arguments):
    return {
        "function": {
            "name": name,
            "arguments": arguments,
        }
    }


def model_tool_response(*calls):
    return {
        "message": {
            "content": "",
            "tool_calls": list(calls),
        }
    }


def model_final_response(content="测试完成"):
    return {"message": {"content": content}}


class AgentDependencyIntegrationTests(unittest.TestCase):

    def test_failed_write_is_reported_at_max_model_turns(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                })
            )
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)

            # 持续要求继续执行，直到触发最大模型轮数。
            return model_final_response(
                "我将修复代码，现在修复，需要继续验证。"
            )

        with (
            patch.object(
                agent, "call_llm", side_effect=fake_llm
            ) as mock_llm,
            patch.object(
                agent,
                "write_project_file_result",
                return_value={
                    "success": False,
                    "path": "demo.py",
                    "message": "写入文件失败：模拟权限错误",
                },
            ),
        ):
            answer = agent.run_agent("请修改 demo.py")

        self.assertEqual(
            mock_llm.call_count,
            8,
            "Agent 应在达到最大模型轮数后停止请求模型",
        )
        self.assertIn("任务未能在最大请求轮数内完成", answer)
        self.assertIn("demo.py", answer)
        self.assertIn("写入失败", answer)
    def test_failed_write_with_negative_final_response(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                })
            ),
            model_final_response(
                "文件没有成功修改，不能确认任务完成。"
            ),
        ]

        def fake_llm(messages, tools=None):
            return model_responses.pop(0)

        with (
            patch.object(
                agent, "call_llm", side_effect=fake_llm
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={
                    "success": False,
                    "path": "demo.py",
                    "message": "写入文件失败：模拟权限错误",
                },
            ),
        ):
            answer = agent.run_agent("请修改 demo.py")

        self.assertIn("无法确认任务成功", answer)
        self.assertIn("demo.py", answer)
    def test_invalid_files_string_is_rejected_before_python_execution(self):
        answer, python_calls, events = self.run_scenario(
            "文件写入成功",
            [
                tool_call("run_python", {
                    "code": "print('should not run')",
                    "files": "demo.py",
                    "entry_file": "",
                }),
            ],
        )

        self.assertEqual(python_calls, [])
        self.assertTrue(
            any(
                "files" in event.get("message", "")
                and (
                    "错误" in event.get("message", "")
                    or "无效" in event.get("message", "")
                )
                for event in events
            ),
            "应当报告 files 参数类型错误",
        )

    def test_invalid_files_item_is_rejected_before_python_execution(self):
        answer, python_calls, events = self.run_scenario(
            "文件写入成功",
            [
                tool_call("run_python", {
                    "code": "print('should not run')",
                    "files": ["demo.py", 123],
                    "entry_file": "",
                }),
            ],
        )

        self.assertEqual(python_calls, [])
        self.assertTrue(
            any(
                "files" in event.get("message", "")
                and (
                    "错误" in event.get("message", "")
                    or "无效" in event.get("message", "")
                )
                for event in events
            ),
            "应当报告 files 列表元素类型错误",
        )

    def run_scenario(self, write_result, calls):
        model_responses = [
            model_tool_response(*calls),
            model_final_response(),
        ]
        python_calls = []
        events = []

        def fake_llm(messages, tools=None):
            if not model_responses:
                raise AssertionError("模型响应次数超出预期")
            return model_responses.pop(0)

        def fake_write(file_path, content):
            return write_result

        def fake_python(code, files, entry_file):
            python_calls.append({
                "code": code,
                "files": files,
                "entry_file": entry_file,
            })
            return "执行成功：模拟输出"

        with (
            patch.object(agent, "call_llm", side_effect=fake_llm),
            patch.object(agent, "write_project_file_result", side_effect=lambda file_path, content: {"success": write_result.startswith("文件写入成功"), "path": file_path, "message": write_result}),
            patch.object(agent, "run_python", side_effect=fake_python),
            patch.object(agent, "calculator", return_value="2"),
        ):
            answer = agent.run_agent(
                "集成测试",
                event_callback=events.append,
            )

        return answer, python_calls, events

    def test_failed_write_blocks_dependent_python(self):
        answer, python_calls, events = self.run_scenario(
            "写入文件失败：模拟权限错误",
            [
                tool_call("run_python", {
                    "code": "print('should not run')",
                    "files": ["./demo.py"],
                    "entry_file": "",
                }),
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                }),
            ],
        )

        self.assertEqual(python_calls, [])
        self.assertTrue(any(
            "已跳过 Python 执行" in event["message"]
            for event in events
        ))
        self.assertEqual(answer, "测试完成")

    def test_successful_write_allows_dependent_python(self):
        answer, python_calls, events = self.run_scenario(
            "文件写入成功：demo.py",
            [
                tool_call("run_python", {
                    "code": "print('hello')",
                    "files": ["demo.py"],
                    "entry_file": "",
                }),
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                }),
            ],
        )

        self.assertEqual(len(python_calls), 1)
        self.assertEqual(answer, "测试完成")

    def test_failed_write_does_not_block_unrelated_python(self):
        answer, python_calls, events = self.run_scenario(
            "写入文件失败：模拟权限错误",
            [
                tool_call("run_python", {
                    "code": "print('unrelated')",
                    "files": ["other.py"],
                    "entry_file": "",
                }),
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                }),
            ],
        )

        self.assertEqual(len(python_calls), 1)
        self.assertEqual(answer, "测试完成")




    def test_non_dict_tool_arguments_do_not_execute_tool(self):
        events = []
        model_responses = [
            model_tool_response(
                tool_call("calculator", None)
            ),
            model_final_response(),
        ]

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=model_responses,
            ),
            patch.object(agent, "calculator") as mock_calculator,
        ):
            answer = agent.run_agent(
                "测试异常参数",
                event_callback=events.append,
            )

        mock_calculator.assert_not_called()
        self.assertEqual(answer, "测试完成")
        self.assertTrue(any(
            "参数无效" in event.get("message", "")
            for event in events
        ))


    def test_empty_model_response_does_not_claim_success(self):
        events = []

        with patch.object(
            agent,
            "call_llm",
            return_value={"message": {"content": ""}},
        ):
            answer = agent.run_agent(
                "请修改 demo.py",
                event_callback=events.append,
            )

        self.assertNotEqual(
            answer,
            "操作已完成，相关项目文件已经成功修改。",
            "没有执行工具时不应报告文件修改成功。",
        )


    def test_invalid_arguments_do_not_trigger_file_write(self):
        events = []
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", None)
            ),
            model_final_response(),
        ]

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=model_responses,
            ),
            patch.object(agent, "write_project_file") as mock_write,
        ):
            answer = agent.run_agent(
                "测试无效参数不能触发文件写入",
                event_callback=events.append,
            )

        mock_write.assert_not_called()
        self.assertEqual(answer, "测试完成")
        self.assertTrue(any(
            "参数无效" in event.get("message", "")
            for event in events
        ))

    def test_invalid_arguments_do_not_trigger_python_execution(self):
        events = []
        model_responses = [
            model_tool_response(
                tool_call("run_python", None)
            ),
            model_final_response(),
        ]

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=model_responses,
            ),
            patch.object(agent, "run_python") as mock_python,
        ):
            answer = agent.run_agent(
                "测试无效参数不能触发 Python 执行",
                event_callback=events.append,
            )

        mock_python.assert_not_called()
        self.assertEqual(answer, "测试完成")
        self.assertTrue(any(
            "参数无效" in event.get("message", "")
            for event in events
        ))

    def test_unknown_tool_does_not_execute_known_tools(self):
        events = []
        model_responses = [
            model_tool_response(
                tool_call("unknown_dangerous_tool", {})
            ),
            model_final_response(),
        ]

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=model_responses,
            ),
            patch.object(agent, "write_project_file") as mock_write,
            patch.object(agent, "run_python") as mock_python,
            patch.object(agent, "calculator") as mock_calculator,
        ):
            answer = agent.run_agent(
                "测试未知工具不能触发已知工具",
                event_callback=events.append,
            )

        mock_write.assert_not_called()
        mock_python.assert_not_called()
        mock_calculator.assert_not_called()
        self.assertEqual(answer, "测试完成")
        self.assertTrue(any(
            "未知工具" in event.get("message", "")
            for event in events
        ))


    def test_max_model_turns_stops_agent(self):
        events = []

        with patch.object(
            agent,
            "call_llm",
            return_value={
                "message": {
                    "content": "我将修复代码，现在修复，需要继续验证。"
                }
            },
        ) as mock_llm:
            answer = agent.run_agent(
                "测试最大模型轮数限制",
                event_callback=events.append,
            )

        self.assertEqual(
            mock_llm.call_count,
            8,
            "Agent 应在达到最大模型轮数后停止请求模型",
        )
        self.assertIn(
            "任务未能在最大请求轮数内完成",
            answer,
            "达到上限后应明确告知任务尚未完成",
        )
        self.assertTrue(
            any(
                "最大请求轮数" in event.get("message", "")
                for event in events
            ),
            "达到上限时应发出限制事件",
        )

    def test_failed_write_blocks_python_with_equivalent_normalized_path(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                }),
                tool_call("run_python", {
                    "code": "print('should not run')",
                    "files": ["src/../demo.py"],
                    "entry_file": "src/../demo.py",
                }),
            ),
            model_final_response("文件已成功修改，任务完成。"),
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=fake_llm,
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={
                    "success": False,
                    "path": "demo.py",
                    "message": "写入文件失败：模拟权限错误",
                },
            ),
            patch.object(
                agent,
                "run_python",
            ) as mock_python,
        ):
            answer = agent.run_agent("请修改并执行 demo.py")

        mock_python.assert_not_called()
        self.assertNotIn("文件已成功修改", answer)
        self.assertIn("写入失败", answer)

    def test_failed_write_does_not_claim_success(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                })
            ),
            model_final_response(
                "文件已成功修改，任务完成。"
            ),
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=fake_llm,
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={"success": False, "path": "demo.py", "message": "写入文件失败：模拟权限错误"},
            ),
        ):
            answer = agent.run_agent(
                "请修改 demo.py"
            )

        self.assertNotIn(
            "文件已成功修改",
            answer,
            "文件写入失败时，Agent 不应向用户报告修改成功。",
        )
    def test_failed_write_blocks_success_claim_at_debug_limit(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                })
            ),
            model_tool_response(
                tool_call("run_python", {
                    "code": "print('debug')",
                    "files": [],
                    "entry_file": "",
                })
            ),
            model_tool_response(
                tool_call("run_python", {
                    "code": "print('debug')",
                    "files": [],
                    "entry_file": "",
                })
            ),
            model_tool_response(
                tool_call("run_python", {
                    "code": "print('debug')",
                    "files": [],
                    "entry_file": "",
                })
            ),
            model_final_response("文件已成功修改，任务完成。"),
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=fake_llm,
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={"success": False, "path": "demo.py", "message": "写入文件失败：模拟权限错误"},
            ),
            patch.object(
                agent,
                "run_python",
                return_value="执行成功：模拟输出",
            ),
        ):
            answer = agent.run_agent("请修改并测试 demo.py")

        self.assertNotIn("文件已成功修改", answer)
        self.assertIn("写入失败", answer)

    def test_failed_write_does_not_claim_success_with_alternate_wording(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                })
            ),
            model_final_response("已经处理好了，文件可以直接使用。"),
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=fake_llm,
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={"success": False, "path": "demo.py", "message": "写入文件失败：模拟权限错误"},
            ),
        ):
            answer = agent.run_agent("请修改 demo.py")

        self.assertNotIn("已经处理好了", answer)
        self.assertIn("写入失败", answer)

    def test_tool_failure_is_reported_to_model(self):
        captured_messages = []
        model_responses = [
            model_tool_response(
                tool_call("calculator", {"expression": "1+1"})
            ),
            model_final_response("工具执行失败，任务未完成。"),
        ]

        def fake_llm(messages, tools=None):
            captured_messages.append(messages.copy())
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(agent, "call_llm", side_effect=fake_llm),
            patch.object(
                agent,
                "calculator",
                side_effect=RuntimeError("模拟工具内部异常"),
            ),
        ):
            answer = agent.run_agent("测试工具失败后的处理")

        self.assertTrue(captured_messages[1:])
        tool_messages = [
            message
            for message in captured_messages[1][-3:]
            if message.get("role") == "tool"
        ]
        self.assertTrue(
            any(
                "工具 calculator 执行失败" in message.get("content", "")
                for message in tool_messages
            ),
            "后续模型消息应包含通用工具失败提示",
        )
        self.assertEqual(answer, "工具执行失败，任务未完成。")

    def test_tool_exception_details_are_not_sent_to_model(self):
        secret_detail = "/home/itadminn/private/internal-secret.txt"
        model_responses = [
            model_tool_response(
                tool_call("calculator", {"expression": "1+1"})
            ),
            model_final_response(),
        ]
        captured_messages = []

        def fake_llm(messages, tools=None):
            captured_messages.append(messages.copy())
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(agent, "call_llm", side_effect=fake_llm),
            patch.object(
                agent,
                "calculator",
                side_effect=RuntimeError(secret_detail),
            ),
        ):
            agent.run_agent("测试工具异常信息处理")

        subsequent_messages = captured_messages[1:]

        self.assertTrue(
            subsequent_messages,
            "应该存在工具执行后的后续模型请求",
        )
        self.assertNotIn(
            secret_detail,
            str(subsequent_messages),
            "内部异常路径不应进入后续模型消息",
        )


    def test_failed_write_blocks_python_with_absolute_path_alias(self):
        model_responses = [
            model_tool_response(
                tool_call("write_project_file", {
                    "file_path": "demo.py",
                    "content": "print('hello')",
                }),
                tool_call("run_python", {
                    "code": "print('should not run')",
                    "files": [
                        "/home/itadminn/ai-agent/demo.py"
                    ],
                    "entry_file": "",
                }),
            ),
            model_final_response("文件已成功修改，任务完成。"),
        ]

        def fake_llm(messages, tools=None):
            if model_responses:
                return model_responses.pop(0)
            raise AssertionError("模型响应次数超出预期")

        with (
            patch.object(
                agent,
                "call_llm",
                side_effect=fake_llm,
            ),
            patch.object(
                agent,
                "write_project_file_result",
                return_value={
                    "success": False,
                    "path": "demo.py",
                    "message": "写入文件失败：模拟权限错误",
                },
            ),
            patch.object(
                agent,
                "run_python",
            ) as mock_python,
        ):
            answer = agent.run_agent("请修改并执行 demo.py")

        mock_python.assert_not_called()
        self.assertNotIn("文件已成功修改", answer)
        self.assertIn("写入失败", answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
