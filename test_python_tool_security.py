import tempfile
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tools import python_tool


class PythonToolSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name) / "ai-agent"
        self.root.mkdir()

        self.project_root_patch = patch.object(
            python_tool, "PROJECT_ROOT", self.root
        )
        self.project_root_patch.start()
        self.addCleanup(self.project_root_patch.stop)

    def mock_docker(self, *args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="MOCK EXECUTION",
            stderr="",
        )

    def test_env_file_is_not_copied(self):
        secret = self.root / ".env"
        secret.write_text("TEST_SECRET=not-a-real-secret", encoding="utf-8")

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=[".env"],
            )

        if docker.called:
            print("发现问题：.env 未被拒绝，Docker 调用已发生。")
        else:
            print("通过：.env 在启动 Docker 前被拒绝。")

        self.assertFalse(
            docker.called,
            f".env 未被拒绝，返回内容：{result}",
        )

    def test_env_variants_are_rejected(self):
        filenames = [
            ".env.development",
            ".env.test",
            ".env.staging",
            ".env.backup",
            ".env.production.local",
        ]

        for filename in filenames:
            with self.subTest(filename=filename):
                secret = self.root / filename
                secret.write_text(
                    "TEST_SECRET=not-a-real-secret",
                    encoding="utf-8",
                )

                with patch.object(
                    python_tool,
                    "_run_docker_limited",
                    side_effect=self.mock_docker,
                ) as docker:
                    result = python_tool.run_python(
                        code="print('test')",
                        files=[filename],
                    )

                self.assertFalse(
                    docker.called,
                    f"{filename} 未被拒绝，返回内容：{result}",
                )

                secret.unlink()

    def test_backup_directory_is_not_copied(self):
        backup_dir = self.root / ".agent_backups"
        backup_dir.mkdir()
        backup_file = backup_dir / "sample.py"
        backup_file.write_text("print('test')", encoding="utf-8")

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=[".agent_backups/sample.py"],
            )

        if docker.called:
            print("发现问题：.agent_backups 中的文件未被拒绝。")
        else:
            print("通过：备份目录在启动 Docker 前被拒绝。")

        self.assertFalse(
            docker.called,
            f".agent_backups 未被拒绝，返回内容：{result}",
        )

    def test_parent_path_is_rejected(self):
        outside = self.root.parent / "outside.py"
        outside.write_text("print('test')", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=["../outside.py"],
            )

        self.assertFalse(
            docker.called,
            f"父目录路径未被拒绝，返回内容：{result}",
        )

    def test_entry_file_sensitive_path_is_rejected(self):
        secret = self.root / ".env"
        secret.write_text("TEST_SECRET=not-a-real-secret", encoding="utf-8")

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="",
                entry_file=".env",
            )

        self.assertFalse(
            docker.called,
            f"敏感入口文件未被拒绝，返回内容：{result}",
        )


    def test_symlink_to_outside_project_is_rejected(self):
        outside = Path(self.temp_dir.name) / "outside.py"
        outside.write_text("print('outside')", encoding="utf-8")

        link = self.root / "outside_link.py"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"当前环境无法创建符号链接：{exc}")

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=["outside_link.py"],
            )

        self.assertFalse(
            docker.called,
            f"指向项目外部的符号链接未被拒绝，返回内容：{result}",
        )

    def test_windows_style_relative_path_is_normalized(self):
        folder = self.root / "subdir"
        folder.mkdir()
        demo = folder / "demo.py"
        demo.write_text("print('demo')", encoding="utf-8")

        resolved = python_tool._resolve_python_project_path(
            r"subdir\\demo.py"
        )

        self.assertEqual(resolved, demo.resolve())


    def test_run_python_code_is_not_required(self):
        tool = next(
            item["function"]
            for item in __import__("app.agent", fromlist=["TOOLS"]).TOOLS
            if item["function"]["name"] == "run_python"
        )

        self.assertNotIn(
            "code",
            tool["parameters"].get("required", []),
            "run_python 应允许只提供 entry_file。",
        )

    def test_empty_code_without_entry_file_is_rejected(self):
        with patch.object(
            python_tool, "_run_docker_limited"
        ) as docker:
            result = python_tool.run_python(
                code="",
                entry_file="",
            )

        self.assertIn("错误", result)
        self.assertFalse(
            docker.called,
            "没有执行目标时，不应启动 Docker。",
        )
    def test_normal_project_file_still_works(self):
        demo = self.root / "demo.py"
        demo.write_text("print('demo')", encoding="utf-8")

        with patch.object(
            python_tool, "_run_docker_limited", side_effect=self.mock_docker
        ) as docker:
            result = python_tool.run_python(
                code="",
                entry_file="demo.py",
            )

        self.assertTrue(docker.called, "正常项目文件没有进入执行流程。")
        self.assertIn("执行成功", result)

        command = docker.call_args.args[0]
        self.assertEqual(command[-2:], [
            "python",
            "/sandbox/project/demo.py",
        ])

    def test_docker_security_arguments_are_configured(self):
        with patch.object(
            python_tool,
            "_run_docker_limited",
            side_effect=self.mock_docker,
        ) as docker:
            result = python_tool.run_python(
                code="print('security test')",
            )

        self.assertIn("执行成功", result)
        self.assertTrue(docker.called)

        command = docker.call_args.args[0]

        expected_arguments = [
            "--user", "65534:65534",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--network", "none",
            "--cpus", "0.5",
            "--memory", "128m",
            "--pids-limit", "64",
            ]

        for argument in expected_arguments:
            with self.subTest(argument=argument):
                self.assertIn(
                    argument,
                    command,
                    f"Docker 命令缺少安全参数：{argument}",
                )

        self.assertTrue(
            any(
                item.endswith(":/sandbox:ro")
                for item in command
                if isinstance(item, str)
            ),
            "Docker 项目目录应以只读方式挂载。",
        )

    def test_timeout_returns_clear_error(self):
        with patch.object(
            python_tool,
            "_run_docker_limited",
            side_effect=subprocess.TimeoutExpired(
                cmd=["docker", "run"],
                timeout=10,
            ),
        ):
            result = python_tool.run_python(
                code="print('timeout test')",
            )

        self.assertIn("执行失败", result)
        self.assertIn("超过 10 秒", result)


    def test_oversized_project_file_is_rejected_before_docker(self):
        filename = "large.py"
        large_file = self.root / filename
        large_file.write_bytes(b"x" * 200_001)

        with patch.object(
            python_tool,
            "_run_docker_limited",
            side_effect=self.mock_docker,
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=[filename],
            )

        self.assertFalse(
            docker.called,
            f"超大项目文件未在启动 Docker 前被拒绝：{result}",
        )

    def test_total_project_files_size_is_limited_before_docker(self):
        filenames = []

        for index in range(6):
            filename = f"sample_{index}.py"
            (self.root / filename).write_bytes(b"x" * 180_000)
            filenames.append(filename)

        total_size = sum(
            (self.root / filename).stat().st_size
            for filename in filenames
        )
        self.assertGreater(total_size, 1024 * 1024)

        with patch.object(
            python_tool,
            "_run_docker_limited",
            side_effect=self.mock_docker,
        ) as docker:
            result = python_tool.run_python(
                code="print('test')",
                files=filenames,
            )

        self.assertFalse(
            docker.called,
            f"累计超限的项目文件未在启动 Docker 前被拒绝：{result}",
        )


    def test_file_growth_before_copy_is_rejected(self):
        filename = "growing.py"
        source_file = self.root / filename
        source_file.write_bytes(b"x" * 100)

        real_copy = python_tool._copy_project_file_limited

        def grow_file_then_copy(src, dst, max_bytes):
            Path(src).write_bytes(b"x" * 200_001)
            return real_copy(src, dst, max_bytes)

        with (
            patch.object(
                python_tool,
                "_copy_project_file_limited",
                side_effect=grow_file_then_copy,
            ),
            patch.object(
                python_tool,
                "_run_docker_limited",
                side_effect=self.mock_docker,
            ) as docker,
        ):
            result = python_tool.run_python(
                code="print('test')",
                files=[filename],
            )

        self.assertFalse(
            docker.called,
            f"文件增长后仍启动了 Docker：{result}",
        )
        self.assertIn(
            "错误",
            result,
            f"文件增长后应返回错误：{result}",
        )


    def test_copy_failure_removes_partial_destination(self):
        source_file = self.root / "source.py"
        source_file.write_bytes(b"partial content")

        destination = self.root / "copied.py"
        real_path_open = Path.open

        class FailingReader:
            def __init__(self, file_obj):
                self.file_obj = file_obj
                self.read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.file_obj.close()

            def read(self, size=-1):
                self.read_count += 1
                if self.read_count > 1:
                    raise OSError("simulated read failure")
                return self.file_obj.read(size)

        def patched_open(path, *args, **kwargs):
            file_obj = real_path_open(path, *args, **kwargs)
            if path == source_file and args and args[0] == "rb":
                return FailingReader(file_obj)
            return file_obj

        with patch.object(Path, "open", new=patched_open):
            with self.assertRaises(OSError):
                python_tool._copy_project_file_limited(
                    source_file,
                    destination,
                    200_000,
                )

        self.assertFalse(
            destination.exists(),
            "复制失败后，不完整的目标文件应被删除。",
        )


    def test_cleanup_failure_preserves_original_copy_error(self):
        source_file = self.root / "source.py"
        source_file.write_bytes(b"partial content")
        destination = self.root / "copied.py"

        real_path_open = Path.open

        class FailingReader:
            def __init__(self, file_obj):
                self.file_obj = file_obj
                self.read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.file_obj.close()

            def read(self, size=-1):
                self.read_count += 1
                if self.read_count > 1:
                    raise OSError("simulated read failure")
                return self.file_obj.read(size)

        def patched_open(path, *args, **kwargs):
            file_obj = real_path_open(path, *args, **kwargs)
            if path == source_file and args and args[0] == "rb":
                return FailingReader(file_obj)
            return file_obj

        with (
            patch.object(Path, "open", new=patched_open),
            patch.object(
                Path,
                "unlink",
                side_effect=OSError("simulated cleanup failure"),
            ),
            patch.object(python_tool.logger, "exception") as log_exception,
        ):
            with self.assertRaisesRegex(
                OSError, "simulated read failure"
            ):
                python_tool._copy_project_file_limited(
                    source_file,
                    destination,
                    200_000,
                )

        log_exception.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
