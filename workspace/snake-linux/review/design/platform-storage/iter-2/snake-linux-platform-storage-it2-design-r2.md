# 功能模块设计评审意见：platform-storage（snake-linux v2.0.0 迭代 2）r2（复审）

> SE 评审 · 依据：模块设计 `snake-linux/design/platform-storage/r2.md`（修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）
> 复审对象：r1 评审（FAIL，3 必改 + 2 建议）后的 MDE 修订版
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：r1 全部 5 项意见（P1~P3 必改 + P4/P5 建议）在 r2 中逐条落实且落点与流程/用例取齐，无新增矛盾；架构遵循性（模块定位/依赖/接口/数据流/技术选型）经复核仍全量一致；UT 框架（18+5+7 用例、桩/mock/断言规范）可支撑 FO 无歧义 TDD。

## 1. r1 意见修订核对（逐条）

| ID | r1 意见 | r2 修订落点 | 结果 |
|----|---------|-------------|:----:|
| P1 | RLock 声明"不实装"与流程/用例矛盾 | §2 数据传递方式改为"迭代 2 实装（标准库一行，零成本）"；§1.3 `_lock` 注释同步"迭代 2 实装"；§4.2/§4.3/§4.4 保留 `with self._lock:`；§7.4 并发断言与 §7.5 用例 14 保留 | ✅ |
| P2 | schema_version 校验承诺与 load() 流程矛盾 | §4.3 load() 新增校验分支：schema_version 缺字段/类型错/值 != 1 → 备份损坏文件 + 返回 0；§7.5 补用例 16（=99）、17（缺字段）、18（类型错字符串） | ✅ |
| P3 | __init__ 行为定义不全（构造期 .tmp 清理无流程） | §3.2 语义补"构造期 mkdir → 清理残留 *.tmp → load"；新增 §4.0 完整流程（解析 path → mkdir → glob 精确清理同名 `.tmp` → 建 RLock → load 初始化 _cache）；用例 15 保留 | ✅ |
| P4 | §0 规格引用错误 FR-14 → NFR-07 | §0 承载需求改为"FR-13 + NFR-06/07"，与分工表/架构一致 | ✅ |
| P5 | preferences.json 预留接口未定义签名 | 新增 §3.4"偏好接口预留（迭代 3 实装）"：PreferencesStore 签名占位（init/load/save/reset）+ 明确"本迭代不导出不实现，FO 不得据此实现"承诺 | ✅ |

修订对照表（§修订对照）自述与文档正文一致，无"声称已改但正文未改"的落空项。

## 2. 架构遵循性复核（r2 版）

| 核对项 | 架构要求 | r2 落实 | 结果 |
|--------|----------|---------|:----:|
| 模块定位 | 中间件、无依赖（叶子） | §0 中间件/依赖无/被 game-app 依赖 | ✅ |
| 迭代排期 | 迭代 2 首发 | §0 迭代 2（首发）；modules.json n=2 design_reviewing | ✅ |
| 接口 | `get_user_data_dir()`；`HighScoreStore(path)`: load/save(原子写)/reset | §3.1/§3.2 签名语义对应（path 属性为兼容扩展）；§3.3 StorageError | ✅ |
| 数据流 | core 得分事件 → app → storage.save（同步） | §2 同步函数返回值；无反向依赖 | ✅ |
| 技术选型 | 标准库 JSON + 原子写（tmp + os.replace）；三平台目录 | §4.2 原子写流程（tmp→flush→fsync→os.replace）；§1.1/§4.5 三平台路径 | ✅ |
| 零第三方依赖 | core/storage 不 import 第三方库 | §5.5 NFR-06 import 检查；§6 纯标准库 | ✅ |
| Python 3.8 兼容 | 语法兼容 3.8 | unlink missing_ok 用 try/except FileNotFoundError 规避（§4.0/§4.4） | ✅ |
| NFR-03 衔接 | 可读错误提示路径 | §2 错误反馈 StorageError → game-app 统一捕获 | ✅ |

## 3. 需求覆盖核对

| 需求 | 设计落点 | 结果 |
|------|----------|:----:|
| FR-13 最高分持久化（重启保留/重置/异常退出不损坏） | HighScoreStore load/save/reset + 原子写 + 损坏备份恢复（§3.2/§4.2~4.4） | ✅ |
| NFR-06 无网络行为 | §5.5 不 import socket/urllib/http + 数据最小化（仅最高分整数） | ✅ |
| NFR-07 便携式不写系统目录 | §1.1 用户数据目录（APPDATA / ~/Library/Application Support / ~/.local/share） | ✅ |

## 4. 复审新发现（不阻塞）

- §4.0 第 3 步清理匹配的两种表述（`self.path.name + ".tmp"` 与 `self.path.with_suffix(self.path.suffix + ".tmp").name`）经核算一致（均为 `highscore.json.tmp`），且与用例 15"精确匹配同名 .tmp"对齐；表述略显绕，但不构成行为歧义；
- §4.0 建锁（第 4 步）先于 load（第 5 步，内部 `with self._lock:`），时序正确；
- §4.3 schema_version 校验分支与用例 16/17/18 逐条对应（=99/缺字段/类型错），high_score 类型与负数校验与用例 5/6 对应，无"有承诺无用例"或"有用例无流程"的缺项；
- 建议级（留给 FO/MDE 检视把关，不阻塞本轮）：§4.2 第 5 步 `flush → fsync → close` 若中间抛 OSError，fd 可能未关闭且 `.tmp` 残留——虽有构造期清理兜底，建议 FO 用 try/finally 保证 close，MDE 检视门禁时确认。

## 5. 结论

- **PASS**：r1 五项意见全部落实且取齐（声明/流程/用例三处一致），架构遵循性与需求覆盖无回归，UT 框架（test_paths 7 + test_highscore 18 + test_atomic_write 5 = 30 用例）具备 FO TDD 依据。
- 模块迭代 2 可进入 dev_working（FO 开发）；建议项随检视门禁（release_module review）确认即可。
