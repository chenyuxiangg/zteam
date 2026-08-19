# 模块内代码检视（复审）：game-app（snake-linux v2.0.0 迭代 4）

> 检视人：MDE（复审轮，retry_count=1）
> 上轮意见：`snake-linux/review/code/game-app/iter-4/MDE-代码检视-iter4.md`（FAIL：F-1 P0 / F-2 P1 / F-3 P1）
> 设计：`snake-linux/design/game-app/设计-iter4-r2.md`（SE 评审 PASS 版）
> 代码：`snake-linux/code/game-app/iter-4/`（数据层）
> 测试：`snake-linux/code/game-app/iter-4/tests/test_game_app/`（**186 passed**，较上轮 176 新增 10 个回归测试）

---

## 结论：PASS

| 检查项 | 结果 | 备注 |
|---|---|---|
| 1. 实现与模块设计一致（数据结构 / 接口 / 流程） | ✅ | F-1/F-2 修复后 §4.8/§4.9/§4.10 全对齐；§4.7 HiDPI 降级语义与设计一致（二元组直接返回） |
| 2. 实现细节质量（边界 / 异常 / 资源释放） | ✅ | F-3 Windows 平台检查可达；空版本号兜底；退出码 0/1/2/3 映射与 suggestion 齐全 |
| 3. 可测试性（UT 可写可跑） | ✅ | 186 UT 全绿（0.93s）；mock 布局与真实交付对齐，不再绿测掩盖缺陷 |
| 4. 代码风格符合架构约定 | ✅ | docstring 更新、marker 绕道移除；仅剩两处局部 import（均有合理理由） |

---

## 1. 上轮 FAIL 项修复核验（全部闭环）

### F-1【P0】spec GAME_APP_DIR 指向空目录 → 已修复 ✅

- **代码位置**：`snake-linux/spec/snake-gui.spec:18-50`（该 spec 实际位于 `zteam/snake-linux/spec/`，三构建脚本统一引用）
- **修复方式**：`GAME_APP_DIR` 改为四候选探测（资产层 iter-4 → iter-3 → 数据层 iter-4 → iter-3），**以 `__main__.py` 文件存在性判定**（`_first_existing` marker 判定，杜绝 isdir 误命中空壳目录）；三依赖包同法探测；`pathex` 含解析后目录；`datas` 字体路径随 GAME_APP_DIR 解析。
- **实核证据**（模拟 SPECPATH 注入跑探测逻辑）：
  - `GAME_APP_DIR = /home/zyzs/cyx/zteam/workspace/snake-linux/code/game-app/iter-4/game_app`，`__main__.py` 存在 ✅，`fonts/SourceHanSansCN-Regular.otf` 存在 ✅
  - 三依赖包全部命中：game-core iter-2 / gui-renderer iter-3 / platform-storage iter-2 ✅
  - `scripts/bench_fps.py:33-37` 的 `_CANDIDATES` 与 spec 候选顺序一致（设计 §5.4 兼容模式落地）
- **测试防护**：`test_app_iter4_spec.py::TestSpecStructure::test_candidates_have_entry_point`（候选实存断言）+ `test_f1_regression_probe_rule`（marker 判定规则回归）+ `test_app_iter4_build.py::test_spec_entry_point_exists`——绿测不再掩盖路径失效。

### F-2【P1】内置字体路径漏 fonts/ 子目录 → 已修复 ✅

- **代码位置**：`game_app/_constants.py:50-71`（`get_bundled_font_path`）
- **修复方式**：两分支均拼接 `BUNDLED_FONT_SUBDIR`：meipass 分支查 `<meipass>/fonts/<file>`，源码分支查 `<game_app>/fonts/<file>`；`BUNDLED_FONT_SUBDIR == "fonts"` 与 spec `datas` 目标目录（`:39-40`）一致。
- **实核证据**：字体实存于 `code/game-app/iter-4/game_app/fonts/SourceHanSansCN-Regular.otf`（8.4MB）；`fonts.py:47` 优先调 `get_bundled_font_path()` → match_font 回退链 → CJKFontFallbackWarning 兜底，INV-20 成立。
- **测试防护**：`test_app_iter4_font.py` 三个优先级测试均改在真实 `fonts/` 子目录布局下 mock；新增 `test_bundled_font_subdir_matches_spec_datas`（FONT-6 断言 subdir=="fonts"）。

### F-3【P1】win32_ver()[1] 取 csd 静默失效 → 已修复 ✅

- **代码位置**：`game_app/app.py:196-206`（`_check_platform_version`）
- **修复方式**：改取 `win32_ver()[0]`（version 位）；新增空版本号兜底（`platform.release()`），防止精简版 Windows 返回空串时检查静默失效；`int()` 解析 + 异常吞掉保护保留。
- **实核证据**：`platform.win32_ver()` 签名 `(release, version, csd, ptype)`，[0] 位为版本号，修复后 `major < 10` 判定可达。
- **测试防护**：`test_app_iter4_hidpi_platform.py` mock 修正为 `("8.1", "", "", "")`（version 位）；新增 `test_windows_empty_version_falls_back_to_release`（空版本兜底路径）。

