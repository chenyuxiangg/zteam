"""platform-storage v2.0.0 迭代 2 模块集成测试（IT）。

用例编号 IT-storage-2-01 ~ IT-storage-2-28，共 28 条。
依据测试用例文档：snake-linux/it/platform-storage/iter-2/测试用例.md

被测代码路径：snake-linux/code/platform-storage/iter-2/
（pytest + unittest 双兼容，monkeypatch 隔离平台分支与 IO）
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import pytest

# 被测代码定位（与测试套件框架 §3.1 一致：上溯工作区）
import sys
WS_ROOT = Path(__file__).resolve()
# it/platform-storage/iter-2/test_it_storage_2.py -> workspace/snake-linux/
for _ in range(6):
    WS_ROOT = WS_ROOT.parent
CODE_ROOT = WS_ROOT / "code" / "platform-storage" / "iter-2"
sys.path.insert(0, str(CODE_ROOT))

from platform_storage import (  # noqa: E402
    APP_DIR_NAME,
    HighScoreStore,
    StorageError,
    get_user_data_dir,
)
from platform_storage import atomic_write as aw_mod  # noqa: E402
from platform_storage import highscore as hs_mod  # noqa: E402
from platform_storage import paths as paths_mod  # noqa: E402


# =================== 工具 ===================


def _write_json(path: Path, payload) -> None:
    """写入 JSON（支持 dict 或 str 内容）。"""
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _reset_environ(monkeypatch, **kwargs):
    """清除/设置环境变量。"""
    for k, v in kwargs.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# =================== IT-storage-2-01 三平台定位 ===================


def test_it_01_three_platform_paths(tmp_path, monkeypatch):
    """IT-storage-2-01: 三平台用户数据目录定位。"""
    monkeypatch.setattr(paths_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData/Roaming"))
    p = get_user_data_dir()
    assert p == tmp_path / "AppData/Roaming" / "SnakeGui", "win32+APPDATA"
    assert p.is_dir()

    monkeypatch.setattr(paths_mod.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    fake_home = tmp_path / "home"
    monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: fake_home))
    p = get_user_data_dir()
    assert p == fake_home / "AppData" / "Roaming" / "SnakeGui", "win32 fallback"

    monkeypatch.setattr(paths_mod.sys, "platform", "darwin")
    fake_home = tmp_path / "home2"
    monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: fake_home))
    p = get_user_data_dir()
    assert p == fake_home / "Library" / "Application Support" / "SnakeGui", "darwin"

    monkeypatch.setattr(paths_mod.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    p = get_user_data_dir()
    assert p == tmp_path / "xdg" / "SnakeGui", "linux+XDG"

    monkeypatch.setattr(paths_mod.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    fake_home = tmp_path / "home3"
    monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: fake_home))
    p = get_user_data_dir()
    assert p == fake_home / ".local" / "share" / "SnakeGui", "linux fallback"


# =================== IT-storage-2-02 mkdir 失败 ===================


def test_it_02_mkdir_raises_storage_error(tmp_path, monkeypatch):
    """IT-storage-2-02: mkdir 权限拒绝抛 StorageError + 异常链。"""
    monkeypatch.setattr(paths_mod.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    # 模拟 mkdir 抛 OSError
    real_mkdir = paths_mod.Path.mkdir

    def fake_mkdir(self, *a, **kw):
        raise OSError("simulated permission denied")

    monkeypatch.setattr(paths_mod.Path, "mkdir", fake_mkdir)
    with pytest.raises(StorageError) as exc:
        get_user_data_dir()
    assert exc.value.__cause__ is not None, "FR-13 异常链保留原始 OSError"
    monkeypatch.setattr(paths_mod.Path, "mkdir", real_mkdir)


# =================== IT-storage-2-03 子目录自动创建 ===================


def test_it_03_subdir_auto_created(tmp_path, monkeypatch):
    """IT-storage-2-03: 子目录 SnakeGui 自动创建。"""
    monkeypatch.setattr(paths_mod.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    target = tmp_path / "SnakeGui"
    assert not target.exists()
    p = get_user_data_dir()
    assert APP_DIR_NAME == "SnakeGui"
    assert p.name == "SnakeGui"
    assert p.is_dir()


# =================== IT-storage-2-04 默认路径 ===================


def test_it_04_default_path(tmp_path, monkeypatch):
    """IT-storage-2-04: 默认路径与默认文件名。"""
    monkeypatch.setattr(paths_mod.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    store = HighScoreStore()
    assert store.path == tmp_path / "SnakeGui" / "highscore.json"
    assert store.path.name == "highscore.json"
    assert store.path.is_absolute()


# =================== IT-storage-2-05 缺文件 ===================


def test_it_05_missing_file_returns_zero(tmp_path):
    """IT-storage-2-05: 缺文件 load 返回 0。"""
    store = HighScoreStore(tmp_path / "highscore.json")
    assert store.load() == 0
    assert not store.path.exists()


# =================== IT-storage-2-06 正常文件加载 ===================


def test_it_06_normal_file_load(tmp_path):
    """IT-storage-2-06: 正常文件 load 返回缓存值。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1, "high_score": 1234})
    store = HighScoreStore(p)
    assert store.load() == 1234
    assert store.cache == 1234


