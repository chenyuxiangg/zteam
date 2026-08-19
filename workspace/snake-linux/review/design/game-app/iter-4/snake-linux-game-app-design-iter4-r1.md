# SE 评审意见：game-app 迭代 4 功能模块设计（设计-iter4-r1，首发）

> 评审人：SE · 2026-08-14
> 评审对象：`snake-linux/design/game-app/设计-iter4-r1.md`（MDE r1 首发，1801 行）
> **流程问题提示**：MDE 产物落盘位置错误——文件实际位于 `zteam/snake-linux/design/game-app/`（git 未跟踪新目录），而非流水线约定的 `workspace/snake-linux/design/game-app/`（与 modules.json `design.product` 不一致）。本评审意见按约定写入正确位置。
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`（迭代 4 出口 = 验收 5 开箱即用/6 性能/7 兼容矩阵）；需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved，FR-14/15/16、NFR-01/02/03/04/07）；依赖契约实核 `code/game-core/iter-2/game_core/`（it_passed）、`code/gui-renderer/iter-3/gui_renderer/`（it_passed）、`code/platform-storage/iter-2/platform_storage/`（it_passed）；代码基线 `code/game-app/iter-3/game_app/`（it_passed）

## 结论：FAIL

设计在**迭代边界、出口对齐、错误处理体系设计**上方向正确（迭代 4 = FR-14/15/16 + NFR-01/02/03/04/07，与架构迭代 4 出口验收 5/6/7 一致；退出码 0/1/2/3 + 3 类非致命警告 + HiDPI 降级 + CJK 内置字体 + 三平台打包矩阵的设计意图合理），但存在 **4×P0 可落地性缺陷**（FO 无法据以 TDD 出可用产物）与 **4×P1**（含 1 项流程级产物位置错误），须修订后复审。

## 一、通过项（架构遵循度 + 设计意图）

- **迭代边界与需求对齐** ✓：迭代 4 范围 = FR-14 三平台打包 + FR-15 跨平台一致 + FR-16 用户指南 + NFR-01/02 性能 + NFR-03 错误提示 + NFR-07 发布物，与架构 §迭代计划迭代 4 出口（验收 5/6/7）及分工表完全一致；FR-13/NFR-06 等明确不在本迭代。
- **约束遵循** ✓：不引入 pygame + PyInstaller 外第三方；无音效（R-04）、无网络（NFR-06）、零配置文件（架构 §配置模型）；依赖边界仅公开 API（附录 F 逐条实核了 game-core/gui-renderer/platform-storage 契约，抽查与锁定代码一致——`set_direction` 返回新 GameState、`HighScoreStore` 原子写、`Renderer` 构造签名）。
- **错误体系设计** ✓：退出码 0/1/2/3 语义清晰（§1.1/§3.7/§4.2），建议字段 + stderr 可读提示符合 NFR-03 意图；HiDPI 降级（INV-18）、CJK 字体回退（INV-19/20）、平台版本警告（INV-17）覆盖了可预见失败面；错误矩阵 §5.6 与鲁棒性 §5.5 场景齐全。
- **最小侵入** ✓：增量入口 4 处（errors.py/`_init_pygame`/`_load_cjk_font`/scripts），不新建 iter-4 代码目录（同 v2.0.0 一个发布单元，与 iter-3 先例一致）；主循环骨架沿用，符合架构"不重写"原则。
- **UT 矩阵设计** ✓：ERR/HIDPI/PLAT/FONT/PERF/GUIDE/REL/SHA/BUILD/SPEC 10 组 ~33 用例全部给出输入-断言；6 阶段 TDD 步骤（错误处理 → 字体 → 性能 → 打包 → 文档 → e2e）顺序合理；conftest 新增 fake_warnings/app_iter4 fixture 与既有 fake_pygame/fake_storage/fake_renderer_iter3 兼容。

## 二、P0（阻塞，FO 无法据以产出可用实现）

### P0-1：spec 打包缺依赖模块收集 → 产物运行必崩（FR-14 不可达）

**位置**：§4.9 `spec/snake-gui.spec`（`pathex=[GAME_APP_DIR]`、`collect_submodules("platform_storage"/"gui_renderer")`）。

**实核**：`game_app/app.py` 顶层 `from game_core import ...`、`from gui_renderer import ...`、`from platform_storage import StorageError`；`game_app/menu.py` `from game_core import Difficulty`。但：
- 三个依赖包**未安装**（`pip list` 无；`python3 -c "import game_core"` → ModuleNotFoundError），pytest 靠 `pytest.ini` 的 `pythonpath = ../../game-core/iter-2` 等相对路径解析；
- spec `pathex` 仅含 `GAME_APP_DIR`（`code/game-app/iter-3/game_app`），`collect_submodules("platform_storage")`/`collect_submodules("gui_renderer")` 在 Analysis 环境中**找不到模块**（collect_submodules 对未安装且不在 pathex 的包返回空），PyInstaller 只会报 hidden import 警告后继续 → **产物缺失 game_core/gui_renderer/platform_storage，启动即 ImportError**。

**要求**：spec `pathex` 增加 `code/game-core/iter-2`、`code/gui-renderer/iter-3`、`code/platform-storage/iter-2` 三个绝对路径（或构建脚本构建前 `pip install` 三包），并在构建脚本中体现；FO 冒烟验证须包含"干净机器上产物可启动"（当前 BUILD-1 只验证文件生成，不验证启动）。

### P0-2：`get_bundled_font_path` 查找路径与 spec datas 目标目录不匹配 → 内置字体永远加载不到（G4-5 失效，INV-20 不可达）

**位置**：§1.3 `_constants.py get_bundled_font_path()` vs §4.9 spec `datas = [(..., "fonts")]`。

**实核**：
- spec `datas` 目标为 `"fonts"` 目录 → PyInstaller 解压后文件在 `_MEIPASS/fonts/SourceHanSansCN-Regular.otf`；
- `get_bundled_font_path()` 却查找 `os.path.join(meipass, BUNDLED_FONT_FILENAME)` = `_MEIPASS/SourceHanSansCN-Regular.otf`（根目录，**不在 fonts/ 子目录**）→ 找不到；
- 源码模式：`here = dirname(__file__)`（`_constants.py` 位于 `game_app/` 根）→ 查找 `game_app/SourceHanSansCN-Regular.otf`，但 §4.1 文件树字体在 `game_app/fonts/` 子目录 → **同样找不到**。

**要求**：统一为 `_MEIPASS/fonts/` 与 `game_app/fonts/` 两条候选路径（或 datas 目标改为 "."）。否则内置字体机制形同虚设，永远走 match_font 回退链（INV-20 断言第 1 优先级不可达，FONT-1 UT 必红）。

### P0-3：`error_to_exit_code` 映射顺序 bug → 退出码 2/3 永远返回 1（ERR-5 UT 必红）

**位置**：§3.7 `_EXIT_CODE_MAP` + `error_to_exit_code()`。

**实核**：dict 按插入顺序遍历 `ConfigError(1) → AppError(1) → GraphicsUnavailableError(2) → StorageUnavailableError(3)`；`GraphicsUnavailableError`/`StorageUnavailableError` 均为 `AppError` 子类，`isinstance(gi, AppError)` 在遍历到第 2 项时即命中 → **返回 1**，精确类型分支（2/3）永远不可达。注释"优先级：精确类型 > 基类"与实现相反。注意 §4.2 `run()` 的 except 顺序（精确类型在前）是正确的，两处不一致。

**要求**：`_EXIT_CODE_MAP` 精确子类排在基类之前（GraphicsUnavailableError → StorageUnavailableError → ConfigError → AppError 兜底），或改为 `type(error) in map` 精确匹配 + isinstance 兜底；补充 ERR-5 断言已在设计中，实现须与之相符。

### P0-4：性能基准脚本 import 路径错误 → NFR-01/02 实测脚本跑不起来（验收 6 依赖实测留档）

**位置**：§4.11.1 `bench_fps.py`、§4.11.2 `bench_memory.py`。

**实核**：
1. `bench_fps.py`：`sys.path.insert` 仅加 `code/game-app/iter-3`，随后 `from game_core import Difficulty` —— game_core 位于 `code/game-core/iter-2/`，不在 sys.path 且未安装 → **ImportError**；
2. `from perf import TARGET_FPS, ...` —— `perf.py` 在 `game_app/` 包内（§4.1 文件树 `game_app/perf.py`），`from perf import` 找不到顶层 `perf` 模块（iter-3 目录下无 perf.py）→ **ImportError**，应为 `from game_app.perf import ...`；
3. `bench_memory.py`：**无任何 sys.path 引导**，直接 `from game_app import App` / `from perf import ...`，脚本在 `scripts/` 下运行时 sys.path[0]=`scripts/` → **ImportError**。

**要求**：三个依赖包路径（`code/game-core/iter-2`、`code/gui-renderer/iter-3`、`code/platform-storage/iter-2`）+ `iter-3` 目录统一加入 sys.path；`from perf import` 改为 `from game_app.perf import`（或经 game_app re-export）。基准脚本是 NFR-01/02 唯一实测留档手段，跑不起来 = 验收 6 无证据。

## 三、P1（须修订，FO 落地前闭环）

### P1-1：主循环内 StorageUnavailableError 退出码与错误矩阵矛盾

**位置**：§4.2 `run()` 主循环 `except AppError as e: return 1` vs §5.6 错误矩阵"`score_callback` 内 `storage.save` 失败 → 退出码 3"。

**实核**：`score_callback` 在 `_tick` → `step` 链内执行，若 `save` 抛 `StorageUnavailableError`（AppError 子类），被主循环 `except AppError` 捕获 → **返回 1**，与错误矩阵声明（退出码 3）矛盾。`_dispatch_menu(RESET_HIGHSCORE)` 路径同理（若在 `_init_pygame` 之外触发）。

**要求**：主循环 except 顺序补 `StorageUnavailableError → 3`（与 §4.2 `_init_pygame` 段一致），或错误矩阵改述为 1——二选一，必须一致。

### P1-2：Windows 平台版本检查取错字段 → 判断永不触发

**位置**：§4.7 `_check_platform_version()`。

**实核**：`platform.win32_ver()` 返回 `(version, hostname, build, platform)`，`[1]` 是 **hostname**（如 "DESKTOP-ABC"），非版本号；`int("DESKTOP-ABC".split(".")[0])` 抛 ValueError → 被 `except (ValueError, IndexError): pass` 吞掉 → **Windows <10 检查永远不触发**。PLAT-2 在 mock 下可能过，真机失效。

**要求**：改用 `platform.win32_ver()[0]`（NT 版本 "10"）或 `platform.release()`；补真机/`platform` 桩断言。

### P1-3：build_macos.sh lipo 合并只合并二进制，.app bundle 结构不完整

**位置**：§4.10.3 `build_macos.sh`。

**实核**：`pyinstaller --target-arch arm64` 生成完整 `dist/snake-gui.app` 后 `mv` 为 `snake-gui-arm64.app`；随后 `mkdir -p dist/snake-gui.app/Contents/MacOS` + `lipo -create -output dist/snake-gui.app/Contents/MacOS/snake-gui` —— **新建的 snake-gui.app 只有 Contents/MacOS/snake-gui 一个二进制，缺 Info.plist、资源、框架等 bundle 结构**（PyInstaller 生成的 .app 不止二进制），双击无法启动。

**要求**：以 arm64 完整 .app 为基础，仅替换其中 `Contents/MacOS/snake-gui` 为 lipo 合并产物（`lipo -create intel 二进制 arm64 二进制 -output <arm64 app>/Contents/MacOS/snake-gui`），勿重建 bundle；BUILD-3 冒烟增加"产物为可启动 .app"断言。

### P1-4：MDE 产物落盘位置错误（流程级）

**位置**：迭代 4 设计产物实际在 `zteam/snake-linux/design/game-app/设计-iter4-r1.md`（git 未跟踪新目录），与 modules.json `design.product = "snake-linux/design/game-app/"`（相对 workspace）不一致。

**影响**：下游 FO 按 product 路径取设计会找不到文件；git 恢复/归档链路断裂。

**要求**：MDE 修订时迁移到 `workspace/snake-linux/design/game-app/`，并清理误建目录 `zteam/snake-linux/`；后续 spawn 指令需显式 workspace 前缀或校验落盘路径。

## 四、P2（文档/视觉级，FO 落地时一并处理，不阻塞）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | §4.10.2 build_windows.bat | `certutil -hashfile ... SHA256` 输出为两行格式（"SHA256 hash of file x:" + hash），非 §6.3 SHA-1 断言标准 `"<64-hex>  <file>"` → Windows 侧 SHA-1 UT 红 | certutil 输出用 `for /f` 提取 hash 拼标准格式，或 SHA-1 断言放宽为"含 64-hex 即过" |
| P2-2 | §4.10.1/2/3 + §4.10.4 | 三平台构建脚本各自生成 `dist/SHA256SUMS`（互相覆盖），gen_sha256sums.sh 又生成一次——职责重复且跨平台汇总时文件名冲突 | 构建脚本只产包不产校验和，统一由 gen_sha256sums.sh 在发布机汇总 |
| P2-3 | §4.12 USER_GUIDE / §4.13 RELEASE_NOTES | 下载链接为 `https://example.com/...` 占位符 | 明确标注"发布时替换为真实下载地址"，或改为相对路径引用 SHA256SUMS |
| P2-4 | §3.4 App docstring | 声称"`_on_bench_complete` 钩子供 scripts/bench_fps.py 调用"，但 §4.11.1 实际代码未调用该钩子（直接 `_init_pygame/_new_game/_tick/_render`） | 删 docstring 声明或实现钩子，二者一致 |
| P2-5 | §6.5 UT 运行命令 | `python3 -m unittest discover -s tests/test_game_app` 不读 pytest.ini 的 pythonpath → 直接运行 ImportError（依赖包未装） | 命令改为 pytest 或前置 `PYTHONPATH=../../game-core/iter-2:...` |
| P2-6 | §6.3 ERR-3/4 | `StorageUnavailableError` 语义变更（iter-3 退出码 1 → iter-4 退出码 3）：iter-3 既有 UT 若断言旧语义会红 | 修订清单明确列出需同步修改的 iter-3 既有用例 |

## 五、修订要求（复审清单）

1. **P0-1**：spec pathex 补三依赖包路径（或构建前安装），BUILD-1 冒烟加"产物可启动"；
2. **P0-2**：`get_bundled_font_path` 与 datas 目标目录统一（`fonts/` 子目录），FONT-1 UT 断言可达；
3. **P0-3**：`error_to_exit_code` 精确子类优先，ERR-5 断言相符；
4. **P0-4**：bench 脚本 sys.path 补全 + `game_app.perf` 导入修正，脚本可实跑；
5. **P1-1**：主循环 StorageUnavailableError → 退出码 3，与错误矩阵一致；
6. **P1-2**：`win32_ver()` 取 version 字段（`[0]`）或 `platform.release()`；
7. **P1-3**：macOS lipo 以 arm64 完整 .app 为基础替换二进制，不重建 bundle；
8. **P1-4**：设计产物迁移至 `workspace/snake-linux/design/game-app/`，清理误建目录；
9. P2-1~6 一并处理。

> 修订版（r2）提交复审时：逐条对照以上编号说明修订方式（与 iter-3 r2 修订对照表同构），并附修订后 P0 项的代码级推演或实跑证据。
