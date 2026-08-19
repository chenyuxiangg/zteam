# 模块内代码检视：game-app（snake-linux v2.0.0 迭代 4）

> 检视人：MDE
> 设计：`snake-linux/design/game-app/设计-iter4-r1.md`（SE 评审 PASS 后首发 r1）
> 代码：`snake-linux/code/game-app/iter-4/`（数据层 workspace；资产层 code/ 为空壳）
> 测试：`snake-linux/code/game-app/iter-4/tests/test_game_app/`（176 passed）
> UT 运行：`pytest code/game-app/iter-4/tests/ -q` → **176 passed**（0.90s）

---

## 结论：FAIL

| 检查项 | 结果 | 备注 |
|---|---|---|
| 1. 实现与模块设计一致（数据结构 / 接口 / 流程） | ❌ | **G4-1 spec 构建路径失效**（spec 指向资产层空目录，构建必败）；**G4-5 内置字体路径失效**（get_bundled_font_path 漏 fonts/ 子目录，INV-20 不成立） |
| 2. 实现细节质量（边界 / 异常 / 资源释放） | ❌ | **Windows 平台版本检查静默失效**（win32_ver()[1] 取 csd 非版本号，PLAT-2 不可达） |
| 3. 可测试性（UT 可写可跑） | ⚠️ | 176 UT 全绿，但 build/spec/font/platform 四组测试的 mock 与真实交付布局脱节，**绿测掩盖真实缺陷**；judge 纯函数抽离是亮点 |
| 4. 代码风格符合架构约定 | ⚠️ | 小瑕疵若干（函数内 import、过时 docstring、marker 绕道），不阻塞 |

---

## 1. FAIL 级问题（阻塞，需 FO 修复后复审）

### F-1【P0】G4-1 打包矩阵不可用：spec 的 GAME_APP_DIR 指向资产层空目录

- **代码位置**：`snake-linux/spec/snake-gui.spec:22-23`（GAME_APP_DIR 定义）、`:29-31`（datas 字体源）、`:56-57`（Analysis 入口）
- **问题**：
  ```python
  PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))       # → snake-linux/（资产层）
  GAME_APP_DIR = os.path.join(PROJECT_ROOT, "code", "game-app", "iter-3", "game_app")
  ```
  资产层 `snake-linux/code/` 下**无任何代码文件**（`find code -type f` 为空；`code/game-app/iter-3/game_app/` 仅有空 `fonts/` 子目录）。真实代码在数据层 `workspace/snake-linux/code/game-app/iter-4/`（modules.json iter-4.dev_product 亦指向此处）。
- **实核证据**：
  - `os.path.isfile(snake-linux/code/game-app/iter-3/game_app/__main__.py)` → **False**
  - `os.path.isfile(snake-linux/code/game-app/iter-3/game_app/fonts/SourceHanSansCN-Regular.otf)` → **False**
  - `os.path.isfile(workspace/snake-linux/code/game-app/iter-4/game_app/__main__.py)` → **True**
- **后果**：`pyinstaller --clean --noconfirm spec/snake-gui.spec`（build_linux.sh:15 / build_windows.bat:22 / build_macos.sh:15 均引用此 spec）在 Analysis 阶段即报错（入口脚本不存在），**三平台打包矩阵 G4-1 完全不可用**，dist/ 产物无法产出。
- **修复建议**：GAME_APP_DIR 改为指向数据层 iter-4（`workspace/snake-linux/code/game-app/iter-4`），或参考 bench_fps.py 已实现的 `_CANDIDATES` 四候选路径兼容模式（资产层 iter-4 → iter-3 → 数据层 iter-4 → iter-3）做候选探测；同步核对三个 build 脚本的 PROJECT_ROOT 解析。
- **测试为何没抓到**：`test_app_iter4_spec.py` 仅做 `compile()` 语法 + 正则断言（文件存在/含字符串），`test_app_iter4_build.py` 仅做 `bash -n` 语法冒烟，**均未验证 GAME_APP_DIR 指向的目录真实存在代码**。

### F-2【P1】G4-5 内置字体路径失效：get_bundled_font_path 两个候选分支都漏 `fonts/` 子目录