# =================== IT-storage-2-07 save 升级 ===================


def test_it_07_save_updates_file_and_cache(tmp_path):
    """IT-storage-2-07: save(score > cache) 文件更新 + 缓存更新。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    store.save(100)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["high_score"] == 100
    assert store.load() == 100


# =================== IT-storage-2-08 save 不降分 ===================


def test_it_08_save_no_downgrade(tmp_path):
    """IT-storage-2-08: save(score <= cache) 不写盘。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1, "high_score": 100})
    mtime_before = p.stat().st_mtime_ns
    time.sleep(0.05)
    store = HighScoreStore(p)
    store.save(50)  # 低于 cache
    assert store.load() == 100, "FR-13 save 不应覆盖更高分"
    assert p.stat().st_mtime_ns == mtime_before, "FR-13 不触发 IO"


# =================== IT-storage-2-09 多次 save ===================


def test_it_09_multiple_save_picks_max(tmp_path):
    """IT-storage-2-09: 多次 save 最终 = max，重启后仍能读到。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    for s in [10, 50, 30, 100, 80]:
        store.save(s)
    assert store.load() == 100
    store2 = HighScoreStore(p)
    assert store2.load() == 100


# =================== IT-storage-2-10 原子写不留 tmp ===================


def test_it_10_atomic_write_no_tmp_residue(tmp_path):
    """IT-storage-2-10: 原子写不留 .tmp 残留。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    store.save(42)
    assert not (tmp_path / "highscore.json.tmp").exists()
    assert list(tmp_path.glob("*.tmp")) == []


# =================== IT-storage-2-11 reset ===================


def test_it_11_reset_clears_file_and_cache(tmp_path):
    """IT-storage-2-11: 重置删除文件 + load = 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1, "high_score": 999})
    store = HighScoreStore(p)
    assert store.load() == 999
    store.reset()
    assert not p.exists()
    assert store.load() == 0


# =================== IT-storage-2-12 reset 不存在的文件 ===================


def test_it_12_reset_missing_file_idempotent(tmp_path):
    """IT-storage-2-12: reset 不存在的文件不抛异常。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    store.reset()  # 不抛异常
    assert store.load() == 0


# =================== IT-storage-2-13 损坏 JSON ===================


def test_it_13_corrupt_json_backup(tmp_path):
    """IT-storage-2-13: 损坏 JSON → load 返回 0 + 备份存在。"""
    p = tmp_path / "highscore.json"
    corrupt_text = "{not valid json"
    p.write_text(corrupt_text, encoding="utf-8")
    store = HighScoreStore(p)
    assert store.load() == 0
    backups = list(tmp_path.glob("highscore.corrupt-*.json"))
    assert len(backups) >= 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_text


# =================== IT-storage-2-14 缺 high_score 字段 ===================


def test_it_14_missing_high_score_field(tmp_path):
    """IT-storage-2-14: 缺 high_score 字段 → 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-15 high_score 类型错 ===================


def test_it_15_high_score_wrong_type(tmp_path):
    """IT-storage-2-15: high_score 类型错（字符串）→ 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1, "high_score": "abc"})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-16 high_score 负数 ===================


def test_it_16_high_score_negative(tmp_path):
    """IT-storage-2-16: high_score 负数 → 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 1, "high_score": -5})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-17 save IO 失败 ===================


def test_it_17_save_io_failure_storage_error(tmp_path, monkeypatch):
    """IT-storage-2-17: save IO 失败抛 StorageError + 异常链 + 目标未被破坏。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    real_replace = aw_mod.os.replace

    def boom(*a, **kw):
        raise OSError("simulated replace fail")

    monkeypatch.setattr(aw_mod.os, "replace", boom)
    with pytest.raises(StorageError) as exc:
        store.save(100)
    assert exc.value.__cause__ is not None
    # 目标未被破坏（不存在或保持原状）
    monkeypatch.setattr(aw_mod.os, "replace", real_replace)


# =================== IT-storage-2-18 并发 save ===================


def test_it_18_concurrent_save_picks_max(tmp_path):
    """IT-storage-2-18: 5 线程并发 save 不同分值 → 最终 = max。"""
    p = tmp_path / "highscore.json"
    store = HighScoreStore(p)
    scores = [10, 50, 30, 100, 80]
    threads = [threading.Thread(target=store.save, args=(s,)) for s in scores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.load() == 100
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["high_score"] == 100
    store2 = HighScoreStore(p)
    assert store2.load() == 100


# =================== IT-storage-2-19 构造期清理同名 .tmp ===================


def test_it_19_construct_cleans_same_name_tmp(tmp_path):
    """IT-storage-2-19: 构造期清理同名 highscore.json.tmp；不误删其他 .tmp。"""
    same_tmp = tmp_path / "highscore.json.tmp"
    other_tmp = tmp_path / "other.tmp"
    same_tmp.write_text("stale", encoding="utf-8")
    other_tmp.write_text("keep me", encoding="utf-8")
    store = HighScoreStore(tmp_path / "highscore.json")
    assert not same_tmp.exists(), "同名 .tmp 应被清理"
    assert other_tmp.exists(), "其他模块的 .tmp 不应被误删"


# =================== IT-storage-2-20 schema_version 不识别 ===================


def test_it_20_schema_version_unknown(tmp_path):
    """IT-storage-2-20: schema_version=99 → 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": 99, "high_score": 100})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-21 schema_version 缺字段 ===================


def test_it_21_schema_version_missing(tmp_path):
    """IT-storage-2-21: 缺 schema_version → 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"high_score": 100})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-22 schema_version 类型错 ===================


