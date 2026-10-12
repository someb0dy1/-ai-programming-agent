import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tools import file_tool


class WriteProjectFileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.target = self.root / "demo.py"
        self.target.write_text("print('old')", encoding="utf-8")

        self.backup_root = self.root / ".agent_backups"

        self.root_patch = patch.object(
            file_tool, "PROJECT_ROOT", self.root
        )
        self.backup_patch = patch.object(
            file_tool, "BACKUP_ROOT", self.backup_root
        )
        self.root_patch.start()
        self.backup_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.backup_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def temporary_files(self):
        return list(self.root.glob(".demo.py.*.tmp"))

    def test_normal_write_succeeds(self):
        result = file_tool.write_project_file(
            "demo.py", "print('new')"
        )

        self.assertEqual(result, "文件写入成功：demo.py")
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "print('new')",
        )
        self.assertTrue(self.backup_root.exists())
        self.assertEqual(self.temporary_files(), [])

    def test_normal_write_preserves_existing_file_permissions(self):
        self.target.chmod(0o644)

        result = file_tool.write_project_file_result(
            "demo.py",
            "print('new')",
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "print('new')",
        )
        self.assertEqual(
            self.target.stat().st_mode & 0o777,
            0o644,
            "覆盖文件后应保留原有权限模式",
        )
    def test_backup_failure_preserves_original(self):
        with patch.object(
            file_tool.shutil,
            "copy2",
            side_effect=OSError("模拟备份失败"),
        ):
            result = file_tool.write_project_file(
                "demo.py", "print('new')"
            )

        self.assertIn("写入文件失败：", result)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "print('old')",
        )
        self.assertEqual(self.temporary_files(), [])

    def test_replace_failure_preserves_original(self):
        with patch.object(
            file_tool.os,
            "replace",
            side_effect=OSError("模拟原子替换失败"),
        ):
            result = file_tool.write_project_file(
                "demo.py", "print('new')"
            )

        self.assertIn("写入文件失败：", result)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "print('old')",
        )
        self.assertEqual(self.temporary_files(), [])

    def test_invalid_content_does_not_modify_file(self):
        result = file_tool.write_project_file("demo.py", None)

        self.assertIn("错误：文件内容必须是字符串", result)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "print('old')",
        )
        self.assertEqual(self.temporary_files(), [])


    def test_symlink_replacement_before_second_path_check(self):
        outside_dir = Path(self.temp_dir.name) / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("outside-secret", encoding="utf-8")

        original_target = self.root / "demo.py"
        original_target.unlink()

        real_named_temporary_file = file_tool.tempfile.NamedTemporaryFile
        call_count = 0

        def replace_target_after_temp_created(*args, **kwargs):
            nonlocal call_count
            temp_file = real_named_temporary_file(*args, **kwargs)
            call_count += 1

            if call_count == 1:
                original_target.symlink_to(outside_file)

            return temp_file

        with patch.object(
            file_tool.tempfile,
            "NamedTemporaryFile",
            side_effect=replace_target_after_temp_created,
        ):
            result = file_tool.write_project_file_result(
                "demo.py",
                "should-not-be-written",
            )

        self.assertFalse(result["success"])
        self.assertIn("符号链接", result["message"])
        self.assertEqual(
            outside_file.read_text(encoding="utf-8"),
            "outside-secret",
        )
        self.assertTrue(original_target.is_symlink())
        self.assertEqual(self.temporary_files(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
