# 功能模块设计评审意见：platform-storage（snake-linux v2.0.0 迭代 2）r1

> SE 评审 · 依据：模块设计 `snake-linux/design/platform-storage/r1.md` + 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：设计整体遵循架构（模块定位/依赖/接口/数据流/技术选型全部一致），UT 框架详实（27 用例 + 桩/断言规范）具备 TDD 基础，但存在 **3 处设计文档内部矛盾**（RLock 声明 vs 流程/用例、schema_version 校验承诺 vs load 流程、__init__ 行为定义缺失），直接导致 FO 按文档 TDD 时行为歧义；均属文档级小修，MDE 修订后重新 DONE 即可过。

## 1. 架构遵循性核对

| 核对项 | 架构要求 | 设计落实 | 结果 |
|--------|----------|----------|:----:|
| 模块定位 | 中间件、无依赖（叶子） | §0 中间件/依赖无/被 game-app 依赖 | ✅ |
| 迭代排期 | 迭代 2 首发 | §0 迭代 2（首发）；modules.json n=2 design_reviewing | ✅ |
| 接口 | `get_user_data_dir()`（三平台目录+应用子目录）；`HighScoreStore(path)`: load/save(原子写)/reset | §3.1/§3.2 签名与语义完全对应（含 path 属性扩展，兼容） | ✅ |
| 数据流 | core 得分事件 → app → storage.save（同步） | §2 同步函数返回值传递，无反向依赖 | ✅ |
| 技术选型 | 标准库 JSON + 原子写（tmp + os.replace）；三平台目录 %APPDATA% / ~/Library/Application Support / ~/.local/share | §4.2 原子写流程（tmp→fsync→os.replace）；§4.5 三平台路径 | ✅ |
| 零第三方依赖 | core/storage 不 import 第三方库 | §5.5 NFR-06 无网络 import 检查；资源评估"纯标准库" | ✅ |
| Python 3.8 兼容 | 语法兼容 3.8 | unlink missing_ok 用 try/except 规避（§4.4） | ✅ |

接口清单与架构"设计期定义接口"要求一致，无接口级偏差。

## 2. 需求覆盖核对（模块承载子集）

| 需求 | 设计落点 | 结果 |
|------|----------|:----:|
| FR-13 最高分持久化（重启保留/重置/异常退出不损坏） | HighScoreStore load/save/reset + 原子写 + 损坏备份恢复（§3.2/§4.2~4.4） | ✅ |
| NFR-06 无网络行为 | §5.5 不 import socket/urllib/http + 数据最小化 | ✅ |
| NFR-07 便携式不写系统目录 | 用户数据目录（§1.1） | ✅ |
| §0 规格引用 | 写"FR-14（用户数据目录，不写安装路径）" | ⚠️ 引用错误，见 P4 |

## 3. 可落地性评估（FO TDD 依据）

- ✅ UT 框架完备：测试目录/文件划分（test_paths 7 例、test_highscore 15 例、test_atomic_write 5 例）、运行命令、覆盖率目标 ≥95%、桩/mock 规范（monkeypatch 三平台/禁止 mock Path）、断言规范（原子性/异常链/并发）齐全；
- ✅ 接口签名/异常语义/边界行为（缺文件、损坏、权限拒绝）逐条明确；
- ❌ 但存在 3 处设计内部矛盾（见 §4），FO 按文档实现会出现"按 A 处写实现、按 B 处写测试"对不上的情况。

## 4. 必改问题（FAIL 依据，阻塞 FO 无歧义 TDD）

### P1. RLock 声明"不实装"与流程/用例自相矛盾（§2 vs §4.2/§7.4/§7.5-14）
- §2 数据传递方式："进程内互斥 threading.RLock（**预留）；本迭代单线程不实装**"；
- 但 §4.2 save 流程第 1 步即 `with self._lock:` 进入临界区；§7.4 断言规范与 §7.5 用例 14 均要求"threading.Thread(5) 并发 save 不同分值 → 最终 = max"。
- 后果：若不实装锁，读-比较-写非原子，低分线程可能在 `_cache` 更新前通过比较并覆盖高分，用例 14 无锁下必 flaky/失败；若实装锁，§2 声明错误。
- **修订（二选一，必须取齐）**：a) 迭代 2 实装 RLock（标准库一行、零成本，§4.2 流程已就位），删除 §2"不实装"表述；b) 删除用例 14 与 §7.4 并发断言，明确"迭代 2 不承诺并发行为"。

### P2. schema_version 校验承诺与 load() 流程矛盾（§5.2 vs §4.3；用例清单缺项）
- §5.2 鲁棒性表承诺："schema_version 不识别 → 备份 + 返回 0"；
- 但 §4.3 load() 流程仅处理 JSONDecodeError/KeyError/ValueError/TypeError 与 high_score 类型/负数校验，**无 schema_version 校验分支**；§7.5 用例清单也无对应用例。
- 后果：按 §4.3 实现，`{"schema_version": 99, "high_score": 100}` 将正常返回 100，与 §5.2 承诺冲突；FO 无法确定正确行为。
- **修订**：§4.3 load() 增加 `schema_version != 1` 时走损坏备份分支（返回 0 + 备份）；§7.5 test_highscore 补用例"schema_version 不识别 → 返回 0 + 备份存在"。

### P3. __init__ 行为定义不全：构造期 *.tmp 清理无实现流程（§3.2 vs §5.2/§7.5-15）
- §5.2 承诺"临时文件残留 → 构造期清理 *.tmp"、用例 15 要求"构造期清理残留 .tmp"；
- 但 §3.2 __init__ 语义仅"构造期 mkdir + load"，§4 实现细节无 __init__ 流程小节（清理方式/glob 范围/时序未定义）。
- 后果：FO 不知道清理是"精确删自身 .tmp"还是"glob 全目录"、先于/后于 load 执行。
- **修订**：§4 补 __init__ 流程：mkdir(parents=True) → glob 清理 `*.tmp` 残留 → load() 初始化 _cache。

## 5. 建议问题（不阻塞本轮）

### P4. §0 规格引用错误：FR-14 → 应 NFR-07
- 规格 FR-14 = "免预装直接运行（三平台单文件可执行）"，属 game-app/PyInstaller 交付范畴，与本模块无关；"不写安装路径"实际对应 **NFR-07**（发布物规范·便携式）。
- 分工表与架构写的是"FR-13/NFR-06/07"。建议 §0 承载需求改为"FR-13 + NFR-06/07"，避免追溯混淆。

### P5. preferences.json 预留接口未定义签名（§1.2 vs §3）
- §1.2 称"接口预留由 storage 模块提供（load/save/reset）"，但 §3 对外接口仅有 get_user_data_dir + HighScoreStore，偏好接口无签名定义。
- 建议：a) §3 补预留接口签名（标注迭代 3 实装）；或 b) 明确"本轮不提供偏好接口，迭代 3 设计时定义"。避免 FO 误以为本轮要实现偏好 load/save。

## 6. 结论

- **FAIL**：P1~P3 为设计文档内部矛盾（非架构违背、非方案不可行），会让 FO 按 §7 用例写测试与按 §4 流程写实现互相冲突；MDE 按上述修订（预计半小时内）后重新 `release_module ... design DONE`，SE 复审通过即 PASS。
- 架构遵循性本身无问题，无需回退架构。
