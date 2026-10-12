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


class DebugLimitIntegrationTest(unittest.TestCase):
    def test_skipped_python_does_not_consume_debug_quota(self):
        calls = [
            # 这个调用依赖写入失败的 demo.py，应当被跳过
            tool_call("run_python", {
                "code": "print('blocked')",
                "files": ["./demo.py"],
                "entry_file": "",
            }),
            tool_call("write_project_file", {
                "file_path": "demo.py",
                "content": "print('hello')",
            }),
            # 以下三个任务互不依赖，应当全部执行
            tool_call("run_python", {
                "code": "print(1)",
                "files": ["task1.py"],
                "entry_file": "",
            }),
            tool_call("run_python", {
                "code": "print(2)",
                "files": ["task2.py"],
                "entry_file": "",
            }),
            tool_call("run_python", {
                "code": "print(3)",
                "files": ["task3.py"],
                "entry_file": "",
            }),
        ]

        responses = [
            {
                "message": {
                    "content": "",
                    "tool_calls": calls,
                }
            },
            {"message": {"content": "测试完成"}},
        ]

        executed = []
        events = []

        def fake_llm(messages, tools=None):
            if not responses:
                raise AssertionError("模型响应次数超出预期")
            return responses.pop(0)

        def fake_write(file_path, content):
            return {
                "success": False,
                "message": "写入文件失败：模拟测试",
          }
        def fake_python(code, files, entry_file):
            executed.append(code)
            return "执行成功：模拟输出"

        with (
            patch.object(agent, "call_llm", side_effect=fake_llm),
            patch.object(agent, "write_project_file_result", side_effect=fake_write),
            patch.object(agent, "run_python", side_effect=fake_python),
        ):
            answer = agent.run_agent(
                "测试 Debug 次数",
                event_callback=events.append,
            )

        self.assertEqual(
            len(executed), 3,
            f"预期执行 3 次，实际执行 {len(executed)} 次：{executed}",
        )
        self.assertEqual(executed, ["print(1)", "print(2)", "print(3)"])
        self.assertEqual(
            sum(event["type"] == "sandbox" for event in events),
            3,
        )
        self.assertTrue(any(
            "已跳过 Python 执行" in event["message"]
            for event in events
        ))
        self.assertIn("demo.py", answer)
        self.assertIn("写入失败", answer)
        self.assertIn("无法确认", answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
