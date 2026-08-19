# 代码检视意见：platform-storage（snake-linux v2.0.0 迭代 2）

> MDE 检视（模块内实现视角）· 依据模块设计 `snake-linux/design/platform-storage/r2.md` + 模块设计评审 `snake-linux/review/design/platform-storage/iter-2/snake-linux-platform-storage-it2-design-r2.md`（PASS）
> 检视对象：`snake-linux/code/platform-storage/iter-2/`
> 检视日期：2026-08-14

## 0. 检视结论

- **结论：PASS**
- 一句话理由：实现与设计 r2 全部对齐（数据结构/接口/流程/异常/并发/损坏恢复/构造期清理），38 个 UT 全绿，2 项非阻塞偏差不破坏契约（见 §3）。

## 1. 实现与设计一致性核对

| # | 检查项 | 设计落点 | 实现落点 | 结果 |
|---|--------|----------|----------|:----:|
| 1.1 | 模块文件组织 | §4.1 `platform_storage/{__init__,paths,highscore,exceptions}.py` + tests + README | 同上（外加 `atomic_write.py`，设计未单列但 §4.2 流程要求原子写工具，合理拆分） | ✅ |
| 1.2 | `get_user_data_dir()` 签名/语义/异常 | §3.1 / §4.5 | `paths.py:24` 完全一致（三平台分支 + mkdir + StorageError） | ✅ |
| 1.3 | `HighScoreStore.__init__` 流程 | §4.0 五步（解析 path → mkdir → 清理同名 .tmp → 建 RLock → load 初始化 _cache） | `highscore.py:45-66` 五步严格对应 | ✅ |
| 1.4 | `save()` 流程：临界区 + 仅高值落盘 + 原子写 | §4.2 + §3.2 | `highscore.py:80-101` 顺序、`score = int(score)` 强转（额外健壮性）、`score <= self._cache` 提前 return、`atomic_write_json` 调用、`StorageError from OSError` 异常链 | ✅ |
| 1.5 | `load()` 不抛异常 + 缺文件/损坏/版本不识别返回 0 | §3.2 + §4.3 + §5.2 | `highscore.py:75-78` 公开 load 仅返回 `_cache`；`_load_uncached`（构造期）覆盖全部损坏分支并备份 | ✅ |
| 1.6 | `reset()` 不抛异常 + 清缓存 | §4.4 | `highscore.py:103-110` try/except FileNotFoundError + `_cache = 0` | ✅ |
| 1.7 | `StorageError` 异常类 | §3.3 | `exceptions.py:4` 一致 | ✅ |
| 1.8 | 数据文件结构（schema_version=1 + high_score int） | §1.2 | `highscore.py:22 SCHEMA_VERSION=1`、`save()` 序列化字段一致 | ✅ |
| 1.9 | 进程内互斥锁 RLock | §2 数据传递方式 + §5.3 | `highscore.py:63 self._lock = threading.RLock()`；公开方法均在 `with self._lock:` 内 | ✅ |
| 1.10 | 构造期清理同名 .tmp（精确匹配） | §4.0 第 3 步 + §5.2 | `highscore.py:56-60` `with_suffix(suffix + ".tmp")` 精确路径 + FileNotFoundError 兼容 | ✅ |
| 1.11 | 损坏备份路径 `.corrupt-<ts>` | §4.3 第 4 步 + §7.5 用例 3/16/17/18 | `highscore.py:30-33 _corrupt_backup_path` + `:152-158 _backup_corrupt` | ✅（详见 §3.1） |
| 1.12 | 原子写流程：tmp → flush → fsync(fd) → os.replace | §4.2 + §1.3 + §5.3 | `atomic_write.py:26-39 _atomic_write_bytes` / `:42-50 atomic_write_text` 严格三步 | ✅ |
| 1.13 | `preferences.json` 不导出/不实现（仅 §3.4 签名占位） | §1.2 + §3.4 承诺 | `__init__.py:18` 仅导出 `APP_DIR_NAME / StorageError / HighScoreStore / get_user_data_dir`，未导出 `PreferencesStore` | ✅ |
| 1.14 | 无网络依赖（NFR-06） | §5.5 + 架构 §技术选型 | `paths/highscore/atomic_write/exceptions` 仅 import `os/sys/pathlib/json/threading/time/typing` —— 零网络模块 | ✅ |
| 1.15 | Python 3.8 兼容（不依赖 `missing_ok`） | §5.4 可部署 | `highscore.py:58-60 / :107-109` 均用 `try/except FileNotFoundError` 规避 3.8 不支持 | ✅ |

