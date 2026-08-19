"""platform_storage.highscore — HighScoreStore 实现。

依据设计 §3.2/§4.0-§4.4：
- __init__: mkdir → 清理同名 .tmp → 创建 RLock → load 初始化 _cache
- load: 缺文件/损坏/schema_version 不识别/类型错 → 备份 + 返回 0
- save: only if score > _cache；临界区内读-比较-写整体原子；原子写
- reset: 删除文件 + _cache = 0

鲁棒性：load 永不抛异常给上层（仅 __init__ 在 mkdir 失败时抛 StorageError）。
进程内并发：RLock 保护所有公开方法。
"""
import json
import threading
import time
from pathlib import Path
from typing import Optional

from platform_storage.atomic_write import atomic_write_json
from platform_storage.exceptions import StorageError
from platform_storage.paths import get_user_data_dir

SCHEMA_VERSION = 1
HIGHSCORE_FILENAME = "highscore.json"
CORRUPT_PREFIX = "highscore.corrupt-"

# load() 内 JSON/类型校验失败的异常类型
_LOAD_ERRORS = (KeyError, ValueError, TypeError, json.JSONDecodeError)


def _corrupt_backup_path(target: Path) -> Path:
    """生成损坏文件备份路径：<stem>.corrupt-<ts><suffix>。"""
    ts = int(time.time())
    return target.with_name(f"{target.stem}.corrupt-{ts}{target.suffix}")


class HighScoreStore:
    """最高分持久化存储（单进程内线程安全）。

    Attributes:
        path (Path): highscore.json 绝对路径（构造期计算）。
        _cache (int): 内存缓存的最高分。
        _lock (threading.RLock): 进程内互斥锁。
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        # 1. 解析路径
        if path is None:
            self.path = get_user_data_dir() / HIGHSCORE_FILENAME
        else:
            self.path = path

        # 2. 创建目录
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # 3. 清理同名 .tmp 残留（精确匹配，避免误删其他模块临时文件）
        same_name_tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            same_name_tmp.unlink()
        except FileNotFoundError:
            pass

        # 4. 创建进程内互斥锁（RLock：允许同一线程重入）
        self._lock = threading.RLock()

        # 5. 初始化内存缓存
        self._cache = self._load_uncached()

    # ---------- public API ----------

    @property
    def cache(self) -> int:
        """返回当前内存缓存值（仅供测试 / 调试）。"""
        return self._cache

    def load(self) -> int:
        """返回当前最高分。缺文件 / 损坏 / 版本不识别返回 0，不抛异常。"""
        with self._lock:
            return self._cache

    def save(self, score: int) -> None:
        """写入新最高分；仅在严格大于当前值时落盘（避免并发降分）。

        Args:
            score: 新分值；必须为 int。

        Raises:
            StorageError: IO / 权限失败。
        """
        score = int(score)
        with self._lock:
            if score <= self._cache:
                return  # 无需落盘
            payload = {
                "schema_version": SCHEMA_VERSION,
                "high_score": score,
            }
            try:
                atomic_write_json(self.path, payload)
            except OSError as e:
                raise StorageError(f"写入最高分文件失败 {self.path}: {e}") from e
            self._cache = score

    def reset(self) -> None:
        """删除 highscore.json（如存在）并清 _cache = 0。"""
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._cache = 0

    # ---------- internal ----------

    def _load_uncached(self) -> int:
        """加载并校验最高分（无锁版本；调用方需在锁内或构造期调用）。

        损坏恢复：备份为 .corrupt-<ts> 后返回 0。
        """
        if not self.path.exists():
            return 0
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except _LOAD_ERRORS:
            self._backup_corrupt()
            return 0

        # 校验 schema_version
        if not isinstance(data, dict):
            self._backup_corrupt()
            return 0
        if "schema_version" not in data:
            self._backup_corrupt()
            return 0
        if not isinstance(data["schema_version"], int):
            self._backup_corrupt()
            return 0
        if data["schema_version"] != SCHEMA_VERSION:
            self._backup_corrupt()
            return 0

        # 校验 high_score
        score = data.get("high_score")
        if not isinstance(score, int) or isinstance(score, bool):
            self._backup_corrupt()
            return 0
        if score < 0:
            self._backup_corrupt()
            return 0
        return score

    def _backup_corrupt(self) -> None:
        """将损坏文件备份为 .corrupt-<ts>。"""
        backup = _corrupt_backup_path(self.path)
        try:
            self.path.replace(backup)
        except FileNotFoundError:
            pass