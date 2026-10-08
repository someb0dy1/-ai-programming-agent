import subprocess
import tempfile
from pathlib import Path
import shutil

DOCKER_IMAGE = "python:3.12-slim"
PROJECT_ROOT = Path.home() / "ai-agent"


def run_python(code: str = "", files=None, entry_file: str = "") -> str:
    try:
        files = files or []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            script_path = temp_path / "main.py"
            script_path.write_text(code, encoding="utf-8")

            project_path = temp_path / "project"
            project_path.mkdir()

            # 复制需要使用的项目文件
            for file_path in files:
                source = (PROJECT_ROOT / file_path).resolve()

                if PROJECT_ROOT not in source.parents:
                    return f"错误：禁止访问项目目录之外的文件：{file_path}"

                if not source.is_file():
                    return f"错误：项目文件不存在：{file_path}"

                relative_path = source.relative_to(PROJECT_ROOT)

                if any(
                    part in {"venv", "__pycache__", ".git", "logs"}
                    for part in relative_path.parts
                ):
                    return f"错误：禁止使用受保护目录中的文件：{file_path}"

                destination = project_path / relative_path
                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                shutil.copy2(source, destination)

            # 如果指定 entry_file，必须确保它也在 files 中
            if entry_file:
                entry_source = (PROJECT_ROOT / entry_file).resolve()

                if PROJECT_ROOT not in entry_source.parents:
                    return f"错误：禁止访问项目目录之外的文件：{entry_file}"

                if not entry_source.is_file():
                    return f"错误：入口文件不存在：{entry_file}"

                entry_relative = entry_source.relative_to(PROJECT_ROOT)

                if any(
                    part in {"venv", "__pycache__", ".git", "logs"}
                    for part in entry_relative.parts
                ):
                    return f"错误：禁止执行受保护目录中的文件：{entry_file}"

                entry_destination = project_path / entry_relative
                entry_destination.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                # 如果 entry_file 不在 files 中，则自动复制
                if not entry_destination.exists():
                    shutil.copy2(
                        entry_source,
                        entry_destination
                    )

            if entry_file:
                command = [
                    "python",
                    f"/sandbox/project/{entry_file}"
                ]
            else:
                command = [
                    "python",
                    "/sandbox/main.py"
                ]

            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cpus",
                    "0.5",
                    "--memory",
                    "128m",
                    "--pids-limit",
                    "64",
                    "-v",
                    f"{temp_dir}:/sandbox:ro",
                    "-e",
                    "PYTHONPATH=/sandbox/project",
                    DOCKER_IMAGE,
                ]
                + command,
                capture_output=True,
                text=True,
                timeout=10
            )

            output = result.stdout.strip()
            error = result.stderr.strip()

            if result.returncode == 0:
                if output:
                    return (
                        "执行成功\n"
                        f"输出：\n{output}"
                    )

                return (
                    "执行成功\n"
                    "程序没有输出内容。"
                )

            return (
                "执行失败\n"
                f"退出码：{result.returncode}\n"
                f"错误信息：\n{error}"
            )

    except subprocess.TimeoutExpired:
        return "执行失败\nPython 程序执行超过 10 秒，已终止。"

    except Exception as e:
        return f"执行失败\nPython Tool 异常：{e}"