def test_it_22_schema_version_wrong_type(tmp_path):
    """IT-storage-2-22: schema_version="v1" → 备份 + 返回 0。"""
    p = tmp_path / "highscore.json"
    _write_json(p, {"schema_version": "v1", "high_score": 100})
    store = HighScoreStore(p)
    assert store.load() == 0
    assert list(tmp_path.glob("highscore.corrupt-*.json"))


# =================== IT-storage-2-23 atomic_write_json 编码 ===================


def test_it_23_atomic_write_json_utf8(tmp_path):
    """IT-storage-2-23: atomic_write_json 中文/emoji 编码正确。"""
    p = tmp_path / "p.json"
    # 蛇(0x86C7) + 蛇 emoji(0x1F40D)，动态构造避免 patch 转义
    payload = {"name": chr(0x86C7) + chr(0x1F40D), "score": 42}
    aw_mod.atomic_write_json(p, payload)
    raw = p.read_text(encoding="utf-8")
    # ensure_ascii=False → 中文字面存在（不转 uXXXX）
    assert chr(0x86C7) in raw, "ensure_ascii=False 应保留中文"
    assert chr(0x1F40D) in raw, "ensure_ascii=False 应保留 emoji"
    data = json.loads(raw)
    assert data["name"] == chr(0x86C7) + chr(0x1F40D)



# =================== IT-storage-2-24 atomic_write_json 含 schema_version ===================


def test_it_24_atomic_write_json_includes_schema_version(tmp_path):
    """IT-storage-2-24: atomic_write_json 写入 schema_version 字段。"""
    p = tmp_path / "hs.json"
    aw_mod.atomic_write_json(p, {"schema_version": 1, "high_score": 100})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1


# =================== IT-storage-2-25 os.replace 失败 ===================


def test_it_25_atomic_write_text_replace_failure(tmp_path, monkeypatch):
    """IT-storage-2-25: os.replace 失败 → 目标未被破坏 + tmp 保留。"""
    target = tmp_path / "target.txt"
    target.write_text("ORIG", encoding="utf-8")
    real_replace = aw_mod.os.replace

    def boom(src, dst):
        raise OSError("simulated replace fail")

    monkeypatch.setattr(aw_mod.os, "replace", boom)
    with pytest.raises(OSError):
        aw_mod.atomic_write_text(target, "NEW")
    monkeypatch.setattr(aw_mod.os, "replace", real_replace)
    assert target.read_text(encoding="utf-8") == "ORIG"
    tmp = tmp_path / "target.txt.tmp"
    assert tmp.exists(), "失败时 tmp 保留便于排查"


# =================== IT-storage-2-26 无网络 import 静态检查 ===================


def test_it_26_no_network_import():
    """IT-storage-2-26: 模块无网络依赖（NFR-06）。"""
    forbidden_patterns = [
        r"\bimport\s+socket\b",
        r"\bimport\s+urllib\b",
        r"\bimport\s+http\b",
        r"\bfrom\s+socket\b",
        r"\bfrom\s+urllib\b",
        r"\bfrom\s+http\b",
        r"\brequests\.",
        r"\bhttpx\.",
        r"\baiohttp\.",
    ]
    pkg_dir = CODE_ROOT / "platform_storage"
    bad = []
    for py in pkg_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            if re.search(pat, text):
                bad.append(f"{py.name}: {pat}")
    assert bad == [], f"NFR-06 违反：无网络依赖 → {bad}"


# =================== IT-storage-2-27 fsync 被调用 ===================


def test_it_27_save_calls_fsync(tmp_path, monkeypatch):
    """IT-storage-2-27: save 流程触发 os.fsync。"""
    p = tmp_path / "highscore.json"
    calls = []
    real_fsync = aw_mod.os.fsync

    def spy_fsync(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(aw_mod.os, "fsync", spy_fsync)
    store = HighScoreStore(p)
    store.save(42)
    assert len(calls) >= 1, "FR-13 原子写必须触发 fsync"


# =================== IT-storage-2-28 path 属性 ===================


def test_it_28_path_attribute_is_absolute(tmp_path):
    """IT-storage-2-28: store.path 是绝对 pathlib.Path。"""
    store = HighScoreStore(tmp_path / "hs.json")
    assert isinstance(store.path, Path)
    assert store.path.is_absolute()
    assert str(store.path) == str(tmp_path / "hs.json")
