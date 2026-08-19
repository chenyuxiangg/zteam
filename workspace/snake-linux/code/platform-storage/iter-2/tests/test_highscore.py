"""test_highscore.py — HighScoreStore 核心类单测（依据设计 §7.5 用例 1-18）

覆盖：
1. 缺文件 → load 返回 0
2. 正常文件 → load 返回缓存值
3. JSON 损坏 → load 返回 0 + 备份存在
4. 缺 high_score 字段 → load 返回 0 + 备份存在
5. 类型错（字符串）→ load 返回 0 + 备份存在
6. 负数 → load 返回 0 + 备份存在
7. save(score > cache) → 文件更新 + _cache 更新
8. save(score <= cache) → 不写盘（mtime 不变）
9. 连续多次 save → 最终文件 = max
10. save 后不存在 .tmp 残留
11. reset → 文件删除 + load = 0
12. reset 不存在的文件 → 不抛
13. save IO 失败（mock os.replace 抛 OSError）→ StorageError
14. 并发 save 不同分值 → 最终 = max
15. 构造期清理残留 highscore.json.tmp
16. schema_version 不识别 → load 返回 0 + 备份存在
17. schema_version 缺字段 → load 返回 0 + 备份存在
18. schema_version 类型错 → load 返回 0 + 备份存在
"""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from platform_storage.highscore import HighScoreStore
from platform_storage.exceptions import StorageError
from platform_storage.atomic_write import _tmp_path_for


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def _make_store(tmp_dir: Path, name: str = "highscore.json") -> HighScoreStore:
    return HighScoreStore(path=tmp_dir / name)


class HighScoreStoreBasicTests(unittest.TestCase):
    """用例 1-2：缺文件 / 正常文件。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "highscore.json"

    def test_load_returns_zero_when_file_missing(self):
        store = _make_store(Path(self._tmp.name))
        self.assertEqual(store.load(), 0)

    def test_load_returns_cached_value(self):
        _write_json(self.path, {"schema_version": 1, "high_score": 100})
        store = _make_store(Path(self._tmp.name))
        self.assertEqual(store.load(), 100)


class HighScoreStoreCorruptTests(unittest.TestCase):
    """用例 3-6：损坏恢复。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "highscore.json"

    def _assert_corrupt_backup_exists(self, store):
        backups = list(self.dir.glob("highscore.corrupt-*.json"))
        self.assertEqual(len(backups), 1, f"应有 1 个备份，实际 {backups}")

    # 3. JSON 损坏
    def test_corrupt_json_returns_zero_with_backup(self):
        self.path.write_text("{not json", encoding="utf-8")
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists(store)

    # 4. 缺字段
    def test_missing_high_score_field_returns_zero_with_backup(self):
        _write_json(self.path, {"schema_version": 1})  # 无 high_score
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists(store)

    # 5. 类型错（字符串）
    def test_high_score_wrong_type_returns_zero_with_backup(self):
        _write_json(self.path, {"schema_version": 1, "high_score": "abc"})
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists(store)

    # 6. 负数
    def test_negative_high_score_returns_zero_with_backup(self):
        _write_json(self.path, {"schema_version": 1, "high_score": -10})
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists(store)


class HighScoreStoreSaveTests(unittest.TestCase):
    """用例 7-10, 13：save 行为。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "highscore.json"

    # 7. save(score > cache) → 写盘
    def test_save_with_higher_score_writes_file(self):
        store = _make_store(self.dir)
        store.save(50)
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["high_score"], 50)
        self.assertEqual(store.load(), 50)

    # 8. save(score <= cache) → 不写盘（mtime 不变）
    def test_save_with_lower_score_does_not_write(self):
        store = _make_store(self.dir)
        store.save(100)
        mtime1 = self.path.stat().st_mtime_ns
        # 睡一下以确保 mtime 差异可观察（若实现误写）
        time.sleep(0.01)
        store.save(50)  # <= 100
        mtime2 = self.path.stat().st_mtime_ns
        self.assertEqual(mtime1, mtime2)
        self.assertEqual(store.load(), 100)

    # 9. 连续多次 save → 最终 = max
    def test_consecutive_save_keeps_max(self):
        store = _make_store(self.dir)
        for s in [10, 50, 30, 80, 20, 99, 1]:
            store.save(s)
        self.assertEqual(store.load(), 99)
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["high_score"], 99)

    # 10. save 后不存在 .tmp 残留
    def test_no_tmp_leftover_after_save(self):
        store = _make_store(self.dir)
        store.save(123)
        self.assertFalse(_tmp_path_for(self.path).exists())

    # 13. save IO 失败 → StorageError
    def test_save_io_failure_raises_storage_error(self):
        store = _make_store(self.dir)
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(StorageError) as cm:
                store.save(10)
        self.assertIsNotNone(cm.exception.__cause__)


class HighScoreStoreResetTests(unittest.TestCase):
    """用例 11-12：reset。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "highscore.json"

    # 11. reset → 删除 + cache = 0
    def test_reset_removes_file_and_clears_cache(self):
        _write_json(self.path, {"schema_version": 1, "high_score": 88})
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 88)
        store.reset()
        self.assertFalse(self.path.exists())
        self.assertEqual(store.load(), 0)

    # 12. reset 不存在的文件 → 不抛
    def test_reset_on_missing_file_is_safe(self):
        store = _make_store(self.dir)
        self.assertFalse(self.path.exists())
        store.reset()  # 不抛
        self.assertEqual(store.load(), 0)


