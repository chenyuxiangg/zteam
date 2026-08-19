"""storage 模块：HighScoreStore 包装（G2-2 iter-2 新增）。

设计目的：
- 隔离 platform_storage 与 game_app，app 仅依赖本模块的 create_storage
- 让 UT 可以 monkeypatch `create_storage` 注入 fake

公开 API：
- create_storage(path: Optional[Path] = None) -> HighScoreStore
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from platform_storage import HighScoreStore


def create_storage(path: Optional[Path] = None) -> HighScoreStore:
    """构造 HighScoreStore 实例。

    Args:
        path: 自定义路径（UT 用 tmp_path）；None → platform_storage.get_user_data_dir()

    Returns:
        HighScoreStore 实例（构造期 mkdir 失败抛 OSError / StorageError，让 _init_pygame 捕获）

    Raises:
        OSError: mkdir 失败（P1-1 实核 platform-storage iter-2 的 highscore.py 抛裸 OSError）
        platform_storage.StorageError: save() 内部 atomic_write 失败时抛（构造期不抛）
    """
    return HighScoreStore(path)


__all__ = ["create_storage"]