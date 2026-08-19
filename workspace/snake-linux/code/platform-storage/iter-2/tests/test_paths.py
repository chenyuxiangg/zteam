"""test_paths.py — 路径定位单测（依据设计 §7.5 用例 1-7）

覆盖：
1. win32 + APPDATA 存在 → 使用 APPDATA
2. win32 + APPDATA 缺失 → fallback 到 home/AppData/Roaming
3. darwin → home/Library/Application Support
4. linux + XDG_DATA_HOME → 使用 XDG
5. linux + 无 XDG → fallback 到 home/.local/share
6. mkdir 权限拒绝 → StorageError
7. 子目录 SnakeGui 自动创建
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from platform_storage.paths import get_user_data_dir, APP_DIR_NAME
from platform_storage.exceptions import StorageError


class _FakeHomePath:
    """模拟 Path.home()，避免污染用户真实目录。"""
    def __init__(self, home):
        self._home = Path(home)

    def __call__(self):
        return self._home


class GetUserDataDirTests(unittest.TestCase):
    """get_user_data_dir() 三平台路径定位。"""

    def setUp(self):
        # 每个用例用自己的临时 home，避免环境泄漏
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self._patch_home = mock.patch.object(
            Path, "home", new_callable=lambda: _FakeHomePath(self.home)
        )
        self._patch_home.start()
        self.addCleanup(self._patch_home.stop)

        # 清空 XDG_DATA_HOME / APPDATA 避免父进程泄漏
        self._clean_env = mock.patch.dict(
            os.environ, {"XDG_DATA_HOME": "", "APPDATA": ""}, clear=False
        )
        self._clean_env.start()
        self.addCleanup(self._clean_env.stop)

    def _set_platform(self, name):
        return mock.patch.object(sys, "platform", name)

    # 1. win32 + APPDATA 存在
    def test_win32_with_appdata_uses_appdata(self):
        appdata = self.home / "AppData" / "Roaming"
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}), \
             self._set_platform("win32"):
            result = get_user_data_dir()
        self.assertEqual(result, appdata / APP_DIR_NAME)
        self.assertTrue(result.exists())

    # 2. win32 + APPDATA 缺失
    def test_win32_without_appdata_fallback_to_home(self):
        # APPDATA 已被 setUp 置空
        with self._set_platform("win32"):
            result = get_user_data_dir()
        expected = self.home / "AppData" / "Roaming" / APP_DIR_NAME
        self.assertEqual(result, expected)
        self.assertTrue(result.exists())

    # 3. darwin
    def test_darwin_uses_library_application_support(self):
        with self._set_platform("darwin"):
            result = get_user_data_dir()
        expected = self.home / "Library" / "Application Support" / APP_DIR_NAME
        self.assertEqual(result, expected)
        self.assertTrue(result.exists())

    # 4. linux + XDG
    def test_linux_with_xdg_data_home(self):
        xdg = self.home / "custom_xdg"
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(xdg)}), \
             self._set_platform("linux"):
            result = get_user_data_dir()
        self.assertEqual(result, xdg / APP_DIR_NAME)
        self.assertTrue(result.exists())

    # 5. linux + 无 XDG
    def test_linux_without_xdg_fallback(self):
        with self._set_platform("linux"):
            result = get_user_data_dir()
        expected = self.home / ".local" / "share" / APP_DIR_NAME
        self.assertEqual(result, expected)
        self.assertTrue(result.exists())

    # 6. mkdir 失败 → StorageError
    def test_mkdir_failure_raises_storage_error(self):
        # 让目标已存在但不可写：mock mkdir 抛 OSError
        with self._set_platform("linux"):
            with mock.patch.object(Path, "mkdir",
                                   side_effect=PermissionError("denied")):
                with self.assertRaises(StorageError) as cm:
                    get_user_data_dir()
        # 异常链：原始 OSError 应被 from 保留
        self.assertIsNotNone(cm.exception.__cause__)

    # 7. 子目录 SnakeGui 自动创建
    def test_app_subdir_is_created(self):
        with self._set_platform("linux"):
            result = get_user_data_dir()
        self.assertTrue(result.is_dir())
        self.assertEqual(result.name, APP_DIR_NAME)
        self.assertEqual(APP_DIR_NAME, "SnakeGui")


if __name__ == "__main__":
    unittest.main()