## 2. 实现细节质量（边界/异常/资源释放）

| # | 检查项 | 位置 | 评价 | 结果 |
|---|--------|------|------|:----:|
| 2.1 | `save` 入参强转 `int(score)`（防止浮点/字符串绕过比较） | `highscore.py:89` | 额外健壮性，优于设计但符合 §5.3 韧性 | ✅ |
| 2.2 | `bool` 类型被 `int` 排除（`isinstance(score, int) or isinstance(score, bool)`） | `highscore.py:144` | 设计 §7.5 用例 5 隐含（"字符串"），但布尔穿透风险实际存在；此实现明确拒绝 True=1/False=0 误用 | ✅ |
| 2.3 | `_backup_corrupt` 用 `Path.replace` 而非 `copy + unlink`（POSIX 原子） | `highscore.py:156` | 备份流程原子化，避免半损坏状态 | ✅ |
| 2.4 | `load()` 公开方法仅返回 `_cache`，未读盘 | `highscore.py:75-78` | 与设计 §3.2"正常返回 _cache"一致；但**外部进程在构造后改写文件不会被察觉**——本迭代单进程场景可接受，多进程场景在设计 §8 已声明"迭代 N 增加 fcntl" | ✅ |
| 2.5 | `_LOAD_ERRORS` 元组包含 `JSONDecodeError`（虽继承 `ValueError`） | `highscore.py:27` | 显式列出更清晰，且 json>=3.5 `JSONDecodeError` 是 `ValueError` 子类 | ✅ |
| 2.6 | `atomic_write_json` 使用 `ensure_ascii=False` 保留中文/emoji | `atomic_write.py:55` | 与设计 §7.5 用例 4 一致 | ✅ |
| 2.7 | 文件句柄上下文管理 `with open(...)` 保证关闭 + fsync 在 fd 关闭前生效 | `atomic_write.py:34-37 / :46-49` | 正确顺序：write → flush → fsync → close（with 退出） | ✅ |
| 2.8 | `os.replace` 在 with 块外调用（关闭 fd 后），保证 fsync 真正落盘 | `atomic_write.py:39 / :50` | 设计 §4.2 流程一致 | ✅ |
| 2.9 | `reset()` 先 unlink 再清 `_cache`，顺序安全（即便 unlink 抛 FileNotFoundError 也走 except） | `highscore.py:106-110` | 与设计一致 | ✅ |
| 2.10 | `_load_uncached` 校验顺序：先 dict → schema_version 存在/类型/值 → high_score 类型/bool 排除/范围 | `highscore.py:128-150` | 与设计 §4.3 流程对应 | ✅ |

## 3. 与设计偏差（非阻塞，明确记录）

| ID | 偏差 | 设计落点 | 实现落点 | 判定 |
|----|------|----------|----------|:----:|
| 3.1 | 损坏备份文件命名实现细节 | §4.3 第 4 步 `self.path.with_suffix(f".corrupt-{int(time.time())}.json")` | `_corrupt_backup_path` 用 `with_name(f"{stem}.corrupt-{ts}{suffix}")` | **等效**：`highscore.json` → `highscore.corrupt-<ts>.json`（两者结果完全一致；实现路径对未来多 suffix 文件名更稳健，非退化） |
| 3.2 | `_dirty` 字段未定义 | §1.3 内存缓存模型表 + §4.2 第 7 步 `更新 _cache = score; _dirty = False` | 实现无 `_dirty` 属性 | **可接受**：`_dirty` 在设计中标注"进程崩溃兜底参考"，未在公开接口/UT 用例/鲁棒性承诺中引用；删除不影响行为与可测试性（仅 1 处段落未对齐文档）。建议 MDE 在设计 r3 同步移除该字段，保持文档与实现单一事实源 |