### 上轮风格小节问题（§5，非阻塞）→ 全部修复 ✅

1. `errors.py` docstring 已更新为"退出码 3"（G4-2 语义）✅
2. `app.py` `setattr(renderer, "_hidpi_degraded_marker")` 绕道已移除——`_create_renderer_with_hidpi_fallback` 改为返回 `(renderer, degraded)` 二元组，调用方直接解包设 `self._hidpi_degraded`（`app.py:327-333`，INV-18 语义与设计 §4.7 完全一致）✅
3. 函数内 import 残留：仅剩 `app.py:180` `import platform as platform_mod`（局部别名防命名冲突，单点使用，合理）与 `__init__.py:23` 类型注解延迟导入（`# type: ignore`，合理）——均不构成问题 ✅

---

## 2. 实现与设计一致性核对（复审）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §1.1 errors.py 扩展 | StorageUnavailableError + suggestion + 3 警告类 + error_to_exit_code | `errors.py` | ✅（上轮已核，docstring 已同步） |
| §1.2 perf.py 常量 | 8 个常量 | `perf.py` | ✅ |
| §1.4 运行期状态 | _last_error/_hidpi_degraded/_cjk_font_fallback | `app.py` | ✅ |
| §3.4 App 主类 | run() 退出码 0/1/2/3 | `app.py` | ✅ |
| §4.7 HiDPI 降级 | 降级警告 + 二元组标志（INV-18） | `app.py:113-160` | ✅（本轮核心修复） |
| §4.8 字体回退链 | 内置 → match_font → Font(None) | `fonts.py:47-76` | ✅（F-2 修复后成立） |
| §4.9/§4.10 spec+构建脚本 | 三平台构建 | `spec/snake-gui.spec` + `scripts/build_*.{sh,bat}` | ✅（F-1 修复后可用） |
| §4.11 bench 脚本 | NFR-01/02 实测 + 路径候选兼容 | `scripts/bench_fps.py` / `bench_memory.py` | ✅ |
| §4.12/4.13 文档 | USER_GUIDE / RELEASE_NOTES | `release/` | ✅（GUIDE/REL UT 通过） |
| §6.3 测试用例清单 | ERR/HIDPI/PLAT/FONT/PERF/GUIDE/REL/SHA | 186 UT | ✅（含 10 个新增回归） |

## 3. 实现细节质量（边界/异常/资源释放）

- Renderer.init 失败降级链（HiDPI 开→降级重试→仍败 GraphicsUnavailableError + suggestion）✅
- create_storage/load 失败 → StorageUnavailableError → 退出码 3（INV-17）✅
- 平台版本检查：macOS <12 / Windows <10（含空版本兜底）/ Linux 跳过 ✅
- CJK 全失败 → CJKFontFallbackWarning → Font(None) 兜底（INV-19）✅
- run() finally shutdown 幂等兜底（INV-5）+ 半构造 Renderer 判空 ✅

## 4. 可测试性

- 186 UT 全绿（`pytest code/game-app/iter-4/tests/ -q` → 186 passed, 0.93s），fake_pygame/fake_storage 桩 + monkeypatch 注入，真实 IO 断绝。
- **上轮"绿测掩盖缺陷"根因已消除**：spec 路径实存断言、字体 fonts/ 子目录 mock、win32_ver version 位 mock 均与真实交付布局对齐；新增测试直接以 F-1/F-2/F-3 回归命名，行为契约导向。
- 亮点保持：bench 脚本 judge 纯函数可零窗口断言（设计 §5.4）。

## 5. 非阻塞备注（不要求修改）

1. **iter-4 独立目录 vs 设计 r2"增量落 iter-3"**：设计 r2 关键决策 1 称"不新建 iter-4 代码目录"，实际 FO 交付在独立 `code/game-app/iter-4/`（与 modules.json 迭代目录约定及 dev_product 一致，迭代隔离更清晰）。spec/bench 候选探测已兼容两种布局，无功能影响——建议后续设计修订时同步文字表述。
2. **spec/scripts/release 位于 `zteam/snake-linux/`（历史误建顶层）**：设计 P1-4 曾禁止误建该目录，但构建链产物实际统一在此，且 F-1 探测已兼容数据层路径，构建闭环可用。属产物位置约定问题（版本级/SE 关注），非模块实现缺陷，此处仅记录。

---

## 检视签字

- 检视图：`snake-linux/review/code/game-app/iter-4/MDE-代码检视-iter4-r2.md`
- 输入：设计 `snake-linux/design/game-app/设计-iter4-r2.md` + 代码 `snake-linux/code/game-app/iter-4/` + 上轮 FAIL 意见
- 测试命令：`pytest code/game-app/iter-4/tests/ -q` → **186 passed**（0.93s）
- F-1/F-2/F-3 实核：spec 探测命中数据层 iter-4（入口+字体+三依赖包全存在）；`get_bundled_font_path()` 返回真实字体路径；win32_ver version 位判定可达
- 结论：**PASS**（三项 FAIL 全部闭环，测试布局与真实交付对齐，风格问题清除）
- 后续：进入 IT 阶段（MTO 执行集成测试）
