import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.tools import python_tool


class FakePipe:
    def __init__(self, chunks=None):
        self.chunks = list(chunks or [])
        self.closed = False

    def read(self, size=-1):
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, stdout=None, stderr=None):
        self.stdout = stdout or FakePipe()
        self.stderr = stderr or FakePipe()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeSelector:
    def __init__(self, mode):
        self.mode = mode
        self.keys = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def register(self, fileobj, events, data=None):
        self.keys[fileobj] = SimpleNamespace(
            fileobj=fileobj,
            data=data,
        )

    def get_map(self):
        return self.keys

    def unregister(self, fileobj):
        self.keys.pop(fileobj, None)

    def select(self, timeout=None):
        if self.mode == "error":
            raise RuntimeError("simulated selector failure")

        if self.mode == "timeout":
            return []

        # 输出超限测试持续读取 stdout。
        for key in self.keys.values():
            if key.data == "stdout":
                return [(key, 1)]

        return []


class PythonToolCleanupTests(unittest.TestCase):
    def setUp(self):
        self.command = [
            "docker", "run", "--rm",
            "--network", "none",
            python_tool.DOCKER_IMAGE,
            "python", "-c", "pass",
        ]

    def run_with_fake_process(self, mode, stdout_chunks=None):
        process = FakeProcess(
            stdout=FakePipe(stdout_chunks),
            stderr=FakePipe(),
        )
        selector = FakeSelector(mode)

        return process, selector

    def test_output_overflow_triggers_cleanup(self):
        chunks = [b"x" * 65536 for _ in range(17)]
        process, selector = self.run_with_fake_process(
            "overflow",
            chunks,
        )

        with (
            patch.object(
                python_tool.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                python_tool.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            patch.object(
                python_tool,
                "_stop_docker_process",
            ) as cleanup,
        ):
            with self.assertRaises(python_tool.OutputLimitExceeded):
                python_tool._run_docker_limited(
                    self.command,
                    timeout=10,
                    max_output_bytes=1024 * 1024,
                )

        cleanup.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
    def test_combined_stdout_stderr_output_limit(self):
        limit = 1024 * 1024

        stdout_chunks = [b"x" * 65536 for _ in range(8)]
        stderr_chunks = [b"y" * 65536 for _ in range(9)]

        process = FakeProcess(
            stdout=FakePipe(stdout_chunks),
            stderr=FakePipe(stderr_chunks),
        )
        # 模拟 Docker 客户端在输出管道读完后正常退出。
        process.returncode = 0
        selector = FakeSelector("overflow")

        def select_both(timeout=None):
            return [
                (key, 1)
                for key in list(selector.keys.values())
            ]

        selector.select = select_both

        with (
            patch.object(
                python_tool.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                python_tool.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            patch.object(
                python_tool,
                "_stop_docker_process",
            ) as cleanup,
        ):
            with self.assertRaises(python_tool.OutputLimitExceeded):
                python_tool._run_docker_limited(
                    self.command,
                    timeout=10,
                    max_output_bytes=limit,
                )

        cleanup.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_timeout_triggers_cleanup(self):
        process, selector = self.run_with_fake_process("timeout")

        with (
            patch.object(
                python_tool.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                python_tool.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            patch.object(
                python_tool.time,
                "monotonic",
                side_effect=[0, 20],
            ),
            patch.object(
                python_tool,
                "_stop_docker_process",
            ) as cleanup,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                python_tool._run_docker_limited(
                    self.command,
                    timeout=10,
                )

        cleanup.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_unexpected_exception_triggers_cleanup(self):
        process, selector = self.run_with_fake_process("error")

        with (
            patch.object(
                python_tool.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                python_tool.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            patch.object(
                python_tool,
                "_stop_docker_process",
            ) as cleanup,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated selector failure",
            ):
                python_tool._run_docker_limited(
                    self.command,
                    timeout=10,
                )

        cleanup.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_cleanup_error_does_not_replace_original_error(self):
        process, selector = self.run_with_fake_process("error")

        with (
            patch.object(
                python_tool.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                python_tool.selectors,
                "DefaultSelector",
                return_value=selector,
            ),
            patch.object(
                python_tool,
                "_stop_docker_process",
                side_effect=OSError("simulated cleanup failure"),
            ) as cleanup,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated selector failure",
            ):
                python_tool._run_docker_limited(
                    self.command,
                    timeout=10,
                )

        cleanup.assert_called_once()


    def test_kill_is_attempted_when_terminate_fails(self):
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError(
            "simulated terminate failure"
        )

        container_name = "ai-agent-python-kill-fallback-test"
        docker_result = SimpleNamespace(
            returncode=0,
            stderr="",
        )

        with (
            patch.object(
                python_tool.subprocess,
                "run",
                return_value=docker_result,
            ),
            patch.object(
                python_tool.logger,
                "exception",
            ),
        ):
            python_tool._stop_docker_process(
                process,
                container_name,
            )

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        process.wait.assert_called()

    def test_container_cleanup_runs_when_kill_fails(self):
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError(
            "simulated terminate failure"
        )
        process.kill.side_effect = OSError(
            "simulated kill failure"
        )

        container_name = "ai-agent-python-kill-failure-test"
        docker_result = SimpleNamespace(
            returncode=0,
            stderr="",
        )

        with (
            patch.object(
                python_tool.subprocess,
                "run",
                return_value=docker_result,
            ) as docker_run,
            patch.object(
                python_tool.logger,
                "exception",
            ),
        ):
            python_tool._stop_docker_process(
                process,
                container_name,
            )

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        docker_run.assert_called_once_with(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

    def test_container_cleanup_runs_when_terminate_fails(self):
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError(
            "simulated terminate failure"
        )

        container_name = "ai-agent-python-test"
        docker_result = SimpleNamespace(
            returncode=0,
            stderr="",
        )

        with patch.object(
            python_tool.subprocess,
            "run",
            return_value=docker_result,
        ) as docker_run:
            python_tool._stop_docker_process(
                process,
                container_name,
            )

        docker_run.assert_called_once_with(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )


    def test_container_cleanup_nonzero_exit_logs_details(self):
        process = Mock()
        process.poll.return_value = 0

        container_name = "ai-agent-python-cleanup-test"
        docker_result = SimpleNamespace(
            returncode=1,
            stderr="simulated docker cleanup failure",
        )

        with (
            patch.object(
                python_tool.subprocess,
                "run",
                return_value=docker_result,
            ) as docker_run,
            patch.object(
                python_tool.logger,
                "warning",
            ) as log_warning,
        ):
            python_tool._stop_docker_process(
                process,
                container_name,
            )

    def test_container_cleanup_nonzero_exit_logs_details(self):
        process = Mock()
        process.poll.return_value = 0

        container_name = "ai-agent-python-cleanup-test"
        docker_result = SimpleNamespace(
            returncode=1,
            stderr="simulated docker cleanup failure",
        )

        with (
            patch.object(
                python_tool.subprocess,
                "run",
                return_value=docker_result,
            ) as docker_run,
            patch.object(
                python_tool.logger,
                "warning",
            ) as log_warning,
        ):
            python_tool._stop_docker_process(
                process,
                container_name,
            )

            docker_run.assert_called_once()
            log_warning.assert_called_once()

            log_message = log_warning.call_args.args[0]
            log_args = log_warning.call_args.args[1:]
            formatted_message = log_message % log_args

            self.assertIn(container_name, formatted_message)
            self.assertIn("1", formatted_message)
            self.assertIn(
                "simulated docker cleanup failure",
                formatted_message,
            )

    def test_container_cleanup_exception_is_logged(self):
        process = Mock()
        process.poll.return_value = 0

        container_name = "ai-agent-python-cleanup-exception-test"

        with (
            patch.object(
                python_tool.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["docker", "rm", "-f", container_name],
                    timeout=3,
                ),
            ) as docker_run,
            patch.object(
                python_tool.logger,
                "exception",
            ) as log_exception,
        ):
            python_tool._stop_docker_process(
                process,
                container_name,
            )

        docker_run.assert_called_once_with(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        log_exception.assert_called_once()

        log_message = log_exception.call_args.args[0]
        log_args = log_exception.call_args.args[1:]
        formatted_message = log_message % log_args
        self.assertIn("执行 Docker 容器清理命令时发生异常", formatted_message)
        self.assertIn(container_name, formatted_message)





if __name__ == "__main__":
    unittest.main(verbosity=2)
