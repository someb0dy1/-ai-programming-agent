from datetime import datetime
from pathlib import Path
import shutil
import re
import os
import tempfile

PROJECT_ROOT = (Path.home() / "ai-agent").resolve()
BACKUP_ROOT = PROJECT_ROOT / ".agent_backups"

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

MAX_FILE_SIZE = 200_000


def _resolve_project_path(file_path: str) -> Path:
    """校验相对路径，并拒绝符号链接和项目目录外的路径。"""
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    # 统一 Windows 和 Linux 路径分隔符，避免反斜杠绕过校验。
    normalized_path = file_path.replace("\\", "/")

    if re.match(r"^[A-Za-z]:", normalized_path):
        raise ValueError("不允许使用 Windows 盘符路径。")

    relative_path = Path(normalized_path)


    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("只允许使用项目目录内的相对路径。")

    candidate = PROJECT_ROOT / relative_path

    # 拒绝路径中已有的符号链接，避免链接跳转到其他位置。
    current = PROJECT_ROOT
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("不允许通过符号链接访问文件。")

    resolved = candidate.resolve()

    if resolved == PROJECT_ROOT or PROJECT_ROOT not in resolved.parents:
        raise ValueError("禁止访问项目目录之外的路径。")

    return resolved


def _check_protected_path(path: Path) -> None:
    relative_path = path.relative_to(PROJECT_ROOT)

    if any(part in FORBIDDEN_PARTS for part in relative_path.parts):
        raise ValueError("禁止访问或修改受保护目录。")

    if path.name in FORBIDDEN_FILES:
        raise ValueError("禁止访问或修改敏感配置文件。")


def list_project_files() -> str:
    """列出 AI Agent 项目中的文件，排除受保护目录。"""
    try:
        files = []

        for path in PROJECT_ROOT.rglob("*"):
            relative_path = path.relative_to(PROJECT_ROOT)

            if any(part in FORBIDDEN_PARTS for part in relative_path.parts):
                continue

            # 不跟随符号链接。
            if path.is_symlink():
                continue

            if path.is_file():
                files.append(str(relative_path))

        if not files:
            return "项目中没有找到文件。"

        files.sort()
        return "项目文件列表：\n" + "\n".join(files)

    except Exception as e:
        return f"读取项目文件失败：{e}"


def read_project_file(file_path: str) -> str:
    """读取项目目录中的指定文件。"""
    try:
        requested_path = _resolve_project_path(file_path)
        _check_protected_path(requested_path)

        if not requested_path.is_file():
            return f"错误：文件不存在：{file_path}"

        if requested_path.stat().st_size > MAX_FILE_SIZE:
            return "错误：文件过大，不允许读取超过 200KB 的文件。"

        content = requested_path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        return f"文件：{file_path}\n内容：\n{content}"

    except Exception as e:
        return f"读取文件失败：{e}"



def _write_project_file_result(file_path: str, content: str) -> dict:
    """安全写入项目文件，并返回明确的结构化状态。"""
    temp_path = None

    def result(success: bool, message: str) -> dict:
        return {
            "success": success,
            "path": str(file_path) if isinstance(file_path, str) else "",
            "message": message,
        }

    try:
        if not isinstance(content, str):
            return result(False, "错误：文件内容必须是字符串。")

        requested_path = _resolve_project_path(file_path)
        _check_protected_path(requested_path)

        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            return result(
                False,
                "错误：文件内容过大，不允许写入超过 200KB 的内容。",
            )

        requested_path.parent.mkdir(parents=True, exist_ok=True)

        # 默认使用安全权限；覆盖现有文件时，保留原有权限模式。
        existing_mode = None

        if requested_path.exists():
            if not requested_path.is_file():
                return result(False, "错误：目标路径不是普通文件。")

            if requested_path.stat().st_size > MAX_FILE_SIZE:
                return result(False, "错误：目标文件超过 200KB，拒绝覆盖。")

            existing_mode = requested_path.stat().st_mode & 0o777

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=requested_path.parent,
            prefix=f".{requested_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())

            # 临时文件默认权限通常为 0600。
            # 覆盖现有文件时，尝试保留目标文件的权限模式。
            if existing_mode is not None:
                os.fchmod(temp_file.fileno(), existing_mode)

        # 写入临时文件后再次验证目标路径。
        requested_path = _resolve_project_path(file_path)
        _check_protected_path(requested_path)

        if requested_path.exists():
            if not requested_path.is_file():
                return result(False, "错误：目标路径不是普通文件。")

            if requested_path.stat().st_size > MAX_FILE_SIZE:
                return result(False, "错误：目标文件超过 200KB，拒绝覆盖。")

            relative_path = requested_path.relative_to(PROJECT_ROOT)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_path = BACKUP_ROOT / timestamp / relative_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(requested_path, backup_path)

        os.replace(temp_path, requested_path)
        temp_path = None

        return result(True, f"文件写入成功：{file_path}")

    except Exception as e:
        return result(False, f"写入文件失败：{e}")

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_project_file_result(file_path: str, content: str) -> dict:
    """公开的结构化写入接口。"""
    return _write_project_file_result(file_path, content)


def write_project_file(file_path: str, content: str) -> str:
    """兼容旧调用：仍返回字符串结果。"""
    return _write_project_file_result(file_path, content)["message"]
