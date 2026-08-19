"""platform_storage — 跨平台用户数据存储（迭代 2 首发）。

公开 API：
- get_user_data_dir() -> Path
- HighScoreStore
- StorageError

偏好存储（PreferencesStore）保留至迭代 3 实装，本迭代不导出。
"""
from platform_storage.exceptions import StorageError
from platform_storage.highscore import HighScoreStore
from platform_storage.paths import APP_DIR_NAME, get_user_data_dir

__all__ = [
    "APP_DIR_NAME",
    "StorageError",
    "HighScoreStore",
    "get_user_data_dir",
]