> **设计一致性补丁建议**：将 §3.2/3.3 加入"实现偏差表"或在下一轮设计 r3 中修正 §1.3/§4.2。属文档同步，非代码缺陷。

## 4. 可测试性核对

| # | 检查项 | 评价 | 结果 |
|---|--------|------|:----:|
| 4.1 | UT 可写可跑（pytest + unittest 双兼容） | 设计 §7.2 | ✅ |
| 4.2 | 用例覆盖设计 §7.5 必含清单 | 7+18+5 = 30 项设计清单，实测 38 用例（含 lock 类型、init 默认路径、__init__ 保留其他 .tmp 等补充），覆盖度 ≥ 设计清单 | ✅ |
| 4.3 | 桩/Mock 规范符合设计 §7.3 | `monkeypatch` → `mock.patch` 等价；threading.RLock 未 mock 用真实并发；fsync 用计数桩 + 真实调用 | ✅ |
| 4.4 | 断言规范符合设计 §7.4 | 路径对象相等、IO 副作用断言、异常链断言 (`__cause__ is not None`)、并发断言、构造期清理断言 | ✅ |
| 4.5 | **运行验证**：`PYTHONPATH=. python3 -m unittest discover -v tests/` | **38 tests, 0 failures, 0 errors（0.174s）** | ✅ |

## 5. 代码风格与架构约定

| # | 检查项 | 评价 | 结果 |
|---|--------|------|:----:|
| 5.1 | 公开 API 命名与签名严格匹配设计 §3 | 一致 | ✅ |
| 5.2 | 模块导入清晰（相对包内绝对导入 `from platform_storage.xxx import yyy`） | 一致（`exceptions.py` 无循环依赖） | ✅ |
| 5.3 | `__all__` 显式声明 | `__init__.py:14-18` 列出 4 项 | ✅ |
| 5.4 | 类型标注（`Path | None`、`-> int`、`-> None`） | `highscore.py:16 Optional[Path]`、方法返回标注齐全 | ✅ |
| 5.5 | Docstring（中英混排，遵循 v1.0.0 风格） | 每个公开类/方法均有 docstring + Raises/Args 段 | ✅ |
| 5.6 | 常量集中（SCHEMA_VERSION / HIGHSCORE_FILENAME / CORRUPT_PREFIX） | `highscore.py:22-24` 顶部常量，APP_DIR_NAME 在 paths.py:15 | ✅ |
| 5.7 | 单一职责（paths 只做定位、highscore 只做存储、atomic_write 只做工具） | 无交叉耦合 | ✅ |
| 5.8 | README.md 含使用示例 + 数据格式 + 鲁棒性保证 | `README.md` 与 v1.0.0 终端版 README 风格一致 | ✅ |

## 6. 检视门禁输出（自动化兜底）

- 单测执行：`Ran 38 tests in 0.174s OK`
- 失败项：无
- 警告项：无
- 偏差项：2 项（详见 §3，均为非阻塞文档同步建议）

## 7. MDE 建议（不构成 FAIL 依据）

1. 设计 r3 同步：移除 §1.3 `_dirty` 字段描述，或在 §3.2/3.3 标注"实现未实装 `_dirty`，行为无依赖"；
2. 设计 r3 同步：§4.3 第 4 步备份路径描述调整为"`highscore.corrupt-<ts>.json`（按 stem + suffix 重组）"，与实现 `with_name` 路径对齐；
3. 后续迭代若引入多文件（如 PreferencesStore），建议在 `paths.py` 抽象 `backup_corrupt_path(stem, suffix)` 共用工具。

---

**结论**：实现质量达标（数据结构/接口/流程/异常/并发/损坏恢复/构造期清理全对齐），38 个 UT 全绿，2 项非阻塞偏差属文档同步建议，不影响契约与可测试性。

**PASS** —— 进入 it_working。