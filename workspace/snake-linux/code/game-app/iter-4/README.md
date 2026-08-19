# game-app 迭代 4（交付打磨）· TDD 开发产物

> 模块：game-app（v2.0.0 迭代 4）
> 角色：FO（开发者，TDD）
> 设计依据：`snake-linux/design/game-app/设计-iter4-r2.md`（SE 评审 PASS 后修订版）
> 交付目录：`snake-linux/code/game-app/iter-4/`
> 检视记录：`snake-linux/review/code/game-app/iter-4/MDE-代码检视-iter4.md`
> （r1 检视 FAIL → 本版修复 F-1/F-2/F-3 后复审）

## 本迭代范围（G4 增量）

| 项 | 内容 | 落地位置 |
|----|------|---------|
| G4-1 三平台打包矩阵 | PyInstaller spec + 三平台构建脚本 + SHA256SUMS | `snake-linux/spec/snake-gui.spec`、`snake-linux/scripts/build_*.{sh,bat}`、`snake-linux/scripts/gen_sha256sums.sh`、`snake-linux/release/SHA256SUMS` |
| G4-2 错误提示完善 | 退出码 3（StorageUnavailableError）+ suggestion 字段 + HiDPI 降级 + 平台版本检查 + 3 类非致命警告 | `game_app/errors.py`、`game_app/app.py` |
| G4-3 性能 profile | perf.py 常量 + bench_fps + bench_memory | `game_app/perf.py`、`snake-linux/scripts/bench_*.py` |
| G4-4 用户指南 | USER_GUIDE.md 七小节 | `snake-linux/release/USER_GUIDE.md` |
| G4-5 打包内置字体 | SourceHanSansCN-Regular.otf（OFL）+ 路径定位 | `game_app/fonts/`、`game_app/_constants.py`、`game_app/fonts.py` |
| G4-6 发布说明 | RELEASE_NOTES.md | `snake-linux/release/RELEASE_NOTES.md` |
| G4-7 回归全模块 | 185 项 UT 全绿 | `tests/test_game_app/` |

## 目录结构

```
iter-4/
├── game_app/                  # 完整实现（iter-1/2/3 全量沿用 + iter-4 增量）
│   ├── __main__.py            # PyInstaller 入口
│   ├── app.py                 # 主装配 + G4-2 错误处理（退出码 0/1/2/3）
│   ├── errors.py              # AppError 子类 + 3 类警告 + error_to_exit_code
│   ├── perf.py                # G4-3 性能常量（NFR-01/02）
│   ├── _constants.py          # G4-5 get_bundled_font_path
│   ├── fonts.py               # G4-5 内置字体优先回退链
│   ├── input.py / menu.py / config.py / screens.py / storage.py
│   └── fonts/
│       ├── SourceHanSansCN-Regular.otf   # 内置中文字体（OFL-1.1，8.4MB）
│       └── README.md                     # license 与使用说明
├── tests/test_game_app/       # 185 项 UT（iter-1~4 全量）
│   ├── conftest.py            # pygame 桩 + fixtures
│   ├── test_app_iter3_*.py    # 沿用 iter-3
│   ├── test_app_iter4_errors.py        # G4-2 错误类型 + 退出码映射
│   ├── test_app_iter4_hidpi_platform.py# G4-2 HiDPI 降级 + 平台检查
│   ├── test_app_iter4_font.py          # G4-5 字体优先级
│   ├── test_app_iter4_perf.py          # G4-3 常量
│   ├── test_app_iter4_bench.py         # G4-3 bench 判定逻辑（PERF-2~5）
│   ├── test_app_iter4_spec.py          # G4-1 spec 文件
│   ├── test_app_iter4_build.py         # G4-1 构建脚本冒烟 + 字体资产
│   └── test_app_iter4_docs.py          # G4-4/6/1 文档字段完备性 + SHA256SUMS
└── pytest.ini
```

## UT 运行

```bash
cd snake-linux/code/game-app/iter-4
python3 -m pytest tests/test_game_app -q
# 期望：185 passed（2026-08-15 实测）
```

## 检视修复记录（r1 FAIL → r2 复审版）

| 编号 | 问题 | 修复 |
|------|------|------|
| **F-1（P0）** | spec `GAME_APP_DIR` 指向资产层空目录，PyInstaller 构建必败 | spec 改为候选探测（资产层 iter-4 → iter-3 → 数据层 iter-4 → iter-3），三依赖包同 code_root 探测；`test_app_iter4_spec.py` 新增"候选目录真实存在 `__main__.py`/字体"断言，`test_app_iter4_build.py` 新增 spec 入口 isfile 断言 |
| **F-2（P1）** | `get_bundled_font_path` 两分支漏 `fonts/` 子目录，INV-20 不成立 | `_constants.py` 新增 `BUNDLED_FONT_SUBDIR="fonts"`，两分支均拼接子目录；测试 mock 布局改为真实交付（`<game_app>/fonts/<file>`、`<_MEIPASS>/fonts/<file>`） |
| **F-3（P1）** | `win32_ver()[1]` 取 csd 非版本号，Windows 检查静默失效 | `_check_platform_version` 改取 `[0]` + `release()` 兜底；PLAT-2 测试 mock 改 `("8.1","","","")` version 位结构 |
| 风格（MDE §5） | 函数内 import / 重复 gui_renderer import / errors docstring 过时 / `_hidpi_degraded_marker` 绕道 | import 全部上移合并；errors.py docstring 退出码 1→3；`_create_renderer_with_hidpi_fallback` 改返回 `(renderer, degraded)` 二元组（不再写 Renderer 私有属性） |
| 测试脱节（MDE §4.2） | 4 组测试 mock 与真实交付布局不符，绿测掩盖缺陷 | 对应测试全部修正（spec 路径实存 / 字体 fonts/ 子目录 / win32_ver version 位） |

## 关键设计点

1. **退出码语义**（G4-2）：0 正常 / 1 app 异常 / 2 图形环境不可用 / 3 用户数据目录不可写。
2. **HiDPI 降级**（G4-2）：`_create_renderer_with_hidpi_fallback` 首次 SCALED 失败 →
   HighDPIWarning + 降级非 SCALED → 再失败抛 GraphicsUnavailableError（退出码 2）。
3. **字体优先级**（G4-5，INV-20，检视 F-2 修订）：`sys._MEIPASS/fonts/` > `<game_app>/fonts/` >
   match_font 回退链 > Font(None)——两处内置路径均含 `fonts/` 子目录（与 spec datas 目标一致）。
4. **构建脚本**（G4-1）：Linux/macOS 用 `bash scripts/build_linux.sh` / `build_macos.sh`；
   Windows 用 `scripts\build_windows.bat`；三平台原生构建（PyInstaller 不支持交叉打包）。
5. **性能实测**（G4-3）：`python3 scripts/bench_fps.py`（NFR-01 ≥60FPS，P95≤25ms）、
   `python3 scripts/bench_memory.py`（NFR-02 ≤300MB）；判定逻辑为纯函数可单测，
   真实窗口基准需在带显示环境执行。

## 边界与注意

- 本机无 PyInstaller / 无显示环境：构建脚本冒烟（静态语法 + 关键命令存在）已由
  `test_app_iter4_build.py` 覆盖；真实打包需在三平台构建机执行
  （`design` 文档 §6.6 手工验证清单）。
- 无网络依赖：全模块不 import socket/urllib/http/requests；打包资源（字体）已随目录交付。
- Python 3.8 兼容：无 3.9+ 语法。
