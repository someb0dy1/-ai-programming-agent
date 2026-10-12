import subprocess
import tempfile
from pathlib import Path
import shutil
import re
import selectors
import time
import uuid
import logging

logger = logging.getLogger(__name__)

DOCKER_IMAGE = "python:3.12-slim"
PROJECT_ROOT = (Path.home() / "ai-agent").resolve()

FORBIDDEN_PARTS = {
    "venv",
    "__pycache__",
    ".git",
    "logs",
    ".agent_backups",
}

FORBIDDEN_FILES = {
    ".env",
    ".env.local",
    ".env.production",
}


def _resolve_python_project_path(file_path: str) -> Path:
    """校验项目相对路径，拒绝敏感目标、符号链接和项目外路径。"""
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    normalized = file_path.replace("\\", "/")

    if re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("不允许使用 Windows 盘符路径。")

    relative = Path(normalized)

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("只允许使用项目目录内的相对路径。")

    current = PROJECT_ROOT
    for part in relative.parts:
        if part in ("", "."):
            continue
        current = current / part
        if current.is_symlink():
            raise ValueError("不允许通过符号链接访问文件。")

    resolved = (PROJECT_ROOT / relative).resolve()

    if resolved == PROJECT_ROOT or PROJECT_ROOT not in resolved.parents:
        raise ValueError("禁止访问项目目录之外的路径。")

    safe_relative = resolved.relative_to(PROJECT_ROOT)

    if any(part in FORBIDDEN_PARTS for part in safe_relative.parts):
        raise ValueError("禁止访问受保护目录。")

    if (
        resolved.name in FORBIDDEN_FILES
        or resolved.name == ".env"
        or resolved.name.startswith(".env.")
    ):
        raise ValueError("禁止访问敏感配置文件。")

    return resolved

MAX_OUTPUT_BYTES = 1024 * 1024
MAX_PROJECT_FILE_SIZE = 200_000
MAX_PROJECT_TOTAL_SIZE = 1024 * 1024
EXECUTION_TIMEOUT = 10


class OutputLimitExceeded(Exception):
    """Python 程序输出超过允许的大小。"""


class ProjectFileSizeLimitExceeded(Exception):
    """项目文件在复制过程中超过允许的字节数。"""



def _copy_project_file_limited(
    source: Path,
    destination: Path,
    max_bytes: int,
) -> int:
    """限制实际复制的字节数；失败时尽力删除不完整的目标文件。"""
    copied = 0

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        with source.open("rb") as source_file:
            with destination.open("wb") as destination_file:
                while True:
                    remaining = max_bytes - copied

                    # 最多额外读取 1 字节，以检测是否超过限制。
                    chunk = source_file.read(min(64 * 1024, remaining + 1))

                    if not chunk:
                        break

                    if len(chunk) > remaining:
                        raise ProjectFileSizeLimitExceeded(
                            "项目文件在复制过程中超过大小限制。"
                        )

                    destination_file.write(chunk)
                    copied += len(chunk)

        return copied

    except Exception:
        # 不让清理异常覆盖原始复制异常。
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "删除不完整的项目文件副本失败：%s",
                destination,
            )

        raise




def _stop_docker_process(process, container_name: str) -> None:
    """尽力终止 Docker 客户端，并始终尝试清理对应容器。"""

    def force_kill() -> None:
        try:
            process.kill()
            process.wait(timeout=1)
        except Exception:
            logger.exception(
                "强制终止 Docker 客户端时发生异常：container=%s",
                container_name,
            )

    try:
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                logger.exception(
                    "终止 Docker 客户端时发生异常，尝试强制终止：container=%s",
                    container_name,
                )
                force_kill()
            else:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "等待 Docker 客户端退出超时，尝试强制终止：container=%s",
                        container_name,
                    )
                    force_kill()
                except Exception:
                    logger.exception(
                        "等待 Docker 客户端退出时发生异常：container=%s",
                        container_name,
                    )
                    force_kill()
    except Exception:
        logger.exception(
            "检查 Docker 客户端进程状态时发生异常：container=%s",
            container_name,
        )
    finally:
        try:
            result = subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )

            if result.returncode != 0:
                logger.warning(
                    "Docker 容器清理命令返回非零退出码：container=%s, "
                    "returncode=%s, stderr=%s",
                    container_name,
                    result.returncode,
                    (result.stderr or "").strip()[:1000],
                )
        except Exception:
            logger.exception(
                "执行 Docker 容器清理命令时发生异常：container=%s",
                container_name,
            )


