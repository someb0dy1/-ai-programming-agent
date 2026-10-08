from pathlib import Path

PROJECT_ROOT = Path.home() / "ai-agent"


def list_project_files() -> str:
    """
    列出 AI Agent 项目中的文件。
    """

    try:
        files = []

        for path in PROJECT_ROOT.rglob("*"):
            if path.is_file():
                relative_path = path.relative_to(PROJECT_ROOT)

                # 排除虚拟环境、日志和缓存
                if any(
                    part in {"venv", "__pycache__", ".git", "logs"}
                    for part in relative_path.parts
                ):
                    continue

                files.append(str(relative_path))

        if not files:
            return "项目中没有找到文件。"

        files.sort()

        return "项目文件列表：\n" + "\n".join(files)

    except Exception as e:
        return f"读取项目文件失败：{e}"


def read_project_file(file_path: str) -> str:
    """
    读取 AI Agent 项目中的指定文件。
    """

    try:
        requested_path = (PROJECT_ROOT / file_path).resolve()

        # 安全检查：禁止访问 PROJECT_ROOT 之外的文件
        if PROJECT_ROOT not in requested_path.parents:
            return "错误：禁止访问项目目录之外的文件。"

        if not requested_path.is_file():
            return f"错误：文件不存在：{file_path}"

        # 限制单个文件大小
        if requested_path.stat().st_size > 200_000:
            return "错误：文件过大，暂时不允许读取超过 200KB 的文件。"

        content = requested_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return (
            f"文件：{file_path}\n"
            f"内容：\n"
            f"{content}"
        )

    except Exception as e:
        return f"读取文件失败：{e}"
def write_project_file(file_path: str, content: str) -> str:
    """
    修改 AI Agent 项目中的指定文件。
    """

    try:
        requested_path = (PROJECT_ROOT / file_path).resolve()

        # 安全检查：禁止访问 PROJECT_ROOT 之外的文件
        if PROJECT_ROOT not in requested_path.parents:
            return "错误：禁止写入项目目录之外的文件。"

        # 禁止修改敏感目录
        forbidden_parts = {"venv", "__pycache__", ".git", "logs"}

        relative_path = requested_path.relative_to(PROJECT_ROOT)

        if any(part in forbidden_parts for part in relative_path.parts):
            return "错误：禁止修改虚拟环境、缓存、Git 或日志目录。"

        # 禁止修改敏感文件
        forbidden_files = {
            ".env",
            ".env.local",
            ".env.production",
        }

        if requested_path.name in forbidden_files:
            return "错误：禁止修改敏感配置文件。"

        # 限制单个文件大小
        if len(content.encode("utf-8")) > 200_000:
            return "错误：文件内容过大，暂时不允许写入超过 200KB 的文件。"

        # 创建父目录
        requested_path.parent.mkdir(parents=True, exist_ok=True)

        requested_path.write_text(
            content,
            encoding="utf-8"
        )

        return f"文件写入成功：{file_path}"

    except Exception as e:
        return f"写入文件失败：{e}"