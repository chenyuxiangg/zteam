# platform-storage（snake-linux v2.0.0 迭代 2）

跨平台用户数据目录定位 + 最高分 JSON 持久化 + 原子写防损坏 + 重置支撑。

> 详细设计：`workspace/snake-linux/design/platform-storage/r2.md`
> 检视意见：`workspace/snake-linux/review/design/platform-storage/iter-2/`

## 安装（开发模式）

```bash
cd workspace/snake-linux/code/platform-storage/iter-2
pip install -e .   # 或直接 PYTHONPATH=.
```

无第三方依赖，仅 Python 3.8+ 标准库。

## 公开 API

```python
from platform_storage import get_user_data_dir, HighScoreStore, StorageError

# 三平台用户数据目录（自动 mkdir）
data_dir = get_user_data_dir()
#   win32: %APPDATA%/SnakeGui
#   darwin: ~/Library/Application Support/SnakeGui
#   linux: $XDG_DATA_HOME/SnakeGui  or  ~/.local/share/SnakeGui

# 最高分存储（默认路径）
store = HighScoreStore()  # → {data_dir}/highscore.json
score = store.load()      # 0 if missing / corrupt / unknown schema
store.save(score + 1)    # only writes if score > cache
store.reset()             # 删除文件 + cache = 0

# 自定义路径（测试 / 便携模式）
from pathlib import Path
store = HighScoreStore(path=Path("/tmp/game/highscore.json"))

# 错误处理
try:
    store.save(score)
except StorageError as e:
    # 走 NFR-03 可读错误提示路径
    log_user_visible(e)
```

## 数据格式（highscore.json）

```json
{
  "schema_version": 1,
  "high_score": 1234
}
```

- `schema_version`：当前 = 1（常量）；不识别 / 缺字段 / 类型错 → 备份 + 返回 0
- `high_score`：整数 ≥ 0；负数 / 字符串 / 缺字段 → 备份 + 返回 0

## 鲁棒性保证

- **原子写**：临时文件 → flush → fsync(fd) → os.replace；写过程断电旧文件完整
- **损坏恢复**：JSON 损坏 / 字段错 / 负数 / schema_version 不识别 → 自动备份 `.corrupt-<ts>.json` 后返回 0
- **进程内并发**：`HighScoreStore._lock`（RLock）保护所有公开方法；多线程并发 `save` 最终值 = max
- **构造期清理**：同名 `highscore.json.tmp` 残留自动清理；其他模块 `.tmp` 不误删
- **无网络**：不依赖 socket / urllib / http（NFR-06）

## 文件结构

```
platform-storage/iter-2/
├── platform_storage/
│   ├── __init__.py        # 导出 get_user_data_dir, HighScoreStore, StorageError
│   ├── paths.py           # 三平台路径定位
│   ├── highscore.py       # HighScoreStore + 损坏恢复
│   ├── atomic_write.py    # 原子写工具
│   └── exceptions.py      # StorageError
├── tests/
│   ├── test_paths.py        # 7 用例
│   ├── test_atomic_write.py # 12 用例（含 fsync 验证）
│   └── test_highscore.py    # 19 用例（设计 §7.5 全部 + 补充）
└── README.md
```

## 测试

```bash
cd workspace/snake-linux/code/platform-storage/iter-2
python3 -m unittest discover -v -s tests
# 或
python3 -m pytest tests/ -v
```

## 不在范围内

- `PreferencesStore`（偏好 / 皮肤）：接口签名见 `design/platform-storage/r2.md` §3.4，迭代 3 实装
- 多进程文件锁（fcntl）：迭代 2 单进程不实装
- PyInstaller hook：标准库，无 C 扩展