- **代码位置**：`game_app/_constants.py:58-71`（get_bundled_font_path 两分支）
- **问题**：字体文件实际位于 `game_app/fonts/SourceHanSansCN-Regular.otf`（子目录），但两个查找分支均直接在 `_MEIPASS` 根 / `__file__` 同目录查找，**未拼接 `fonts/` 前缀**：
  ```python
  # 1. PyInstaller --onefile：spec datas 目标目录是 "fonts"（spec:31）→ 实际在 _MEIPASS/fonts/ 下
  candidate = os.path.join(meipass, BUNDLED_FONT_FILENAME)   # 查 _MEIPASS/SourceHanSansCN-Regular.otf → 不存在
  # 2. 源码模式：字体在 game_app/fonts/ 子目录
  candidate = os.path.join(here, BUNDLED_FONT_FILENAME)      # 查 game_app/SourceHanSansCN-Regular.otf → 不存在
  ```
- **实核证据**：运行时实测 `get_bundled_font_path()` 返回 `''`（字体真实在 `game_app/fonts/` 下，game_app 根目录无字体）。
- **后果**：**INV-20 不成立**——内置字体优先级链第 1/2 级永远落空，始终走 match_font 系统字体回退链；在无 CJK 系统字体的 Linux 上中文显示为方框，**G4-5 打包内置字体的核心目标未达成**。
- **修复建议**：meipass 分支查 `os.path.join(meipass, "fonts", BUNDLED_FONT_FILENAME)`；源码分支查 `os.path.join(here, "fonts", BUNDLED_FONT_FILENAME)`；同时修正 `test_returns_source_path_when_no_meipass`（当前在 game_app 根目录 mock 字体，与真实交付布局不符，属**测试掩盖缺陷**）。

### F-3【P1】Windows 平台版本检查静默失效：win32_ver()[1] 取的是 csd 而非版本号

- **代码位置**：`game_app/app.py:194`
  ```python
  win_ver = platform_mod.win32_ver()[1]   # ← 应为 [0]
  major = int(win_ver.split(".")[0])
  ```
- **问题**：`platform.win32_ver()` 返回元组 `(version, csd, ptype)`——**版本号在 [0]**（如 `'10.0'` / `'6.1'`），**[1] 是 csd**（service pack 描述，如 `'Service Pack 1'` 或空串）。取 `[1]` 后 `int()` 几乎必抛 ValueError，被 `except (ValueError, IndexError, AttributeError): pass` 吞掉 → **Windows <10 的 PlatformUnsupportedWarning 永不触发**。
- **实核证据**：`inspect.signature(platform.win32_ver)` = `(release='', version='', csd='', ptype='')`，返回 (version, csd, ptype)。
- **后果**：G4-2 平台检查目标在 Windows 上不可达（PLAT-2 UT 通过是 mock 结构错误所致：`test_windows_old_version_warning` mock 返回 `("", "8.1", "", "")` 把版本号放在了 csd 位）。
- **修复建议**：改取 `[0]`；同步修测试 mock 为 `("8.1", "", "", "")` 结构（version 位）。

---

