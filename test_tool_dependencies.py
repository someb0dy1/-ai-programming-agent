from pathlib import Path
import os
def normalize_path(path):
    """统一路径写法，用于比较文件依赖。"""
    if not isinstance(path, str) or not path.strip():
        return ""

    path = path.strip().replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/")


def should_skip_python(tool_name, arguments, failed_write_paths):
    """判断 Python 工具是否依赖写入失败的文件。"""
    if tool_name != "run_python":
        return False

    failed_paths = {
        normalize_path(path)
        for path in (failed_write_paths or [])
    }
    failed_paths.discard("")

    if not failed_paths:
        return False

    files = arguments.get("files", [])
    entry_file = arguments.get("entry_file", "")

    dependencies = {
        normalize_path(path)
        for path in (files or [])
    }
    dependencies.discard("")

    if entry_file:
        normalized_entry = normalize_path(entry_file)
        if normalized_entry:
            dependencies.add(normalized_entry)

    return bool(dependencies & failed_paths)


def test_write_failure_blocks_dependent_python():
    failed = {"agent_e2e_test.py"}
    args = {
        "files": ["agent_e2e_test.py"],
        "entry_file": "agent_e2e_test.py",
    }
    assert should_skip_python("run_python", args, failed)


def test_write_failure_does_not_block_unrelated_python():
    failed = {"agent_e2e_test.py"}
    args = {
        "files": ["logic_demo.py"],
        "entry_file": "logic_demo.py",
    }
    assert not should_skip_python("run_python", args, failed)


def test_failed_write_does_not_block_calculator():
    assert not should_skip_python(
        "calculator",
        {"expression": "125 * 36"},
        {"agent_e2e_test.py"},
    )


def test_successful_write_does_not_block_python():
    assert not should_skip_python(
        "run_python",
        {"files": ["agent_e2e_test.py"]},
        set(),
    )

def test_equivalent_relative_paths_are_blocked():
    failed = {"demo.py"}
    args = {
        "files": ["src/../demo.py"],
        "entry_file": "",
    }
    assert should_skip_python("run_python", args, failed)


def test_windows_style_path_is_normalized():
    failed = {"src/demo.py"}
    args = {
        "files": ["src\\demo.py"],
        "entry_file": "",
    }
    assert should_skip_python("run_python", args, failed)

if __name__ == "__main__":
    tests = [
        test_write_failure_blocks_dependent_python,
        test_write_failure_does_not_block_unrelated_python,
        test_failed_write_does_not_block_calculator,
        test_successful_write_does_not_block_python,
        test_equivalent_relative_paths_are_blocked,
        test_windows_style_path_is_normalized,
    ]

    for test in tests:
        test()
        print(f"通过：{test.__name__}")

    print(f"\n全部 {len(tests)} 项测试通过。")