def _run_docker_limited(
    command: list[str],
    timeout: int = EXECUTION_TIMEOUT,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
) -> subprocess.CompletedProcess:
    """执行 Docker 命令，并限制标准输出和错误输出的大小。"""
    container_name = f"ai-agent-python-{uuid.uuid4().hex}"

    docker_command = list(command)
    docker_command[2:2] = ["--name", container_name]

    process = subprocess.Popen(
        docker_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    deadline = time.monotonic() + timeout

    try:
        with selectors.DefaultSelector() as selector:
            selector.register(
                process.stdout,
                selectors.EVENT_READ,
                "stdout",
            )
            selector.register(
                process.stderr,
                selectors.EVENT_READ,
                "stderr",
            )

            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        docker_command,
                        timeout,
                        output=bytes(stdout_buffer),
                        stderr=bytes(stderr_buffer),
                    )

                if selector.get_map():
                    events = selector.select(min(remaining, 0.1))
                else:
                    time.sleep(min(remaining, 0.05))
                    events = []

                for key, _ in events:
                    chunk = key.fileobj.read(65536)

                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue

                    if (
                        len(stdout_buffer)
                        + len(stderr_buffer)
                        + len(chunk)
                        > max_output_bytes
                    ):
                        raise OutputLimitExceeded(
                            "标准输出和错误输出合计超过大小限制。"
                        )

                    buffer = (
                        stdout_buffer
                        if key.data == "stdout"
                        else stderr_buffer
                    )
                    buffer.extend(chunk)

        return subprocess.CompletedProcess(
            docker_command,
            process.wait(),
            stdout_buffer.decode("utf-8", errors="replace"),
            stderr_buffer.decode("utf-8", errors="replace"),
        )

    except BaseException:
        try:
            _stop_docker_process(process, container_name)
        except Exception:
            # 清理过程发生异常时，保留原始执行异常。
            pass
        raise
    finally:
        # 无论执行成功还是失败，都关闭尚未关闭的输出管道。
        for pipe in (process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()


def run_python(code: str = "", files=None, entry_file: str = "") -> str:
    try:
        if not isinstance(code, str):
            return "错误：code 必须是字符串。"

        if not isinstance(entry_file, str):
            return "错误：entry_file 必须是字符串。"

        if not code.strip() and not entry_file.strip():
            return "错误：必须提供非空的 Python 代码或入口文件。"

        if code.strip() and entry_file.strip():
            return "错误：不能同时提供非空的 code 和 entry_file，请选择一种执行方式。"

        if files is None:
            files = []

        if not isinstance(files, list) or not all(
            isinstance(item, str) and item.strip()
            for item in files
        ):
            return "错误：files 必须是非空字符串组成的列表。"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # 允许容器内的非 root 用户穿过只读挂载目录。
            temp_path.chmod(0o755)

            script_path = temp_path / "main.py"
            script_path.write_text(code, encoding="utf-8")

            project_path = temp_path / "project"
            project_path.mkdir()

            # 校验并复制需要使用的项目文件。
            validated_files = {}
            for file_path in files:
                source = _resolve_python_project_path(file_path)

                if not source.is_file():
                    return f"错误：项目文件不存在：{file_path}"

                relative_path = source.relative_to(PROJECT_ROOT)
                validated_files[str(relative_path)] = source

            validated_entry = None
            if entry_file:
                validated_entry = _resolve_python_project_path(entry_file)

                if not validated_entry.is_file():
                    return f"错误：入口文件不存在：{entry_file}"

                entry_relative = validated_entry.relative_to(PROJECT_ROOT)
                validated_files[str(entry_relative)] = validated_entry

            # 在复制前检查所有项目文件的大小。
            total_project_size = 0

            for relative_text, source in validated_files.items():
                file_size = source.stat().st_size

                if file_size > MAX_PROJECT_FILE_SIZE:
                    return (
                        "错误：项目文件超过单文件大小限制"
                        f"（{MAX_PROJECT_FILE_SIZE} 字节）：{relative_text}"
                    )

                total_project_size += file_size

                if total_project_size > MAX_PROJECT_TOTAL_SIZE:
                    return (
                        "错误：项目文件总大小超过限制"
                        f"（{MAX_PROJECT_TOTAL_SIZE} 字节）。"
                    )

            # 所有文件通过初始检查后，再进行有字节数上限的复制。
            copied_total = 0

            for relative_text, source in validated_files.items():
                relative_path = Path(relative_text)
                destination = project_path / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)

                remaining_total = MAX_PROJECT_TOTAL_SIZE - copied_total
                copy_limit = min(
                    MAX_PROJECT_FILE_SIZE,
                    remaining_total,
                )

                try:
                    copied_size = _copy_project_file_limited(
                        source,
                        destination,
                        copy_limit,
                    )
                except ProjectFileSizeLimitExceeded:
                    return (
                        "错误：项目文件在复制过程中超过大小限制。"
                        f"单文件上限为 {MAX_PROJECT_FILE_SIZE} 字节，"
                        f"项目总大小上限为 {MAX_PROJECT_TOTAL_SIZE} 字节。"
                    )

                copied_total += copied_size

            if validated_entry is not None:
                entry_relative = validated_entry.relative_to(PROJECT_ROOT)
                command = [
                    "python",
                    f"/sandbox/project/{entry_relative.as_posix()}"
                ]
            else:
                command = [
                    "python",
                    "/sandbox/main.py"
                ]

            docker_command = [
                "docker",
                "run",
                "--rm",
                "--user",
                "65534:65534",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
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
            ] + command

            result = _run_docker_limited(
                docker_command,
                timeout=EXECUTION_TIMEOUT,
                max_output_bytes=MAX_OUTPUT_BYTES,
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

    except OutputLimitExceeded:
        return (
            "执行失败\n"
            "Python 程序输出超过 1 MiB 限制，已终止执行。"
        )

    except subprocess.TimeoutExpired:
        return "执行失败\nPython 程序执行超过 10 秒，已终止。"

    except Exception as e:
        return f"执行失败\nPython Tool 异常：{e}"