## 2. 实现与设计一致性核对（非阻塞项）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §1.1 errors.py 扩展 | StorageUnavailableError + suggestion + 3 警告类 + error_to_exit_code | `errors.py:42-105` | ✅（_EXIT_CODE_MAP 缺 AppError:1 显式条目，但循环后 isinstance 兜底等价，行为一致） |
| §1.2 perf.py 常量 | 8 个常量值 | `perf.py:23-36` | ✅ 全对齐 |
| §1.4 运行期状态 | _last_error/_hidpi_degraded/_cjk_font_fallback | `app.py:238-240` | ✅ |
| §3.4 App 主类 | run() 退出码 0/1/2/3 | `app.py:249-288` | ✅ 2/3 路径 stderr suggestion + finally shutdown 兜底 |
| §4.7 HiDPI 降级 | 第一次失败 → warning + 降级；都失败 → GraphicsUnavailableError | `app.py:109-165` | ⚠️ 功能一致，但降级标志通过 `setattr(renderer, "_hidpi_degraded_marker")` 绕道传递（见 §4.4） |
| §4.8 字体回退链 | 内置 → match_font 链 → Font(None) | `fonts.py:35-83` | ⚠️ 回退链逻辑正确，但内置字体路径定位失效（F-2） |
| §4.9/§4.10 spec+构建脚本 | 三平台构建 | `spec/snake-gui.spec` + `scripts/build_*.{sh,bat}` | ❌ GAME_APP_DIR 指向空目录（F-1） |
| §4.11 bench 脚本 | NFR-01/02 实测 | `scripts/bench_fps.py` / `bench_memory.py` | ✅ 路径候选兼容做得好（四候选），judge 纯函数抽离可测 |
| §4.12/4.13 文档 | USER_GUIDE 五节 / RELEASE_NOTES | `release/USER_GUIDE.md` / `RELEASE_NOTES.md` | ✅ 字段完备（GUIDE/REL UT 实测通过） |
| §6.3 ERR/HIDPI/PLAT/FONT/PERF/GUIDE/REL/SHA | 测试用例清单 | 176 UT | ⚠️ 数量全覆盖，但 4 组 mock 与真实行为脱节（F-1/2/3） |

---

## 3. 实现细节质量

### 3.1 边界 / 异常路径（已实核）

| 场景 | 实现 | 评价 |
|---|---|---|
| Renderer.init 失败（HiDPI 开） | 降级重试 → 仍败 GraphicsUnavailableError(suggestion) | ✅ |
| Renderer.init 失败（HiDPI 关） | 直接 GraphicsUnavailableError | ✅ |
| create_storage/load 失败 | StorageUnavailableError(suggestion) → 退出码 3 | ✅（INV-17） |
| _dispatch_menu RESET_HIGHSCORE 失败 | StorageError → StorageUnavailableError（无 suggestion，可接受） | ✅ |
| score_callback storage.save 失败 | StorageUnavailableError → _run_loop error_to_exit_code → 3 | ✅ |
| 平台版本检查 | macOS ✅ / **Windows ❌（F-3）** / Linux 跳过 | ❌ |
| CJK 字体回退链全失败 | CJKFontFallbackWarning → Font(None) 兜底 | ✅（INV-19） |
| 打包内置字体路径 | **两分支均失效（F-2）** | ❌ |

### 3.2 资源释放

- run() `finally` shutdown 兜底（INV-5）：`app.py:282-288`，幂等包裹 ✅
- 半构造 Renderer 泄漏：_init_pygame 失败路径 `self._renderer` 保持 None，finally 判空 ✅

### 3.3 不变量（INV）核对

| # | 描述 | 落点 | 守住 |
|---|---|---|---|
| INV-17 | Graphics→2 / Storage→3 | `app.py:261-274` + `errors.py:82-105` | ✅ |
| INV-18 | HiDPI 降级标志 | `app.py:324-325`（经 marker） | ✅ 功能等价 |
| INV-19 | CJK 回退标志 | `app.py:342-348` catch_warnings 检测 | ⚠️ 语义偏宽（内置字体失败即置 True，即使 match_font 成功） |
| **INV-20** | **内置字体优先级** | `_constants.py:58-71` | ❌ **两分支路径错误，永不走内置字体** |

---

## 4. 可测试性

### 4.1 亮点

- bench_fps/bench_memory 的 `judge_fps` / `judge_memory` 纯判定函数抽离，UT 可零窗口断言 PASS/FAIL 边界 —— 符合设计 §5.4"性能脚本可测"。
- fake_pygame 全套桩（含 VIDEORESIZE 常量）+ fake_storage + fake_renderer_iter3 + monkeypatch 注入顺序沿用 iter-3，176 UT 0.90s 全绿，真实 IO 断绝。

### 4.2 问题（测试与真实交付布局脱节，绿测掩盖缺陷）