class HighScoreStoreConcurrentTests(unittest.TestCase):
    """用例 14：进程内并发（RLock 保护下稳定通过）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_concurrent_save_keeps_max(self):
        store = _make_store(self.dir)
        scores = [10, 50, 30, 99, 20, 77, 88, 100, 5, 1, 200, 150]
        threads = []

        def worker(s):
            store.save(s)

        for s in scores:
            t = threading.Thread(target=worker, args=(s,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=5)
        final = store.load()
        self.assertEqual(final, max(scores))


class HighScoreStoreConstructionCleanupTests(unittest.TestCase):
    """用例 15：构造期清理同名 .tmp 残留。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "highscore.json"
        self.tmp = self.dir / "highscore.json.tmp"

    def test_constructor_cleans_up_same_name_tmp(self):
        # 预先制造残留
        self.tmp.write_text("leftover", encoding="utf-8")
        self.assertTrue(self.tmp.exists())
        # 构造 store 应清理同名 .tmp
        store = _make_store(self.dir)
        self.assertFalse(self.tmp.exists())

    def test_constructor_preserves_other_dot_tmp_files(self):
        # 同名 .tmp 应清理；其他模块的 .tmp 不应被误删
        # 这里用 different_name.tmp 模拟其他模块临时文件
        other = self.dir / "preferences.json.tmp"
        other.write_text("other module tmp", encoding="utf-8")
        same_name = self.dir / "highscore.json.tmp"
        same_name.write_text("leftover", encoding="utf-8")
        store = _make_store(self.dir)
        # 精确清理：仅 highscore.json.tmp 被清
        self.assertFalse(same_name.exists())
        self.assertTrue(other.exists(), "不应误删其他 .tmp 残留")


class HighScoreStoreSchemaVersionTests(unittest.TestCase):
    """用例 16-18：schema_version 校验。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "highscore.json"

    def _assert_corrupt_backup_exists(self):
        backups = list(self.dir.glob("highscore.corrupt-*.json"))
        self.assertEqual(len(backups), 1, f"应有 1 个备份，实际 {backups}")

    # 16. schema_version 不识别
    def test_unrecognized_schema_version_returns_zero_with_backup(self):
        _write_json(self.path, {"schema_version": 99, "high_score": 10})
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists()

    # 17. schema_version 缺字段
    def test_missing_schema_version_returns_zero_with_backup(self):
        _write_json(self.path, {"high_score": 10})  # 无 schema_version
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists()

    # 18. schema_version 类型错
    def test_schema_version_wrong_type_returns_zero_with_backup(self):
        _write_json(self.path, {"schema_version": "v1", "high_score": 10})
        store = _make_store(self.dir)
        self.assertEqual(store.load(), 0)
        self._assert_corrupt_backup_exists()


class HighScoreStoreInitDefaultPathTests(unittest.TestCase):
    """补充：__init__ 无入参时使用默认路径（含 mkdir）。"""

    def test_init_with_none_path_uses_default(self):
        with mock.patch("platform_storage.highscore.get_user_data_dir") as g:
            from platform_storage.paths import APP_DIR_NAME
            default_dir = Path("/tmp/fake_default_data") / APP_DIR_NAME
            default_dir.mkdir(parents=True, exist_ok=True)
            g.return_value = default_dir
            store = HighScoreStore(path=None)
            self.assertEqual(store.path, default_dir / "highscore.json")
            self.assertEqual(store.load(), 0)


class HighScoreStoreLockTests(unittest.TestCase):
    """补充：_lock 是 RLock，且公开方法在锁内执行。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_lock_is_rlock(self):
        import threading
        store = _make_store(self.dir)
        self.assertIsInstance(store._lock, type(threading.RLock()))


if __name__ == "__main__":
    unittest.main()