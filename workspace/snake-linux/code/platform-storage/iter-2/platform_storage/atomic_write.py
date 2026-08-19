"""platform_storage.atomic_write — 原子写工具。

依据设计 §4.2 流程：
1. 写入临时文件（<name>.tmp）
2. f.flush() → os.fsync(fd)
3. os.replace(tmp, target)（POSIX/Windows 均为原子）

设计 §7.5 test_atomic_write 用例 3：
os.replace 失败 → 目标不被破坏，临时文件可保留（用于排查）。
"""
import json
import os
from pathlib import Path
from typing import Any


def _tmp_path_for(target: Path) -> Path:
    """生成临时文件路径：<name><suffix>.tmp → 实际为 <name>.tmp。

    使用 with_suffix(.suffix + ".tmp") 保留原 suffix 再追加 .tmp，
    即 highscore.json → highscore.json.tmp。
    """
    return target.with_suffix(target.suffix + ".tmp")


def _atomic_write_bytes(target: Path, data: bytes, encoding: str = "utf-8") -> None:
    """底层原子写：临时文件 → flush → fsync → os.replace。

    Raises:
        OSError: 写入失败（IO 错误），或 os.replace 失败时透传。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path_for(target)
    with open(tmp, "w", encoding=encoding) as f:
        f.write(data.decode(encoding) if isinstance(data, bytes) else data)
        f.flush()
        os.fsync(f.fileno())
    # os.replace 在同文件系统内原子；失败时临时文件保留
    os.replace(tmp, target)


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    """原子写入文本内容。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path_for(target)
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def atomic_write_json(target: Path, payload: Any, encoding: str = "utf-8") -> None:
    """原子写入 JSON 负载（ensure_ascii=False 保留中文/emoji）。"""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    atomic_write_text(target, text, encoding=encoding)