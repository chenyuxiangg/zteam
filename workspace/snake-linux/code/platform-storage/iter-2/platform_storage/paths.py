"""platform_storage.paths — 三平台用户数据目录定位。

依据设计 §3.1 / §4.5：
- win32: %APPDATA% 或 fallback ~/AppData/Roaming
- darwin: ~/Library/Application Support
- linux/unix: $XDG_DATA_HOME 或 fallback ~/.local/share
- 子目录固定名 SnakeGui（与 v1.x "Snake" 不复用——产品名升级）
"""
import os
import sys
from pathlib import Path

from platform_storage.exceptions import StorageError

APP_DIR_NAME = "SnakeGui"


def _linux_or_unix_base(home: Path) -> Path:
    """Linux/Unix 平台基础目录：优先 XDG_DATA_HOME，否则 ~/.local/share。"""
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else home / ".local" / "share"


def get_user_data_dir() -> Path:
    """返回三平台用户数据目录下的 SnakeGui 子目录。

    副作用：mkdir(parents=True, exist_ok=True) 幂等创建。

    Raises:
        StorageError: mkdir 失败（权限 / 只读盘）。
    """
    home = Path.home()
    sysname = sys.platform
    if sysname == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
    elif sysname == "darwin":
        base = home / "Library" / "Application Support"
    else:
        # linux / linux2 / 其他 unix
        base = _linux_or_unix_base(home)

    target = base / APP_DIR_NAME
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise StorageError(f"无法创建用户数据目录 {target}: {e}") from e
    return target