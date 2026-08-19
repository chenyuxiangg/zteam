# SE 评审意见：game-app 迭代 4 功能模块设计（设计-iter4-r2，SE 修订复审）

> 评审人：SE · 2026-08-14
> 评审对象：`workspace/snake-linux/design/game-app/设计-iter4-r2.md`（MDE r2 修订版，1957 行）
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`（迭代 4 出口 = 验收 5 开箱即用/6 性能/7 兼容矩阵）；需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved，FR-14/15/16、NFR-01/02/03/04/07）；前序评审 `review/design/game-app/iter-4/snake-linux-game-app-design-iter4-r1.md`（FAIL：4×P0 + 4×P1 + 6×P2）
> 独立实核（本评审逐条复核，非采信设计自述）：依赖包源码 `code/game-core/iter-2/game_core/`、`code/gui-renderer/iter-3/gui_renderer/`、`code/platform-storage/iter-2/platform_storage/`（均 it_passed）；代码基线 `code/game-app/iter-3/game_app/`（it_passed）；pytest 配置 `code/game-app/iter-3/pytest.ini`

## 结论：PASS

r2 已**逐条闭环** r1 评审的 4×P0 + 4×P1 + 6×P2（附录 D 修订对照表完整、编号一一对应），并经本次独立实核确认**修订后代码可落地**：三依赖包路径存在且 `pathex` 补齐后 PyInstaller 收集链成立、`fonts/` 子目录与 spec `datas` 目标一致、退出码映射精确子类优先逻辑推演正确、bench 脚本 sys.path/导入路径与源码布局吻合、主循环/错误矩阵退出码语义统一。**FO 可据本文 TDD 产出可用产物**。残留 3 项 P2 级提示（见 §四），不阻塞，FO 落地时一并处理。

## 一、r1 P0 修订闭环实核（全部通过）

| 编号 | r1 问题 | r2 修订 | SE 独立实核 |
|------|---------|---------|-------------|
| **P0-1** | spec 打包缺依赖模块收集 → 产物必崩 | §4.9 `pathex` 增 GAME_CORE_DIR / GUI_RENDERER_DIR / PLATFORM_STORAGE_DIR；BUILD-1 加"产物可启动"断言（3 秒内不抛 ImportError）；SPEC-4 UT | ✅ 实核：`game_app/app.py:54,62,68` 顶层 `from game_core/gui_renderer/platform_storage import`；三依赖包目录均存在且含包（`game_core/` `gui_renderer/` `platform_storage/`）；`pytest.ini pythonpath` 用相对路径解析——**打包场景必须靠 pathex，修订正确且必要** |
| **P0-2** | `get_bundled_font_path` 与 datas 目标目录不匹配 → 内置字体永远加载不到 | §1.3 新增 `BUNDLED_FONT_SUBDIR="fonts"`，查找 `<_MEIPASS>/fonts/<file>` 与 `<game_app>/fonts/<file>`；spec `datas` 目标 `"fonts"`；FONT-6/SPEC-2 UT 断言一致 | ✅ 实核：两处路径现完全同构（`meipass/fonts/` ↔ `here/fonts/` ↔ datas `"fonts"`）；INV-20 第一优先级可达，FONT-1/6 UT 断言可绿 |
| **P0-3** | `error_to_exit_code` 基类先命中 → 2/3 永远返 1 | §3.7 `_EXIT_CODE_MAP` 重排：ConfigError(1) → GraphicsUnavailableError(2) → StorageUnavailableError(3) → AppError(1 兜底)；附 ERR-5 推演断言 + ERR-6 UT | ✅ 实核（代码级推演）：isinstance 按插入序遍历，GraphicsUnavailableError/StorageUnavailableError 均在基类 AppError 之前命中；ConfigError 第 1 项命中返 1；普通 AppError 第 4 项兜底返 1。**逻辑正确**，注释"优先级：精确类型 > 基类"与实现一致（r1 时两者相反） |
| **P0-4** | bench 脚本 import 路径错误 → NFR-01/02 实测跑不起来 | §4.11 两脚本 `sys.path.insert` 补三依赖包 + iter-3 目录；`from perf` 改 `from game_app.perf`；PERF-6 UT | ✅ 实核：`PROJECT_ROOT = dirname(scripts/..)` 拼接的四个路径与源码布局逐一相符；`game_app/__init__.py` re-export `App/AppConfigV3`（`from game_app import` 成立）；`game_core/state.py:156 set_direction -> "GameState"` 返回新状态（bench 内 `app.game_state = ...set_direction(...)` 成立）；`renderer.py:484 fps_metric()` 存在 |

## 二、r1 P1 修订闭环实核（全部通过）

| 编号 | r1 问题 | r2 修订 | SE 独立实核 |
|------|---------|---------|-------------|
| **P1-1** | 主循环 StorageUnavailableError 被 AppError 吞 → 返 1 与矩阵矛盾 | §4.2 主循环 `except StorageUnavailableError` 置于 `except AppError` 之前 → return 3；§5.6 错误矩阵明确 score_callback / dispatch_menu / save 三路径均映射 3；ERR-7 UT | ✅ 实核：except 顺序与 `_init_pygame` 段一致，语义统一；§5.6 矩阵行（mkdir/save/dispatch/score_callback → 3）与 §4.2 完全对应，无残留矛盾 |
| **P1-2** | Windows 版本取 `win32_ver()[1]`（hostname）→ 判断永不触发 | §4.7 取 `win32_ver()[0]`（NT 版本），空值兜底 `platform.release()`；PLAT-2 UT 修订为 mock `("10", hostname, build)` | ✅ 实核：`win32_ver()` 返回 `(version, hostname, build, platform)`，取 `[0]` 正确；`int("10".split(".")[0])` 可解析，警告可达；双兜底（release()）防御合理 |
| **P1-3** | build_macos.sh lipo 重建 bundle → 缺 Info.plist/资源 | §4.10.3 改 `cp -R dist/snake-gui-arm64.app dist/snake-gui.app` + `lipo -create -output .../Contents/MacOS/snake-gui`；BUILD-3 断言 Info.plist + 可执行二进制 | ✅ 实核：以 arm64 完整 .app 为基复制后仅替换二进制，bundle 结构保留；脚本逻辑自洽，BUILD-3 断言可达 |
| **P1-4** | MDE 产物落盘位置错误（流程级） | §0 约束 13 + 附录 E issue-008 固化：产物固定 `workspace/snake-linux/design/game-app/` | ✅ 实核：r2 已正确落盘 `workspace/snake-linux/design/game-app/设计-iter4-r2.md`（与 modules.json `design.product` 一致）；误建目录 `zteam/snake-linux/` 残留 r1 副本 1 个（git 未跟踪），**清理动作未执行**——见 §四 P2-7 |

## 三、通过项（架构遵循度 + 可落地性）

- **迭代边界与架构对齐** ✓：迭代 4 = FR-14/15/16 + NFR-01/02/03/04/07，与架构 §迭代计划迭代 4 出口（验收 5/6/7）及分工表一致；不新建 iter-4 代码目录（沿用 iter-3 目录，与 modules.json iter-3.dev_product 一致，同 v2.0.0 一个发布单元）。
- **约束遵循** ✓：零配置（不读 ini/env/YAML）、无网络（不 import socket/urllib/http/requests）、无音效（不 import pygame.mixer）、依赖边界仅公开 API；打包体积/签名公证等架构未要求项明确标注不实施（约束 11/12 + 附录 E）。
- **最小侵入** ✓：增量入口仅 4 处（errors.py / _init_pygame / _load_cjk_font / scripts+spec+docs），主循环骨架沿用；r2 删除 `_on_bench_complete` 钩子声明（P2-4）后 docstring 与实现一致。
- **错误处理体系完整** ✓：退出码 0/1/2/3 四类 + 3 类非致命警告（HiDPI/CJK/PlatformUnsupported）+ suggestion 字段 + stderr 可读提示；INV-17/18/19/20 不变量与 §5.5 鲁棒性表、§5.6 错误矩阵三方一致。
- **TDD 可执行** ✓：§6.3 测试用例清单（33 用例：ERR-1~7/HIDPI-1~4/PLAT-1~3/FONT-1~6/PERF-1~6/GUIDE-1~3/REL-1~2/SHA-1~2/BUILD-1~3/SPEC-1~4）全部含输入-断言；§6.6 六阶段 TDD 步骤顺序合理（错误处理→字体→性能→打包→文档→e2e）；conftest 新增 `fake_warnings`/`app_iter4` 与既有 fixtures 兼容。
- **流程产物位置** ✓：评审意见落盘 `review/design/game-app/iter-4/`（与 modules.json design.reviews 第 8 项一致）。

## 四、P2（不阻塞，FO 落地时一并处理）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-7 | `zteam/snake-linux/`（git 根） | r1 误建目录仍残留 `design/game-app/设计-iter4-r1.md` 一个文件（git 未跟踪），P1-4 的"清理误建目录"动作未执行；下游按 product 路径取文件不受影响，但 git 仓库残留脏目录 | MDE/运维删除 `zteam/snake-linux/` 目录（r1 已归档在 review/iter-4/ 与 workspace 下，无信息损失）；后续 spawn 校验落盘路径 |
| P2-8 | §4.11 bench 脚本 | `app._init_pygame()` + `_render()` 依赖真实窗口（SDL 显示环境），headless CI 会失败；§6.6 步骤 24 已注明"真窗口性能验证"属手工清单，但 §6.3 PERF-2/3 的 mock 时间测的是判定逻辑非渲染链路 | 明确标注"bench 脚本仅真机/带显示环境运行"，UT 只测判定逻辑（现状设计即如此，仅需文档明示）；CI 中挂 `SDL_VIDEODRIVER=dummy` 时可降级为逻辑冒烟 |
| P2-9 | §6.7 修订清单 | 实核 iter-3 测试目录（`tests/test_game_app/`）无 `test_app_iter3_storage.py` / `test_app_iter3_dispatch.py`，即**无既有用例断言 StorageUnavailableError → exit 1**；§6.7 清单为防御性"若存在"表述，实际零修订 | 清单保留（防御 iter-3 后续补测场景）；FO 落地时按清单 grep 复核即可，无需改动 |

## 五、FO 落地提示（非问题，强化可落地性）

1. **P0-1 冒烟**：BUILD-1 的"产物可启动"断言在干净环境（无 pythonpath 辅助）下才能暴露 ImportError——CI 冒烟建议用 `env -i` 或独立 venv 运行产物，避免宿主环境遮蔽。
2. **spec datas 路径**：FO 需先确保 `game_app/fonts/SourceHanSansCN-Regular.otf` 文件存在（OFL 字体），spec `datas` 引用的是**源码目录**（`GAME_APP_DIR/fonts/`），与 `get_bundled_font_path` 的源码分支一致；下载字体属 FO 第一步（§6.6 步骤 6）。
3. **退出码脚本消费**：`console=False`（--windowed）下 Windows/macOS 无控制台，stderr 建议文本不可见，但退出码仍可经 ERRORLEVEL/$? 获取——用户指南 §7 已列退出码表，符合设计意图。

---

> 复审结论：**PASS**。r1 的 4×P0 + 4×P1 + 6×P2 全部闭环并经独立实核；残留 P2-7~9 不阻塞，随 FO 落地处理。按 `release_module snake-linux game-app 4 design <本意见> PASS` 推进至 dev_working。