1. **test_app_iter4_spec.py**：只断言 spec 文件"存在/含字符串/语法合法"，**未验证 GAME_APP_DIR 指向目录有代码** → F-1 漏网。
2. **test_app_iter4_build.py**：仅 `bash -n` 语法冒烟，未真正执行 `pyinstaller`（本机无 pyinstaller 可理解，但至少应验证 spec 入口路径 isfile）→ F-1 漏网。
3. **test_app_iter4_font.py::test_returns_source_path_when_no_meipass**：在 `_constants.__file__` 同目录（game_app 根）创建占位字体——**mock 布局与真实交付（fonts/ 子目录）不符** → F-2 漏网。
4. **test_app_iter4_hidpi_platform.py::test_windows_old_version_warning**：mock `win32_ver` 返回 `("", "8.1", "", "")`，把版本号放在 csd 位，**与真实 API (version, csd, ptype) 结构不符** → F-3 漏网。
5. `test_hidpi_first_try_succeeds_no_fallback` 注释已自曝 `MagicMock(spec=[])` 规避 `_hidpi_degraded_marker` 自动属性陷阱——测试服务于实现细节而非行为契约。

### 4.3 覆盖率

未跑 --cov 复测（本机 .coverage 存在），但行覆盖率目标 §6.4（app.py/errors.py 100%）大概率不达标——F-1 的 spec 路径与 F-3 的 Windows 分支在真实分支上未被覆盖。

---

## 5. 风格 / 架构约定（小瑕疵，不阻塞）

1. `app.py:341` 函数内 `from .errors import CJKFontFallbackWarning`（其余 import 均在顶部）——建议合并到顶部 import。
2. `errors.py:6` 模块 docstring 仍写 "StorageUnavailableError：HighScoreStore 失败 → 退出码 1"——**iter-4 已改退出码 3，docstring 过时**。
3. `app.py:156-159` `setattr(renderer, "_hidpi_degraded_marker", True)` 向第三方 Renderer 实例写私有属性传递降级状态——功能正确（Renderer 无 __slots__ 实测可行）但绕道；设计 §4.7 语义是调用方直接置 `self._hidpi_degraded`，建议改为 `_create_renderer_with_hidpi_fallback` 返回 (renderer, degraded) 二元组或由 _init_pygame 捕获 HighDPIWarning 判定。
4. `app.py:90` 与 `:63-68` 两处 `from gui_renderer import ...` 可合并（iter-3 已记录，仍存在）。

---

## 6. 检视结论

### 6.1 FAIL 理由汇总

1. **F-1（P0）**：spec GAME_APP_DIR 指向资产层空目录，PyInstaller 三平台构建必然失败 → **G4-1 打包矩阵核心交付不可用**（FR-14 未达成）。
2. **F-2（P1）**：get_bundled_font_path 两分支漏 `fonts/` 子目录，运行时实测返回 `''` → **INV-20 / G4-5 内置字体目标未达成**（打包产物中字体形同虚设）。
3. **F-3（P1）**：win32_ver()[1] 取 csd 非版本号 → **Windows 平台版本检查静默失效**（PLAT-2 不可达）。

以上三条均指向明确代码位置、可执行修复；测试 mock 与真实交付布局脱节是共同根因（绿测掩盖真实缺陷）。

### 6.2 复审要求

FO 修复 F-1/F-2/F-3 后：
- 修对应 4 组测试的 mock 布局（spec 路径实存断言 / 字体 fonts/ 子目录 / win32_ver version 位）；
- 本机可验证项：`get_bundled_font_path()` 返回真实字体路径；`_check_platform_version` Windows mock 走 version 位触发警告；
- 真实构建验证（有 pyinstaller 环境）：`bash scripts/build_linux.sh` 产出 dist/snake-gui-linux-x86_64。

---

## 检视签字

- 检视图：`snake-linux/review/code/game-app/iter-4/MDE-代码检视-iter4.md`
- 输入：设计 `snake-linux/design/game-app/设计-iter4-r1.md` + 代码 `snake-linux/code/game-app/iter-4/`（数据层）+ 资产层 spec/scripts/release
- 测试命令：`pytest code/game-app/iter-4/tests/ -q` → 176 passed
- 结论：**FAIL**（F-1 P0 构建路径失效 / F-2 P1 内置字体路径失效 / F-3 P1 Windows 平台检查失效）
- 后续：FO 修复后重新提交 `release_module ... review` 复审
