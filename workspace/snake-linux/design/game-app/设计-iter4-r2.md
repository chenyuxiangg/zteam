# 功能模块设计：game-app（snake-linux v2.0.0 迭代 4）r2（SE 评审修订版）

> MDE r2 · 跨迭代复用基线：
>   - 迭代 4 设计 r1 `snake-linux/design/game-app/设计-iter4-r1.md`（**SE 评审 FAIL**：4×P0 + 4×P1 + 6×P2）
>   - 迭代 3 设计 `snake-linux/design/game-app/设计-iter3-r2.md`（**SE 评审 PASS**，r2-1/r2-2/r2-3 全链修订落地）
>   - 迭代 3 实际代码：`snake-linux/code/game-app/iter-3/game_app/`（it_passed，**实核确认沿用 iter-1 源码目录 + iter-3 增量**——参见 modules.json 中 iter-3.dev_product）
>   - 迭代 2 设计 `snake-linux/design/game-app/设计-iter2-r2.md`（PASS）+ 迭代 1 设计 `snake-linux/design/game-app/设计-r3.md`（PASS）
> 依据：
>   - 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` §迭代计划迭代 4
>   - 功能模块分工表 `snake-linux/arch/v2.0.0/功能模块分工表.md` §迭代 4
>   - 需求规格 `snake-linux/analysis/snake-gui-r1.md` FR-14/FR-15/FR-16/NFR-01/NFR-02/NFR-03/NFR-04/NFR-07 + R-04~R-06 拍板固化
>   - SE 评审 `snake-linux/review/design/game-app/iter-4/snake-linux-game-app-design-iter4-r1.md`（**r2 本版逐条 P0/P1/P2 修订**）
> 依赖模块实核契约（**全部 it_passed，契约已锁定**）：
>   - **game-core 迭代 2** `code/game-core/iter-2/game_core/`：快照接口 + 难度参数 + 反向禁止 + 加速曲线 + set_score_callback（沿用）
>   - **gui-renderer 迭代 3** `code/gui-renderer/iter-3/gui_renderer/`：`Renderer` 构造 + `init`/`shutdown`/`render(snap, hud, *, interp)` + `set_skin` + `handle_resize` + `skin_names`/`current_skin_name` + `fps_metric()` + `SKIN_REGISTRY` 3 套（经典/深色/色盲友好）+ **r2-2 契约前置**：`init`/`handle_resize` 必须带 `pygame.RESIZABLE` 标志
>   - **platform-storage 迭代 2** `code/platform-storage/iter-2/platform_storage/`：`create_storage()` + `HighScoreStore` 原子写 + 三平台用户数据目录（沿用）
> **目标**：FO 拿到本文即可 TDD 开发；迭代 4 **不新建 iter-4 代码目录**，所有增量落在 `code/game-app/iter-3/game_app/`（同 v2.0.0 一个发布单元）；PyInstaller 三平台打包矩阵 + 错误提示完善 + 性能 profile + 用户指南 + 发布物清单
> **关键决策**：
> 1. **打包矩阵三平台原生构建**（G4-1）：PyInstaller `--onefile --windowed --name snake-gui` + Linux ELF / Windows .exe / macOS .app（含 Intel + Apple Silicon 双架构）；**不支持交叉打包**——各平台在对应原生系统构建；`.spec` 文件 + `scripts/build/` 平台脚本 + CI 三平台矩阵
> 2. **错误提示多层降级**（G4-2）：SDL 缺失 → 友好 stderr；HiDPI 缩放异常 → stderr warning + 自动降级；CJK 字体全失败 → 英文兜底；窗口事件源（RESIZABLE）失效 → 不阻塞启动（FR-09 仅失去，不致命）
> 3. **性能回归脚本**（G4-3）：`scripts/bench_fps.py` + `scripts/bench_memory.py`，NFR-01 ≥60FPS / NFR-02 ≤300MB 实测留档；调用 `Renderer.fps_metric()` 已有接口
> 4. **打包内置字体**（G4-5）：`_load_cjk_font` 走 `sys._MEIPASS/fonts/` 与 `__file__/fonts/` 双候选路径（**r2 修订**：与 spec `datas` 目标目录 `fonts/` 一致）查找内置字体文件（如 `SourceHanSansCN-Regular.otf`），避免 Linux 字体版本差异导致中文字形缺失
> 5. **用户指南五节齐全**（G4-4，FR-16）：下载与运行 / 键位表 / 难度 / 皮肤 / 暂停 / 平台差异 / 已知限制——与 v1 终端版 README 同构

---

## 0. 模块定位与迭代边界

| 项 | 值 |
|----|---|
| 模块 | game-app |
| 类型 | 上层应用 |
| 依赖 | game-core（iter-2 it_passed）、gui-renderer（iter-3 it_passed + r2-2 RESIZABLE 契约前置）、platform-storage（iter-2 it_passed） |
| 被依赖 | 无（顶层装配） |
| 承载需求 | snake-gui **主体**（FR-01~16 + NFR-01~07）—— 本迭代 4 范围 = **FR-14 三平台打包** + **FR-15 跨平台一致** + **FR-16 用户指南** + **NFR-01/02 性能** + **NFR-03 错误提示完善** + **NFR-07 发布物** |
| 迭代 | 4（交付打磨） |
| 不引入 | 第三方除 pygame + PyInstaller 外任何依赖；不引入音效（R-04）；不引入网络（R-05/NFR-06）；不引入 config 文件（架构 §配置模型） |
| 跨迭代复用 | 主循环骨架 / 状态机 / 输入映射 / 错误处理框架 / AppConfigV3 / CJK 字体 / 退出码 1-4 迭代复用；迭代 4 通过**新增错误类型 + 错误处理器 + 打包脚本 + 用户指南 + 性能脚本**接入，不重写主循环 |
| PyInstaller 入口 | `snake-linux/code/game-app/iter-3/game_app/__main__.py`（沿用 iter-3：`if __name__ == "__main__": main()`） |
| 输出打包资源 | `dist/`：`snake-gui`（Linux ELF）+ `snake-gui.exe`（Windows）+ `snake-gui.app`（macOS，含 Intel + Apple Silicon 双架构）+ `SHA256SUMS` + `RELEASE_NOTES.md` + `USER_GUIDE.md` + 内置字体 `SourceHanSansCN-Regular.otf`（置于 `_MEIPASS/fonts/` 与 `game_app/fonts/`，**r2 修订**：统一 `fonts/` 子目录） |

### 迭代 4 出口（与架构 §迭代计划对齐）

- ✅ **三平台 PyInstaller 打包矩阵**（G4-1，FR-14）：`.spec` 文件 + `scripts/build_linux.sh` + `scripts/build_windows.bat` + `scripts/build_macos.sh`；Linux ELF / Windows .exe / macOS .app（双架构）
- ✅ **发布物 SHA256SUMS**（G4-1，NFR-07）：三平台包校验和；**r2 修订**：仅由 `scripts/gen_sha256sums.sh` 统一生成，构建脚本只产包不产校验和
- ✅ **可读错误提示完善**（G4-2，NFR-03）：SDL 驱动缺失 / HiDPI 异常 / CJK 字体全失败 / 平台不兼容（macOS <12 / Windows <10） / 用户数据目录不可写 等可预见失败均输出人类可读 stderr
- ✅ **错误退出码扩展**（G4-2）：0 正常 / 1 app 异常 / 2 图形环境不可用 / 3 用户数据目录不可写（新增，区分错误类型便于用户/脚本判断）；**r2 修订**：精确子类优先映射（GraphicsUnavailableError → 2 优先于 AppError → 1；StorageUnavailableError → 3 优先于 AppError → 1）
- ✅ **性能 profile 脚本**（G4-3，NFR-01/02）：`scripts/bench_fps.py` + `scripts/bench_memory.py`，跑 60 秒基准，记录 P95 帧时间 / 平均 FPS / 内存峰值留档；**r2 修订**：sys.path 补全三依赖包 + 经 `game_app.perf` re-export
- ✅ **用户指南**（G4-4，FR-16）：`snake-linux/release/USER_GUIDE.md`（五节齐全：下载运行 / 键位表 / 难度 / 皮肤 / 暂停 / 平台差异 / 已知限制）；**r2 修订**：下载链接标注"发布时替换为真实下载地址"
- ✅ **打包内置字体**（G4-5）：`SourceHanSansCN-Regular.otf`（或同源开源中文字体，license 兼容——优先选用 OFL 协议）打包进 `game_app/fonts/` 模块目录；`_load_cjk_font` 优先查内置文件 → 失败再走 `pygame.font.match_font` 回退链；**r2 修订**：`get_bundled_font_path()` 与 spec `datas` 统一为 `fonts/` 子目录
- ✅ **发布说明**（G4-6）：`snake-linux/release/RELEASE_NOTES.md`（v2.0.0 changelog + 三平台下载链接 + 校验和）；**r2 修订**：下载链接标注"发布时替换为真实下载地址"
- ✅ **回归全模块**（G4-7）：game-app iter-4 测试用例覆盖错误路径 + 打包脚本冒烟测试（含"产物可启动"断言）+ 用户指南字段完备性
- ✅ **跨迭代沿用**：主循环骨架 / 状态机 / 输入映射 / 错误处理框架 / AppConfigV3 / CJK 字体 / 退出码 1-4 迭代复用

### 迭代 4 已知技术约束（FO 实现必读）

1. **Python 3.8 兼容**：与架构 §代码风格约定一致；不引入 3.9+ 新语法。
2. **零配置**：不读 ini/env/YAML/JSON 配置；难度/皮肤通过游戏内 UI 选择。
3. **无网络**：全模块不 `import socket` / `import urllib` / `import http` / `import requests`；UT 与打包脚本不发起网络。
4. **无音效**：不 `import pygame.mixer` 或任何音频模块。
5. **依赖边界**：game-app 可 import pygame + PyInstaller；不侵入 game-core / gui-renderer / platform-storage 内部（仅公开 API）。
6. **打包专用目录**：`snake-linux/code/game-app/iter-3/game_app/fonts/` 内置字体文件（PyInstaller `--add-data` 注入到 `_MEIPASS/fonts/`，**r2 修订**：与源码 `fonts/` 同名）；`snake-linux/scripts/build_*.{sh,bat}` 构建脚本；`snake-linux/spec/snake-gui.spec` PyInstaller 配置。
7. **r2-2 VIDEORESIZE 契约前置**（沿用 iter-3）：gui-renderer iter-3 `init()`/`handle_resize` 必须带 `pygame.RESIZABLE` 标志——iter-4 不重写此契约，仅在用户指南"已知限制"小节提及"窗口缩放事件流失效时 FR-09 验收不可达"。
8. **macOS 双架构**：PyInstaller `--target-arch universal2` 或分别在 Intel / Apple Silicon 构建机上分别构建；产物命名 `snake-gui-intel.app` / `snake-gui-arm64.app`（或合并为 `snake-gui.app` + `lipo` 合成）。**r2 修订**：lipo 合并以 arm64 完整 `.app` 为基础，仅替换其中 `Contents/MacOS/snake-gui` 二进制，不重建 bundle。
9. **PyInstaller 版本**：≥5.13（支持 Python 3.10+ 打包；>=5.0 已稳定支持 `--onefile --windowed`）。
10. **退出码语义**（G4-2 新增退出码 3）：
    - 0 = 正常退出（用户主动退出 / 游戏结束自然退出）
    - 1 = app 异常（ConfigError / 未捕获异常 / 数据损坏）
    - 2 = 图形环境不可用（Renderer.init 失败 / SDL 缺失 / pygame.error）
    - 3 = 用户数据目录不可写（HighScoreStore mkdir 失败 / disk full / 权限拒绝 / score_callback 内 save 失败）
11. **打包体积**：单文件打包预期 20-40MB（pygame SDL2 运行时占大头）；iter-4 不优化体积（架构未要求）。
12. **签名与公证**（**架构未要求，iter-4 不实施**）：Windows 代码签名 / macOS 苹果公证（notarization）—— 留给后续版本；用户在用户指南"已知限制"小节明确"未签名可能在 Windows SmartScreen / macOS Gatekeeper 触发警告，点击'仍要运行'即可"。
13. **r2 产物落盘位置**（P1-4 修订）：迭代 4 设计产物固定落 `workspace/snake-linux/design/game-app/`（与 modules.json `design.product = "snake-linux/design/game-app/"` 一致），git 跟踪；**禁止**再次误建 `zteam/snake-linux/` 顶层目录。

---

## 1. 数据结构

### 1.1 错误类型（**G4-2 新增退出码 3 + 错误子类扩展**）

```python
# errors.py — iter-3 沿用 + iter-4 扩展


class AppError(RuntimeError):
    """app 顶层错误基类。"""


class GraphicsUnavailableError(AppError):
    """Renderer.init() / pygame.display.set_mode 失败 → 退出码 2。"""

    # G4-2 新增字段：可读错误建议
    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion  # 人类可读的建议（如"请安装 SDL2 库"）


class StorageUnavailableError(AppError):
    """用户数据目录不可写（HighScoreStore mkdir/save 失败）→ 退出码 3（G4-2 新增）。

    iter-3 退出码为 1；iter-4 独立为 3，便于用户/脚本区分错误类型。
    注意：iter-3 既有 UT 若断言旧语义（"StorageUnavailableError → exit 1"），需要在
    修订清单中列出并同步修改。
    """

    # G4-2 新增字段
    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion


class ConfigError(AppError):
    """AppConfig / AppConfigV3 构造期校验失败 → 退出码 1（沿用）。"""


# G4-2 新增：HiDPI 警告（非致命）
class HighDPIWarning(UserWarning):
    """HiDPI 缩放失败警告 → 自动降级到非 SCALED 模式 → 不退出，仅 stderr warning。"""


# G4-2 新增：CJK 字体警告（非致命）
class CJKFontFallbackWarning(UserWarning):
    """CJK 字体回退链全失败 → 使用 SDL 默认字体 → 不退出，仅 stderr warning。"""


# G4-2 新增：平台版本不兼容提示（仅 stderr，无异常）
class PlatformUnsupportedWarning(UserWarning):
    """平台版本低于最低要求（macOS <12 / Windows <10） → stderr warning 但继续运行（尽力兼容）。"""
```

### 1.2 性能指标常量（**G4-3 新增**）

```python
# perf.py — G4-3 新增性能基准常量


# NFR-01
TARGET_FPS: int = 60
P95_FRAME_TIME_MS_MAX: float = 25.0  # P95 帧时间 ≤ 25ms
INPUT_LATENCY_TICKS_MAX: int = 1     # 输入延迟 ≤ 1 个节拍
# 各档位节拍上限（确保档位间可感知差异）
TICK_MS_HARD_MAX_RATIO: float = 0.5  # 困难档节拍 ≤ 简单档 50%

# NFR-02
MEMORY_PEAK_MB_MAX: int = 300  # 运行时内存 ≤ 300MB
CPU_IDLE_PERCENT_MAX: float = 10.0  # 空闲画面 CPU ≤ 10%（单核）

# 性能脚本基准时长
BENCH_DURATION_SECONDS: int = 60
BENCH_AI_DIRECTION_SWITCH_INTERVAL_S: float = 0.5  # 基准中每 0.5 秒切一次方向
```

### 1.3 路径定位常量（**G4-1/G4-5 新增，r2 修订：统一 fonts/ 子目录**）

```python
# _constants.py — iter-3 沿用 + iter-4 扩展（r2 修订）


# iter-4 G4-5 打包内置字体路径定位
BUNDLED_FONT_FILENAME: str = "SourceHanSansCN-Regular.otf"

# r2 修订：spec datas 目标目录与 _constants 查找子目录必须一致
BUNDLED_FONT_SUBDIR: str = "fonts"


def get_bundled_font_path() -> str:
    """查找打包内置字体路径（PyInstaller --onefile 临时目录 / 源码目录）。

    PyInstaller --onefile 模式下 sys._MEIPASS 指向临时解压目录；spec datas 目标为
    "fonts/" 子目录 → 文件位于 <_MEIPASS>/fonts/SourceHanSansCN-Regular.otf。
    源码模式 / --onedir 模式下文件位于 <game_app>/fonts/SourceHanSansCN-Regular.otf。

    r2 修订（P0-2）：spec datas 与本函数查找路径统一为 fonts/ 子目录，确保 FONT-1
    UT 第一优先级可达。否则内置字体机制形同虚设，永远走 match_font 回退链。

    全部失败返回空串（由 _load_cjk_font 走 match_font 回退链兜底）。
    """
    import os
    import sys

    # 1. PyInstaller --onefile 临时目录：<_MEIPASS>/fonts/<file>
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, BUNDLED_FONT_SUBDIR, BUNDLED_FONT_FILENAME)
        if os.path.isfile(candidate):
            return candidate

    # 2. 源码目录 / --onedir 模式：<game_app>/fonts/<file>
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, BUNDLED_FONT_SUBDIR, BUNDLED_FONT_FILENAME)
    if os.path.isfile(candidate):
        return candidate

    return ""
```

### 1.4 运行期状态（**G4-2 新增字段 + 沿用 iter-3**）

| 字段 | 类型 | 初始 | 说明 |
|------|------|------|------|
| `_last_error: Optional[AppError]` | class 内部 | `None` | G4-2 新增：最后一次捕获的 AppError，供 main() 退出前写 stderr |
| `_hidpi_degraded: bool` | class 内部 | `False` | G4-2 新增：HiDPI 缩放失败后降级标志 |
| `_cjk_font_fallback: bool` | class 内部 | `False` | G4-2 新增：CJK 字体回退到默认字体标志 |
| （其余字段） | 沿用 iter-3 | 沿用 | `_running` / `_skin_index` / `_prev_snap` / `_difficulty` / `_high_score` / `_tick_accumulator_ms` / `_menu_title_font` / `_menu_body_font` / `clock` / `screen` / `game_state` / `_renderer` / `_storage` / `config` |

### 1.5 不变量清单（FO 实现必须保证，UT 也要覆盖）

| ID | 不变量 |
|----|--------|
| INV-1 | `screen == PLAYING` 时 `game_state.status == GameStatus.RUN` |
| INV-2 | `screen == GAME_OVER` 时 `game_state.status == GameStatus.OVER` |
| INV-3 | 难度 `Difficulty` 选定后写入 `game_state.difficulty`，运行中无接口可改 |
| INV-4 | `_tick_accumulator_ms >= tick_ms` 时必调 `step()`，调后减 `tick_ms`（循环内逐拍重读 tick_ms） |
| INV-5 | 退出主循环后 `Renderer.shutdown()` 必被调 1 次（其内部 `pygame.quit()`），进程退出码 0；退出码 2/3 路径也尝试 1 次（幂等） |
| INV-6 | `_high_score` 类型 int |
| INV-7 | `screen == MENU` 时 `game_state is None` |
| INV-8 | `_prev_snap is None` 时 `_interpolation_state` 返 None（瞬移渲染，r2-1/r2-3 沿用） |
| INV-9 | `_renderer` 仅在 `_init_pygame()` 之后非 None |
| INV-10 | `screen == PAUSED` 时 `game_state.status == GameStatus.PAUSED`（iter-2 G2-1 沿用） |
| INV-11 | `screen` 切换仅发生在 `_dispatch_*` 显式赋值（无自动切屏，r3-7 沿用） |
| INV-12 | `_high_score` 与 `storage.load()` 一致（iter-2 G2-2 沿用） |
| INV-13 | `score_callback` 直接写 `_high_score` 实例字段（iter-2 G2-3 沿用） |
| INV-14 | 失焦仅在 PLAYING 态追加 UNFOCUS（iter-2 G2-4 沿用） |
| INV-15 | `_handle_resize` 抛 `RenderError` 时不退出游戏（iter-3 G3-2 沿用） |
| INV-16 | `_skin_index` 在 `[0, len(skin_names()))` 内循环（iter-3 G3-1 沿用） |
| **INV-17** | **G4-2 新增**：GraphicsUnavailableError 必映射退出码 2，StorageUnavailableError 必映射退出码 3；**r2 修订**（P0-3）：映射时精确类型优先于基类（GraphicsUnavailableError → 2 优先于 AppError → 1） |
| **INV-18** | **G4-2 新增**：HiDPI 降级后 `_hidpi_degraded == True`，HUD 不展示降级提示（用户无感，仅 stderr warning） |
| **INV-19** | **G4-2 新增**：CJK 字体回退后 `_cjk_font_fallback == True`，菜单/结束画面/HUD 仍可读（英文字符） |
| **INV-20** | **G4-5 新增**：打包内置字体优先级 = `sys._MEIPASS/fonts/<file>` > `<game_app>/fonts/<file>` > `pygame.font.match_font` 回退链 > `pygame.font.Font(None, size)`；**r2 修订**：第一优先级路径含 `fonts/` 子目录 |

---

## 2. 数据传递方式

### 2.1 模块边界与数据流（沿用 iter-3 + G4-1 打包构建流）

#### 2.1.1 运行期数据流（沿用 iter-3 §2.1）

```
                 ┌──────────────────────────────┐
   键盘事件 ───▶ │  InputMap: pygame.event →    │ ──▶ InputAction (Enum)
                 │       _map_event (单键)       │       (含 None: 未映射)
                 └──────────────────────────────┘
                            │
                            ▼
                 ┌──────────────────────────────┐
                 │ _drain_events (R3-1 屏态兜底) │
                 │   MENU 屏态兜底为 START       │
                 │   VIDEORESIZE 同步处理        │
                 │   SET_SKIN_* MENU 态处理      │
                 └──────────────────────────────┘
                            │
                            ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  主循环 (run())                                               │
   │   1. clock.tick_busy_loop(fps_cap) → dt_ms                  │
   │   2. _drain_events() → InputAction 流                       │
   │   3. if QUIT in actions: break                              │
   │   4. for a in actions: _dispatch(screen, a)                  │
   │   5. if screen==PLAYING: _tick(dt_ms) → step 节拍            │
   │   6. _render()                                              │
   │   7. pygame.display.flip()                                    │
   └─────────────────────────────────────────────────────────────┘
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
            game-core   gui-renderer  platform-storage
```

#### 2.1.2 构建期数据流（**G4-1 新增，r2 修订：三依赖包路径补全**）

```
源码: code/game-app/iter-3/game_app/
    ├── __main__.py            # PyInstaller 入口
    ├── app.py                 # 主装配
    ├── input.py               # 输入映射
    ├── menu.py                # 自绘菜单/结束画面
    ├── config.py              # AppConfig / AppConfigV3
    ├── fonts.py               # _load_cjk_font
    ├── storage.py             # create_storage 包装
    ├── errors.py              # AppError 子类
    ├── perf.py                # G4-3 性能常量
    └── fonts/                 # G4-5 内置字体（**r2 修订：与 spec datas 目标目录统一**）
        └── SourceHanSansCN-Regular.otf

三依赖包（**r2 修订：spec pathex 须包含**）：
    code/game-core/iter-2/          → game_core 包
    code/gui-renderer/iter-3/        → gui_renderer 包
    code/platform-storage/iter-2/    → platform_storage 包

                    │
                    ▼ PyInstaller --onefile --windowed --name snake-gui
                  spec/snake-gui.spec
                  scripts/build_linux.sh / build_windows.bat / build_macos.sh
                    │
                    ▼
                  dist/
                    ├── snake-gui             # Linux ELF
                    ├── snake-gui.exe         # Windows PE
                    ├── snake-gui.app         # macOS bundle（双架构）
                    ├── SHA256SUMS            # **r2 修订：仅 gen_sha256sums.sh 生成**
                    ├── RELEASE_NOTES.md
                    └── USER_GUIDE.md
```

### 2.2 模块间参数（沿用 iter-3 + G4-5 字体路径）

| 方向 | 路径 | 类型 |
|------|------|------|
| app → core | `_new_game(difficulty) -> None` | `GameState(width=20, height=15, difficulty=..., rng=Random())` |
| app → core | `game_state.set_direction(direction)` | `Direction` |
| app → core | `game_state.step()` / `game_state.snapshot()` / `game_state.toggle_pause()` / `game_state.set_score_callback(cb)` | 沿用 |
| app → renderer | `Renderer((W,H), *, skin, enable_high_dpi)` + `init/shutdown/render(snap, hud, *, interp)/set_skin/handle_resize/skin_names/current_skin_name/fps_metric` | 沿用 |
| app → storage | `create_storage() -> HighScoreStore` + `storage.load/save/reset` | 沿用 |
| **app → 字体文件**（**G4-5 新增**） | `pygame.font.Font(get_bundled_font_path(), size)` 或 `Font(None, size)` 兜底 | 路径定位走 `sys._MEIPASS/fonts/` 优先（**r2 修订**） |
| **app → stderr**（**G4-2 新增**） | `print(suggestion, file=sys.stderr)` 在 GraphicsUnavailableError / StorageUnavailableError / 警告触发时 | 可读建议 |

### 2.3 存储 / 共享状态

- **进程内单例**：app 状态全部活在 `App` 类实例字段。
- **进程间无共享**：无 IPC、无 socket、无文件锁。
- **磁盘写入**：仅 `HighScoreStore.save()` 写 `highscore.json`（用户数据目录，NFR-07）。
- **打包资源**：字体文件 `SourceHanSansCN-Regular.otf` 通过 PyInstaller `--add-data` 注入到 `<_MEIPASS>/fonts/`（**r2 修订**：与源码 `game_app/fonts/` 同名）；spec 文件声明。
- **构建脚本状态**：构建脚本输出到 `dist/`（gitignored）；**r2 修订**：构建脚本只产包，`SHA256SUMS` 由 `scripts/gen_sha256sums.sh` 统一生成；`RELEASE_NOTES` / `USER_GUIDE` 跟踪到 git。

---

## 3. 对外接口

### 3.1 `AppConfig` / `AppConfigV3`（沿用 iter-3）

```python
@dataclass(frozen=True)
class AppConfig:
    """运行期不可变常量。FR-09/NFR-01/NFR-02。"""
    window_w: int = 640
    window_h: int = 480
    fps_cap: int = 60
    min_window_w: int = 512
    min_window_h: int = 472

    def __post_init__(self) -> None:
        if self.fps_cap <= 0:
            raise ConfigError(f"fps_cap 必须 > 0，收到 {self.fps_cap}")
        if self.window_w < self.min_window_w or self.window_h < self.min_window_h:
            raise ConfigError(
                f"窗口尺寸 ({self.window_w}, {self.window_h}) 小于最小可玩 "
                f"({self.min_window_w}, {self.min_window_h})"
            )


@dataclass(frozen=True)
class AppConfigV3(AppConfig):
    """iter-3 扩展：enable_high_dpi (NFR-04 高分屏清晰)。"""
    enable_high_dpi: bool = True
```

### 3.2 `AppScreen`（Enum，沿用 iter-3）

```python
class AppScreen(Enum):
    MENU = "menu"
    PLAYING = "playing"
    PAUSED = "paused"
    GAME_OVER = "over"
```

### 3.3 `InputAction`（Enum，沿用 iter-3 = 18 个）

```python
class InputAction(Enum):
    QUIT = "quit"
    START = "start"
    MOVE_UP = "up"
    MOVE_DOWN = "down"
    MOVE_LEFT = "left"
    MOVE_RIGHT = "right"
    TOGGLE_PAUSE = "pause"
    RESTART = "restart"
    SELECT_EASY = "sel_easy"
    SELECT_MEDIUM = "sel_med"
    SELECT_HARD = "sel_hard"
    RESET_HIGHSCORE = "reset_hs"
    BACK_TO_MENU = "back"
    ESCAPE = "escape"
    UNFOCUS = "unfocus"
    SET_SKIN_PREV = "skin_prev"     # iter-3 G3-1
    SET_SKIN_NEXT = "skin_next"     # iter-3 G3-1
    RESIZE = "resize"               # iter-3 G3-2
```

### 3.4 `App` 主类（**G4-2 新增错误处理器 + G4-5 字体路径注入**）

```python
class App:
    """snake-gui 顶层装配；PyInstaller 入口。

    iter-4 增量（G4-1/2/3/5）：
    - 退出码 0/1/2/3 区分（INV-17）：GraphicsUnavailableError → 2；StorageUnavailableError → 3
    - 可读错误提示 stderr 写入（INV-17/18/19）：GraphicsUnavailableError / StorageUnavailableError / HighDPIWarning / CJKFontFallbackWarning / PlatformUnsupportedWarning 各自带 suggestion
    - HiDPI 自动降级（G4-2，NFR-04）：init 失败时设 _hidpi_degraded=True，不退出
    - CJK 字体打包内置文件优先（G4-5）：get_bundled_font_path() 走 sys._MEIPASS/fonts/ → __file__/fonts/ → match_font 兜底（**r2 修订**）
    - 性能 profile 集成（G4-3）：scripts/bench_fps.py 直接调 _init_pygame/_new_game/_tick/_render（**r2 修订**：删除 _on_bench_complete 钩子声明，见 P2-4）

    沿用 iter-3（G3-1/2/3/4/5 全量沿用）：
    - _skin_index / _prev_snap 字段
    - AppConfigV3 子类支持 + enable_high_dpi 判定
    - _drain_events 同步处理 VIDEORESIZE / SET_SKIN_*
    - _render PLAYING 走 interp
    - _tick step 前维护 _prev_snap
    - _new_game 重置 _prev_snap = None
    - _interpolation_state 真实 Chebyshev 距离防御

    沿用 iter-2/1：None→START 屏态兜底 / menu 用 get_surface / _tick 循环内重读 / CJK 字体回退链 / 退出码 1/2 兜底
    """

    def __init__(self, config: AppConfig = AppConfig()) -> None:
        self.config = config
        self.screen: AppScreen = AppScreen.MENU
        self._difficulty: Difficulty = Difficulty.MEDIUM
        self.game_state: Optional[GameState] = None
        self._renderer: Optional[Renderer] = None
        self._storage: Optional[Any] = None
        self._high_score: int = 0
        self._tick_accumulator_ms: int = 0
        self._running: bool = True
        # ---- iter-3 增量（G3-1/G3-3）----
        self._skin_index: int = 0
        self._prev_snap: Optional[Snapshot] = None
        # ---- iter-4 增量（G4-2）----
        self._last_error: Optional[AppError] = None
        self._hidpi_degraded: bool = False
        self._cjk_font_fallback: bool = False
        # ---- 字体 / 时钟（沿用）----
        self._menu_title_font: Optional[pygame.font.Font] = None
        self._menu_body_font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None

    # ---- 公开入口 ----
    def run(self) -> int:
        """主循环。返回进程退出码：
           0 正常 / 1 app 异常 / 2 图形环境不可用 / 3 用户数据目录不可写（INV-17）。
        """
        ...

    # ---- 内部接口 ----
    def _init_pygame(self) -> None:
        """构造 renderer + HighScoreStore；CJK 字体回退链；HiDPI 降级；G4-5 打包字体优先。"""
        ...

    def _load_cjk_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        """G4-5 修订（r2）：优先打包内置字体（fonts/ 子目录） → match_font 回退链 → Font(None) 兜底。
           返回的 Font 对象记录到 _cjk_font_fallback（INV-19）。
        """
        ...
```

### 3.5 公开 API 列表

| 名称 | 类型 | 用途 |
|------|------|------|
| `AppConfig` | dataclass(frozen) + `__post_init__` | 运行期常量 |
| `AppConfigV3` | dataclass(frozen), iter-3 G3-4 | 扩展 enable_high_dpi |
| `AppScreen` | Enum（4 态） | app 界面状态机 |
| `InputAction` | Enum（18 个，iter-3） | 输入归一化 |
| `App` | class | 主装配类 |
| `main()` | function | 入口函数：`App().run()`，捕获所有 AppError + Warning，统一映射退出码 |
| `AppError` 子类 | 异常类 | iter-4 新增 StorageUnavailableError 退出码 3 + GraphicsUnavailableError.suggestion 字段 |
| `HighDPIWarning` / `CJKFontFallbackWarning` / `PlatformUnsupportedWarning` | UserWarning 子类 | iter-4 新增非致命警告 |
| `HudData` | 来自 gui_renderer | HUD 5 字段 dataclass |
| **`perf` 常量** | **module `perf.py`** | **iter-4 G4-3 新增**：TARGET_FPS / P95_FRAME_TIME_MS_MAX / MEMORY_PEAK_MB_MAX / BENCH_DURATION_SECONDS |
| **`get_bundled_font_path()`** | **function `_constants.py`** | **iter-4 G4-5 新增（r2 修订）**：定位打包内置字体（统一 `fonts/` 子目录） |
| **`scripts/build_*.{sh,bat}`** | **构建脚本** | **iter-4 G4-1 新增**：三平台 PyInstaller 构建；**r2 修订**：构建脚本只产包，不生成 SHA256SUMS |
| **`spec/snake-gui.spec`** | **PyInstaller spec** | **iter-4 G4-1 新增（r2 修订）**：打包配置（entry / datas / hiddenimports / **pathex 含三依赖包**） |
| **`scripts/bench_fps.py`** | **性能脚本** | **iter-4 G4-3 新增（r2 修订）**：sys.path 含三依赖包；经 `game_app.perf` re-export 导入性能常量；NFR-01 帧率实测 |
| **`scripts/bench_memory.py`** | **性能脚本** | **iter-4 G4-3 新增（r2 修订）**：sys.path 含三依赖包；经 `game_app.perf` re-export 导入性能常量；NFR-02 内存实测 |
| **`scripts/gen_sha256sums.sh`** | **校验和脚本** | **iter-4 G4-1 新增（r2 修订）**：统一汇总三平台包 SHA256SUMS |
| **`snake-linux/release/USER_GUIDE.md`** | **文档** | **iter-4 G4-4 新增**：五节齐全用户指南；**r2 修订**：下载链接标注"发布时替换" |
| **`snake-linux/release/RELEASE_NOTES.md`** | **文档** | **iter-4 G4-6 新增**：v2.0.0 changelog；**r2 修订**：下载链接标注"发布时替换" |
| **`snake-linux/release/SHA256SUMS`** | **文件** | **iter-4 G4-1 新增（r2 修订）**：由 `gen_sha256sums.sh` 生成 |

### 3.6 异常（iter-4 G4-2 扩展）

```python
# errors.py — iter-3 沿用 + iter-4 扩展


class AppError(RuntimeError):
    """app 顶层错误基类。"""


class GraphicsUnavailableError(AppError):
    """Renderer.init() 失败 → 退出码 2。iter-4 新增 suggestion 字段。"""
    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion


class StorageUnavailableError(AppError):
    """用户数据目录不可写 → 退出码 3（iter-4 新增退出码）。

    iter-3 退出码为 1；iter-4 独立为 3 便于区分错误类型。
    **r2 修订（P2-6）**：iter-3 既有 UT 中若断言 StorageUnavailableError → exit 1，
    必须修订为 exit 3；FO 修订清单见 §6.7。
    """
    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion


class ConfigError(AppError):
    """AppConfig 校验失败 → 退出码 1。"""


class HighDPIWarning(UserWarning):
    """HiDPI 降级警告（非致命）。"""


class CJKFontFallbackWarning(UserWarning):
    """CJK 字体回退警告（非致命）。"""


class PlatformUnsupportedWarning(UserWarning):
    """平台版本警告（非致命）。"""
```

### 3.7 `errors.py` → 退出码映射（**G4-2 新增，r2 修订 P0-3：精确子类优先**）

```python
# errors.py 新增 error_to_exit_code 函数


# r2 修订（P0-3）：精确子类（GraphicsUnavailableError / StorageUnavailableError）
# 必须排在基类 AppError 之前；isinstance 按插入顺序遍历，先命中精确子类。
_EXIT_CODE_MAP = {
    ConfigError: 1,                          # 叶子：ConfigError
    GraphicsUnavailableError: 2,             # 精确子类 → 2 优先于 AppError → 1
    StorageUnavailableError: 3,              # 精确子类 → 3 优先于 AppError → 1
    AppError: 1,                             # 基类兜底
}


def error_to_exit_code(error: BaseException) -> int:
    """G4-2 新增（r2 修订）：根据异常类型映射退出码。

    r2 修订（P0-3）：按 dict 插入顺序遍历 _EXIT_CODE_MAP，精确类型优先于基类。
    - GraphicsUnavailableError（AppError 子类）→ 命中第 2 项 → 返回 2
    - StorageUnavailableError（AppError 子类）→ 命中第 3 项 → 返回 3
    - ConfigError（AppError 子类）→ 命中第 1 项 → 返回 1
    - 其他 AppError 子类 → 命中第 4 项 → 返回 1

    退出码 3 是 iter-4 新增，专用于用户数据目录不可写。

    注：也可改用 `type(error) in map` 精确匹配 + isinstance 兜底，本设计采用
    dict 顺序方案（与 Python 3.7+ dict 保序一致，FO 落地简单）。
    """
    for exc_type, code in _EXIT_CODE_MAP.items():
        if isinstance(error, exc_type):
            return code
    return 1
```

**r2 修订推演（P0-3）**：

```python
# ERR-5 UT 断言与实现一致性
assert error_to_exit_code(GraphicsUnavailableError("x")) == 2  # 命中第 2 项（精确子类优先）
assert error_to_exit_code(StorageUnavailableError("x")) == 3   # 命中第 3 项（精确子类优先）
assert error_to_exit_code(ConfigError("x")) == 1               # 命中第 1 项
assert error_to_exit_code(AppError("x")) == 1                 # 命中第 4 项（基类兜底）
```

---

## 4. 实现细节/步骤

### 4.1 模块文件组织（**G4-1/G4-3/G4-5 新增**）

```
snake-linux/
├── code/game-app/iter-3/                       # 沿用 iter-3 代码目录（同 v2.0.0 一个发布单元）
│   └── game_app/
│       ├── __init__.py                          # 沿用 iter-3
│       ├── __main__.py                          # 沿用 iter-3（PyInstaller 入口）
│       ├── app.py                               # 沿用 iter-3 + G4-2 错误处理
│       ├── input.py                             # 沿用 iter-3
│       ├── menu.py                              # 沿用 iter-3
│       ├── config.py                            # 沿用 iter-3
│       ├── fonts.py                             # iter-4 G4-5 修订：内置字体优先
│       ├── storage.py                           # 沿用 iter-3
│       ├── errors.py                            # iter-4 G4-2 扩展：退出码 3 + 警告类（r2 修订：精确子类优先映射）
│       ├── perf.py                              # iter-4 G4-3 新增：性能常量
│       ├── _constants.py                        # iter-4 G4-5 新增：get_bundled_font_path（r2 修订：fonts/ 子目录）
│       └── fonts/                                # iter-4 G4-5 新增：打包内置字体目录
│           └── SourceHanSansCN-Regular.otf       # OFL 协议开源中文字体
├── code/game-core/iter-2/                       # 沿用 iter-2（PyInstaller pathex，**r2 修订 P0-1**）
├── code/gui-renderer/iter-3/                    # 沿用 iter-3（PyInstaller pathex，**r2 修订 P0-1**）
├── code/platform-storage/iter-2/                # 沿用 iter-2（PyInstaller pathex，**r2 修订 P0-1**）
├── scripts/                                     # iter-4 G4-1/G4-3 新增
│   ├── build_linux.sh                           # Linux ELF 构建脚本（**r2 修订 P2-2**：不生成 SHA256SUMS）
│   ├── build_windows.bat                        # Windows .exe 构建脚本（**r2 修订 P2-1/2-2**：不生成 SHA256SUMS）
│   ├── build_macos.sh                           # macOS .app 构建脚本（**r2 修订 P1-3/P2-2**：lipo 替换二进制；不生成 SHA256SUMS）
│   ├── bench_fps.py                             # G4-3 NFR-01 帧率实测（**r2 修订 P0-4**：sys.path 完整 + game_app.perf）
│   ├── bench_memory.py                          # G4-3 NFR-02 内存实测（**r2 修订 P0-4**：sys.path 完整 + game_app.perf）
│   └── gen_sha256sums.sh                        # G4-1 三平台包校验和生成（**r2 修订 P2-2**：统一生成入口）
├── spec/                                        # iter-4 G4-1 新增
│   └── snake-gui.spec                           # PyInstaller 配置文件（**r2 修订 P0-1**：pathex 含三依赖包）
└── release/                                     # iter-4 G4-1/G4-4/G4-6 新增
    ├── USER_GUIDE.md                            # G4-4 用户指南（**r2 修订 P2-3**：下载链接标注）
    ├── RELEASE_NOTES.md                         # G4-6 发布说明（**r2 修订 P2-3**：下载链接标注）
    └── SHA256SUMS                                # G4-1 校验和（由 gen_sha256sums.sh 生成）
```

### 4.2 主循环骨架（沿用 iter-3 + G4-2 错误捕获扩展 + r2 修订 P1-1 主循环退出码一致性）

```python
def run(self) -> int:
    """主循环。返回进程退出码（0/1/2/3）。

    iter-4 G4-2 增量：
    - GraphicsUnavailableError → stderr suggestion + 退出码 2
    - StorageUnavailableError → stderr suggestion + 退出码 3
    - HighDPIWarning → stderr warning，不退出
    - CJKFontFallbackWarning → stderr warning，不退出
    - PlatformUnsupportedWarning → stderr warning，不退出
    - finally 块：renderer.shutdown() 兜底（INV-5 沿用）

    r2 修订（P1-1）：主循环 _tick / score_callback / _dispatch_menu 路径下
    StorageUnavailableError 也必须映射退出码 3，与 §5.6 错误矩阵一致。
    """
    try:
        self._init_pygame()
    except GraphicsUnavailableError as e:
        if e.suggestion:
            print(f"\n[snake-gui] 图形环境不可用: {e}\n建议: {e.suggestion}\n", file=sys.stderr)
        else:
            print(f"\n[snake-gui] 图形环境不可用: {e}\n", file=sys.stderr)
        return 2  # 退出码 2
    except StorageUnavailableError as e:
        if e.suggestion:
            print(f"\n[snake-gui] 用户数据目录不可写: {e}\n建议: {e.suggestion}\n", file=sys.stderr)
        else:
            print(f"\n[snake-gui] 用户数据目录不可写: {e}\n", file=sys.stderr)
        return 3  # 退出码 3（iter-4 新增）
    except ConfigError as e:
        print(f"\n[snake-gui] 配置错误: {e}\n", file=sys.stderr)
        return 1
    except AppError as e:
        print(f"\n[snake-gui] app 异常: {e}\n", file=sys.stderr)
        return 1

    # iter-2 G2-4 沿用：窗口失焦自动暂停（INV-14）
    # r2 修订（P1-1）：StorageUnavailableError 必须在 AppError 之前捕获，确保退出码 3
    try:
        while self._running:
            self._run_loop_iteration()
    except StorageUnavailableError as e:           # r2 修订：精确类型优先于 AppError
        self._last_error = e
        if e.suggestion:
            print(f"\n[snake-gui] 用户数据目录不可写: {e}\n建议: {e.suggestion}\n", file=sys.stderr)
        else:
            print(f"\n[snake-gui] 用户数据目录不可写: {e}\n", file=sys.stderr)
        return 3
    except AppError as e:
        self._last_error = e
        print(f"\n[snake-gui] app 异常: {e}\n", file=sys.stderr)
        return 1
    finally:
        # INV-5 兜底：所有退出路径都尝试 shutdown
        if self._renderer is not None:
            try:
                self._renderer.shutdown()
            except Exception:
                pass  # 幂等

    return 0  # 正常退出
```

### 4.3 输入映射（沿用 iter-3）

（不修订，参见 iter-3 设计 §4.3）

### 4.4 状态机 dispatch 表（沿用 iter-3）

（不修订，参见 iter-3 设计 §4.4）

### 4.5 节拍推进（沿用 iter-3）

（不修订，参见 iter-3 设计 §4.5）

### 4.6 渲染分发（沿用 iter-3）

（不修订，参见 iter-3 设计 §4.6）

### 4.7 初始化（**G4-2 HiDPI 降级 + G4-5 字体路径 + G4-2 StorageUnavailableError 退出码 3，r2 修订 P1-2 Windows 版本字段**）

```python
def _init_pygame(self) -> None:
    """构造 renderer + HighScoreStore；CJK 字体回退链；HiDPI 降级。

    iter-4 G4-2 增量：
    - HiDPI 降级：try SCALED 标志，失败 → 降级到非 SCALED + stderr warning + _hidpi_degraded=True
    - 平台版本检查：macOS <12 / Windows <10 → stderr warning 但继续（尽力兼容）
    - StorageUnavailableError 退出码 3（区分于一般 AppError 退出码 1）

    iter-4 G4-5 增量：
    - _load_cjk_font 优先打包内置字体文件
    """
    # 平台版本检查（G4-2 新增，非致命）
    _check_platform_version()

    # iter-3 G3-4 沿用：构造 Renderer（enable_high_dpi 判定）
    enable_high_dpi = True
    if isinstance(self.config, AppConfigV3):
        enable_high_dpi = self.config.enable_high_dpi

    self._renderer = _create_renderer_with_hidpi_fallback(
        window_size=(self.config.window_w, self.config.window_h),
        skin=DEFAULT_SKIN,
        enable_high_dpi=enable_high_dpi,
    )

    # iter-2 G2-2 沿用：HighScoreStore 接入
    try:
        if self._storage is None:
            self._storage = create_storage()
            self._high_score = self._storage.load()
    except (StorageError, OSError) as e:
        # G4-2 修订：抛出 StorageUnavailableError（退出码 3 而非 1）
        raise StorageUnavailableError(
            f"用户数据目录不可写: {e}",
            suggestion="请检查 ~/.local/share (Linux) / ~/Library/Application Support (macOS) / %APPDATA% (Windows) 目录权限；或清理磁盘空间",
        ) from e

    # iter-4 G4-5 修订：CJK 字体回退链（优先打包内置文件）
    self._menu_title_font = _load_cjk_font(48, bold=True)
    self._menu_body_font = _load_cjk_font(22)

    self.clock = pygame.time.Clock()


def _create_renderer_with_hidpi_fallback(
    window_size: tuple,
    *,
    skin: Skin,
    enable_high_dpi: bool,
) -> Renderer:
    """G4-2 新增：HiDPI 降级包装。try enable_high_dpi=True → 失败降级到 False。"""
    try:
        renderer = Renderer(window_size, skin=skin, enable_high_dpi=enable_high_dpi)
        renderer.init()
        return renderer
    except (RenderError, pygame.error) as e:
        if enable_high_dpi:
            # 降级到非 HiDPI（stderr warning）
            warnings.warn(
                f"HiDPI 缩放失败，降级到非 SCALED 模式: {e}",
                HighDPIWarning,
                stacklevel=2,
            )
            try:
                renderer = Renderer(window_size, skin=skin, enable_high_dpi=False)
                renderer.init()
                return renderer
            except (RenderError, pygame.error) as e2:
                # 降级也失败 → GraphicsUnavailableError（退出码 2）
                raise GraphicsUnavailableError(
                    f"图形环境初始化失败: {e2}",
                    suggestion="请检查：1. 显示器已连接；2. SDL2 库已安装（Linux: apt install libsdl2-dev）；3. 显卡驱动版本正常",
                ) from e2
        else:
            raise GraphicsUnavailableError(
                f"图形环境初始化失败: {e}",
                suggestion="请检查：1. 显示器已连接；2. SDL2 库已安装（Linux: apt install libsdl2-dev）；3. 显卡驱动版本正常",
            ) from e


def _check_platform_version() -> None:
    """G4-2 新增：平台版本检查（非致命）。

    r2 修订（P1-2）：Windows 版本取 platform.win32_ver()[0]（NT 版本号 "10"/"11"）
    而非 [1]（hostname）；macOS 沿用 platform.mac_ver()[0]。
    """
    import platform
    import sys

    system = platform.system()
    if system == "Darwin":
        # macOS 版本号：12 = Monterey, 11 = Big Sur
        mac_ver = platform.mac_ver()[0]
        try:
            major = int(mac_ver.split(".")[0])
            if major < 12:
                warnings.warn(
                    f"macOS {mac_ver} 低于最低要求 12.0，可能存在兼容性问题",
                    PlatformUnsupportedWarning,
                    stacklevel=2,
                )
        except (ValueError, IndexError):
            pass
    elif system == "Windows":
        # r2 修订（P1-2）：取 [0] 版本号字段（"10" / "11"）而非 [1] hostname
        win_ver = platform.win32_ver()[0]
        if not win_ver:
            # 兜底：取 platform.release()（如 "10"/"11"）
            win_ver = platform.release()
        try:
            major = int(win_ver.split(".")[0])
            if major < 10:
                warnings.warn(
                    f"Windows {win_ver} 低于最低要求 10，可能存在兼容性问题",
                    PlatformUnsupportedWarning,
                    stacklevel=2,
                )
        except (ValueError, IndexError):
            pass
```

### 4.8 字体加载（**G4-5 修订：内置字体优先**）

```python
# fonts.py — iter-4 G4-5 修订


def _load_cjk_font(size: int, bold: bool = False) -> pygame.font.Font:
    """加载支持 CJK 字符的字体。

    iter-4 G4-5 优先级（INV-20，**r2 修订**：路径含 fonts/ 子目录）：
    1. 打包内置字体文件（SourceHanSansCN-Regular.otf）—— 位于
       <_MEIPASS>/fonts/<file> 或 <game_app>/fonts/<file>（与 spec datas 目标一致）
    2. pygame.font.match_font 回退链（"notosanscjksc", "notosanscjk", "wenquanyizenhei", ...）
    3. pygame.font.Font(None, size) —— SDL 默认字体（仅 ASCII）

    返回值：pygame.font.Font 实例。
    副作用：通过 _cjk_font_fallback 标志记录是否回退（INV-19，stderr warning）。
    """
    import warnings

    # 1. 打包内置字体（优先）—— r2 修订：路径由 get_bundled_font_path() 统一返回
    bundled_path = get_bundled_font_path()
    if bundled_path:
        try:
            font = pygame.font.Font(bundled_path, size)
            font.set_bold(bold)
            return font
        except pygame.error as e:
            warnings.warn(
                f"打包内置字体加载失败 ({bundled_path}): {e}",
                CJKFontFallbackWarning,
                stacklevel=2,
            )

    # 2. match_font 回退链
    fallback_chain = [
        "notosanscjksc",
        "notosanscjk",
        "wenquanyizenhei",
        "wenquanyimicrohei",
        "arialunicodems",
    ]
    for name in fallback_chain:
        try:
            path = pygame.font.match_font(name, bold=bold)
            if path:
                font = pygame.font.Font(path, size)
                font.set_bold(bold)
                return font
        except pygame.error:
            continue

    # 3. SDL 默认字体兜底（仅 ASCII，CJK 字符显示为方框/乱码）
    warnings.warn(
        "CJK 字体回退链全失败，使用 SDL 默认字体（中文显示为方框）",
        CJKFontFallbackWarning,
        stacklevel=2,
    )
    return pygame.font.Font(None, size)
```

### 4.9 PyInstaller spec 文件（**G4-1 新增，r2 修订 P0-1：pathex 含三依赖包**）

```python
# spec/snake-gui.spec — PyInstaller 配置


# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for snake-gui v2.0.0.

使用方法：
  cd snake-linux/
  pyinstaller --clean spec/snake-gui.spec

或在 scripts/build_*.{sh,bat} 中调用：
  pyinstaller --clean --noconfirm spec/snake-gui.spec
"""

import os
from PyInstaller.utils.hooks import collect_submodules

# 项目根目录（spec 文件位于 snake-linux/spec/）
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
GAME_APP_DIR = os.path.join(PROJECT_ROOT, "code", "game-app", "iter-3", "game_app")

# r2 修订（P0-1）：三依赖包路径必须加入 pathex，
# 否则 collect_submodules 对未安装且不在 pathex 的包返回空 → 产物 ImportError。
GAME_CORE_DIR = os.path.join(PROJECT_ROOT, "code", "game-core", "iter-2")
GUI_RENDERER_DIR = os.path.join(PROJECT_ROOT, "code", "gui-renderer", "iter-3")
PLATFORM_STORAGE_DIR = os.path.join(PROJECT_ROOT, "code", "platform-storage", "iter-2")


block_cipher = None

# iter-4 G4-5：打包内置字体文件（**r2 修订**：目标子目录 fonts/ 与 _constants.get_bundled_font_path 一致）
datas = [
    (os.path.join(GAME_APP_DIR, "fonts", "SourceHanSansCN-Regular.otf"), "fonts"),
]

# iter-4 G4-1：全量收集子模块（game_app + platform_storage + gui_renderer）
# 注：pathex 含三依赖包源码目录后，collect_submodules 才能找到子模块。
hiddenimports = []
hiddenimports.extend(collect_submodules("game_app"))
hiddenimports.extend(collect_submodules("platform_storage"))
hiddenimports.extend(collect_submodules("gui_renderer"))


a = Analysis(
    [os.path.join(GAME_APP_DIR, "__main__.py")],
    # r2 修订（P0-1）：pathex 必须含三依赖包路径
    pathex=[
        GAME_APP_DIR,
        GAME_CORE_DIR,
        GUI_RENDERER_DIR,
        PLATFORM_STORAGE_DIR,
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",  # 移除不需要的 tkinter
        "unittest",  # 移除测试模块
        "pydoc",  # 移除文档模块
        "doctest",  # 移除 doctest
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="snake-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 禁用 UPX 压缩（避免杀毒软件误报）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --windowed：无控制台窗口（Windows / macOS）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # macOS 由 --target-arch 参数决定
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可选：添加 .ico 文件路径
)
```

### 4.10 构建脚本（**G4-1 新增，r2 修订 P1-3 / P2-1 / P2-2**）

#### 4.10.1 `scripts/build_linux.sh`

```bash
#!/usr/bin/env bash
# scripts/build_linux.sh — Linux ELF 构建脚本
# 用途：在 Linux 构建机上产出 dist/snake-gui（单文件可执行）
# 前置：Python 3.8+ / pip install pyinstaller==5.13+
# r2 修订（P2-2）：仅产包，不生成 SHA256SUMS（由 gen_sha256sums.sh 统一生成）

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 清理
rm -rf build dist

# 构建
pyinstaller --clean --noconfirm spec/snake-gui.spec

# 重命名产物
mv dist/snake-gui dist/snake-gui-linux-x86_64

# chmod +x
chmod +x dist/snake-gui-linux-x86_64

# r2 修订（P2-2）：不写 SHA256SUMS；发布时由 gen_sha256sums.sh 统一生成

echo "[build_linux] 完成: dist/snake-gui-linux-x86_64"
```

#### 4.10.2 `scripts/build_windows.bat`

```batch
@echo off
REM scripts/build_windows.bat — Windows .exe 构建脚本
REM 用途：在 Windows 构建机上产出 dist\snake-gui.exe
REM 前置：Python 3.8+ / pip install pyinstaller==5.13+
REM r2 修订（P2-1）：不生成 SHA256SUMS（certutil 输出格式与 §6.3 SHA-1 断言不符，
REM 且 SHA-1 断言放宽为"含 64-hex 即过"，本脚本只产包）
REM r2 修订（P2-2）：SHA256SUMS 由 gen_sha256sums.sh 统一生成

setlocal

cd /d "%~dp0\.."

REM 清理
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 构建
pyinstaller --clean --noconfirm spec\snake-gui.spec

REM 重命名产物
rename dist\snake-gui.exe snake-gui-windows-x86_64.exe

echo [build_windows] 完成: dist\snake-gui-windows-x86_64.exe
endlocal
```

#### 4.10.3 `scripts/build_macos.sh`

```bash
#!/usr/bin/env bash
# scripts/build_macos.sh — macOS .app 构建脚本
# 用途：在 macOS 构建机上产出 dist/snake-gui.app（双架构）
# 前置：macOS 12+ / Python 3.8+ / pip install pyinstaller==5.13+
# r2 修订（P1-3）：lipo 合并以 arm64 完整 .app 为基础，仅替换 Contents/MacOS/snake-gui 二进制，
# 不重建 bundle 结构（避免丢失 Info.plist/资源/框架）。
# r2 修订（P2-2）：不生成 SHA256SUMS，由 gen_sha256sums.sh 统一生成。

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 清理
rm -rf build dist

# 构建 Intel 版本（保留完整 .app bundle）
pyinstaller --clean --noconfirm --target-arch x86_64 spec/snake-gui.spec
mv dist/snake-gui.app dist/snake-gui-intel.app

# 构建 Apple Silicon 版本（保留完整 .app bundle，作为最终 .app 基础）
pyinstaller --clean --noconfirm --target-arch arm64 spec/snake-gui.spec
mv dist/snake-gui.app dist/snake-gui-arm64.app

# 合并双架构为 universal2（可选，需安装 lipo）
# r2 修订（P1-3）：以 arm64 完整 .app 为基础，仅替换 Contents/MacOS/snake-gui 二进制
if command -v lipo &> /dev/null; then
    echo "[build_macos] 合并 universal2..."
    cp -R dist/snake-gui-arm64.app dist/snake-gui.app
    lipo -create \
        -output dist/snake-gui.app/Contents/MacOS/snake-gui \
        dist/snake-gui-intel.app/Contents/MacOS/snake-gui \
        dist/snake-gui-arm64.app/Contents/MacOS/snake-gui
    rm -rf dist/snake-gui-intel.app dist/snake-gui-arm64.app
    # r2 修订（P1-3）：BUILD-3 冒烟增加"产物为可启动 .app"断言——结构完整即可
fi

echo "[build_macos] 完成: dist/snake-gui.app"
```

#### 4.10.4 `scripts/gen_sha256sums.sh`

```bash
#!/usr/bin/env bash
# scripts/gen_sha256sums.sh — 生成三平台包 SHA256SUMS
# 用途：发布前统一生成校验和
# 前置：dist/snake-gui{,-linux,-windows,-macos} 已生成（三平台构建机各自产包后汇总）
# r2 修订（P2-2）：三平台构建脚本不再各自生成 SHA256SUMS，统一由此脚本生成

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

{
    if [ -f dist/snake-gui-linux-x86_64 ]; then
        sha256sum dist/snake-gui-linux-x86_64
    fi
    if [ -f dist/snake-gui-windows-x86_64.exe ]; then
        sha256sum dist/snake-gui-windows-x86_64.exe
    fi
    if [ -d dist/snake-gui.app ]; then
        find dist/snake-gui.app -type f -exec sha256sum {} \;
    fi
} > dist/SHA256SUMS

echo "[gen_sha256sums] SHA256SUMS 已生成"
cat dist/SHA256SUMS
```

### 4.11 性能 profile 脚本（**G4-3 新增，r2 修订 P0-4：sys.path 完整 + game_app.perf 导入**）

#### 4.11.1 `scripts/bench_fps.py`

```python
#!/usr/bin/env python3
"""scripts/bench_fps.py — NFR-01 帧率实测脚本。

用法：
  python3 scripts/bench_fps.py [--duration 60] [--difficulty hard]

输出：
  - 平均 FPS
  - P50 / P95 / P99 帧时间
  - 输入延迟（按键到 step 间隔）
  - 评估：NFR-01 PASS / FAIL

r2 修订（P0-4）：
- sys.path 补全 game-core/gui-renderer/platform-storage 三依赖包 + iter-3 代码目录
- 经 game_app re-export 导入性能常量（game_app.perf）或直接 from game_app.perf
- 删除 _on_bench_complete 钩子声明（P2-4），脚本直接调 _init_pygame/_new_game/_tick/_render
"""
import sys
import os
import time
import argparse
from collections import deque
from typing import List

# r2 修订（P0-4）：添加项目根目录到 sys.path，便于依赖包导入
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "game-core", "iter-2"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "gui-renderer", "iter-3"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "platform-storage", "iter-2"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "game-app", "iter-3"))

# r2 修订（P0-4）：经 game_app 顶层 re-export 导入性能常量
from game_app import App, AppConfigV3  # noqa
from game_app.perf import (  # noqa  —— r2 修订：from game_app.perf 而非 from perf
    TARGET_FPS,
    P95_FRAME_TIME_MS_MAX,
    BENCH_DURATION_SECONDS,
)
from game_core import Difficulty, Direction  # noqa  —— r2 修订：合并到顶部 import


def run_benchmark(duration: int, difficulty: Difficulty) -> dict:
    """运行 NFR-01 帧率基准测试。

    Returns:
        dict: {
            "avg_fps": float,
            "p50_frame_ms": float,
            "p95_frame_ms": float,
            "p99_frame_ms": float,
            "input_latency_ms": float,
            "duration_s": int,
            "result": "PASS" | "FAIL",
        }
    """
    # 实例化 App
    config = AppConfigV3(enable_high_dpi=True)
    app = App(config)

    # r2 修订（P2-4）：删除 _on_bench_complete 钩子调用，直接 _init_pygame
    app._init_pygame()
    app._difficulty = difficulty
    app._new_game(difficulty)

    # 帧时间采集
    frame_times: deque = deque(maxlen=10000)
    input_latencies: deque = deque(maxlen=1000)

    start_time = time.perf_counter()
    last_frame_time = start_time
    direction_cycle = 0

    direction_map = {
        "up": Direction.UP,
        "down": Direction.DOWN,
        "left": Direction.LEFT,
        "right": Direction.RIGHT,
    }

    while time.perf_counter() - start_time < duration:
        # 模拟按键（每 0.5 秒切一次方向）
        if time.perf_counter() - start_time > direction_cycle * 0.5:
            direction_cycle += 1
            direction = ["up", "down", "left", "right"][direction_cycle % 4]
            input_time = time.perf_counter()
            # 调 set_direction
            app.game_state = app.game_state.set_direction(direction_map[direction])
            input_latency = (time.perf_counter() - input_time) * 1000
            input_latencies.append(input_latency)

        # 模拟主循环
        dt_ms = (time.perf_counter() - last_frame_time) * 1000
        last_frame_time = time.perf_counter()

        app._tick(int(dt_ms))
        snap = app.game_state.snapshot()
        app._render()

        frame_times.append(dt_ms)

    # 统计
    sorted_frames = sorted(frame_times)
    n = len(sorted_frames)
    avg_fps = 1000.0 / (sum(frame_times) / n) if n > 0 else 0.0
    p50 = sorted_frames[n // 2]
    p95 = sorted_frames[int(n * 0.95)]
    p99 = sorted_frames[int(n * 0.99)]
    avg_latency = sum(input_latencies) / len(input_latencies) if input_latencies else 0.0

    result = "PASS" if p95 <= P95_FRAME_TIME_MS_MAX and avg_fps >= TARGET_FPS else "FAIL"

    return {
        "avg_fps": avg_fps,
        "p50_frame_ms": p50,
        "p95_frame_ms": p95,
        "p99_frame_ms": p99,
        "input_latency_ms": avg_latency,
        "duration_s": duration,
        "result": result,
    }


def main():
    parser = argparse.ArgumentParser(description="NFR-01 帧率基准测试")
    parser.add_argument("--duration", type=int, default=BENCH_DURATION_SECONDS, help="基准时长（秒）")
    parser.add_argument("--difficulty", type=str, default="hard", choices=["easy", "medium", "hard"])
    args = parser.parse_args()

    difficulty_map = {"easy": Difficulty.EASY, "medium": Difficulty.MEDIUM, "hard": Difficulty.HARD}
    difficulty = difficulty_map[args.difficulty]

    print(f"[bench_fps] 开始基准测试（duration={args.duration}s, difficulty={args.difficulty}）...")
    result = run_benchmark(args.duration, difficulty)

    print(f"\n[bench_fps] 结果:")
    print(f"  平均 FPS: {result['avg_fps']:.1f}")
    print(f"  P50 帧时间: {result['p50_frame_ms']:.2f}ms")
    print(f"  P95 帧时间: {result['p95_frame_ms']:.2f}ms (限值: {P95_FRAME_TIME_MS_MAX}ms)")
    print(f"  P99 帧时间: {result['p99_frame_ms']:.2f}ms")
    print(f"  平均输入延迟: {result['input_latency_ms']:.2f}ms")
    print(f"  NFR-01 评估: {result['result']}")

    sys.exit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
```

#### 4.11.2 `scripts/bench_memory.py`

```python
#!/usr/bin/env python3
"""scripts/bench_memory.py — NFR-02 内存实测脚本。

用法：
  python3 scripts/bench_memory.py [--duration 60]

输出：
  - 内存峰值（MB）
  - 平均内存占用（MB）
  - 评估：NFR-02 PASS / FAIL

r2 修订（P0-4）：
- sys.path 补全三依赖包 + iter-3 代码目录
- 经 game_app.perf re-export 导入性能常量
- 删除 _on_bench_complete 钩子调用（P2-4）
"""
import sys
import os
import time
import argparse
import resource  # Unix only

# r2 修订（P0-4）：添加项目根目录到 sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "game-core", "iter-2"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "gui-renderer", "iter-3"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "platform-storage", "iter-2"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "game-app", "iter-3"))

# r2 修订（P0-4）：经 game_app 顶层导入
from game_app import App, AppConfigV3  # noqa
from game_app.perf import MEMORY_PEAK_MB_MAX, BENCH_DURATION_SECONDS  # noqa
from game_core import Difficulty  # noqa


def get_memory_mb() -> float:
    """获取当前进程内存占用（MB，RSS）。"""
    if sys.platform == "win32":
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    else:
        # Unix: rusage.ru_maxrss 单位是 KB
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run_benchmark(duration: int) -> dict:
    """运行 NFR-02 内存基准测试。"""
    app = App(AppConfigV3(enable_high_dpi=True))
    app._init_pygame()
    app._difficulty = Difficulty.HARD
    app._new_game(Difficulty.HARD)

    memory_samples = []
    start_time = time.perf_counter()

    while time.perf_counter() - start_time < duration:
        app._tick(16)  # 60 FPS
        app._render()
        memory_samples.append(get_memory_mb())
        time.sleep(0.016)  # 模拟 60 FPS

    peak_mb = max(memory_samples)
    avg_mb = sum(memory_samples) / len(memory_samples)
    result = "PASS" if peak_mb <= MEMORY_PEAK_MB_MAX else "FAIL"

    return {
        "peak_mb": peak_mb,
        "avg_mb": avg_mb,
        "duration_s": duration,
        "result": result,
    }


def main():
    parser = argparse.ArgumentParser(description="NFR-02 内存基准测试")
    parser.add_argument("--duration", type=int, default=BENCH_DURATION_SECONDS)
    args = parser.parse_args()

    print(f"[bench_memory] 开始内存基准测试（duration={args.duration}s）...")
    result = run_benchmark(args.duration)

    print(f"\n[bench_memory] 结果:")
    print(f"  内存峰值: {result['peak_mb']:.1f}MB (限值: {MEMORY_PEAK_MB_MAX}MB)")
    print(f"  内存平均: {result['avg_mb']:.1f}MB")
    print(f"  NFR-02 评估: {result['result']}")

    sys.exit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
```

### 4.12 用户指南 USER_GUIDE.md（**G4-4 新增，FR-16，r2 修订 P2-3 下载链接标注**）

```markdown
# 用户指南：Snake GUI v2.0.0

> 跨平台贪吃蛇游戏 · 三平台免安装单文件可执行

---

## 1. 下载与运行

### 1.1 下载地址

> **r2 修订（P2-3）**：以下链接为**发布占位**，发布时替换为真实下载地址（同时
> 校对 `SHA256SUMS` 中的校验和）。

- **Linux**：[snake-gui-linux-x86_64](https://example.com/snake-gui-linux-x86_64) (约 25MB)
- **Windows**：[snake-gui-windows-x86_64.exe](https://example.com/snake-gui-windows-x86_64.exe) (约 25MB)
- **macOS**：[snake-gui-macos-universal2.app](https://example.com/snake-gui-macos-universal2.app) (约 30MB，支持 Intel + Apple Silicon)

下载后请校验 SHA256 校验和（参见 `SHA256SUMS` 文件）。

### 1.2 运行方式

#### Linux
```bash
chmod +x snake-gui-linux-x86_64
./snake-gui-linux-x86_64
```

如提示缺少 SDL2 库：
```bash
# Ubuntu / Debian
sudo apt install libsdl2-2.0-0

# Fedora
sudo dnf install SDL2

# Arch
sudo pacman -S sdl2
```

#### Windows
双击 `snake-gui-windows-x86_64.exe` 即可运行。

如 Windows SmartScreen 提示"未知发布者"，点击"更多信息" → "仍要运行"。

#### macOS
双击 `snake-gui-macos-universal2.app` 即可运行。

如 macOS Gatekeeper 提示"无法打开，因为无法验证开发者"，在"系统设置" → "隐私与安全性"中点击"仍要打开"。

### 1.3 系统要求

| 平台 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Linux | Ubuntu 22.04+ / Fedora 36+ / Arch (最新) | 同左 |
| Windows | Windows 10 | Windows 10 / 11 |
| macOS | macOS 12 (Monterey) | macOS 13 (Ventura) 或更新 |

无需预装 Python / Node / Java 等任何运行时。

---

## 2. 键位表

| 键 | 功能 |
|----|------|
| W / ↑ | 向上转向 |
| S / ↓ | 向下转向 |
| A / ← | 向左转向 |
| D / → | 向右转向 |
| P | 暂停 / 继续 |
| 1 | 选择简单难度 |
| 2 | 选择普通难度 |
| 3 | 选择困难难度 |
| ← | 菜单态切换上一皮肤 |
| → | 菜单态切换下一皮肤 |
| R | 结束画面重新开始 |
| H | 重置最高分 |
| ESC | 返回菜单（在结束画面） |
| Q | 退出游戏（任意时刻） |
| 窗口关闭按钮 | 退出游戏 |

---

## 3. 难度

游戏提供三档难度（游戏中不可切换，需返回菜单重新选择）：

| 难度 | 节拍 | 说明 |
|------|------|------|
| 简单 | 250ms / 格 | 蛇速慢，适合新手 |
| 普通 | 160ms / 格 | 蛇速适中，标准体验 |
| 困难 | 100ms / 格 | 蛇速快，挑战极限 |

档位间节拍差异显著（困难 ≤ 简单 50%）。蛇身增长后会自动加速（加速曲线）。

---

## 4. 皮肤

游戏提供 3 套皮肤（在菜单界面用 ← / → 切换）：

| 皮肤 | 特点 |
|------|------|
| 经典 | 默认配色，白底深色蛇 |
| 深色 | 深色主题，适合夜间游戏 |
| 色盲友好 | 叠加形状/纹理辨识（不以颜色为唯一区分），适合色盲用户 |

皮肤切换即时生效，不中断当前对局。

---

## 5. 暂停

游戏中按 P 键暂停，再按 P 键继续。

暂停时画面定格，节拍停止。窗口失焦也会自动暂停。

---

## 6. 平台差异

| 平台 | 字体 | 数据目录 | 已知问题 |
|------|------|---------|---------|
| Linux | 打包内置字体（`fonts/SourceHanSansCN-Regular.otf`）优先，系统字体回退（**r2 修订**） | `~/.local/share/snake-gui/highscore.json` | 部分 Linux 发行版需手动安装 SDL2 库 |
| Windows | 打包内置字体 | `%APPDATA%\snake-gui\highscore.json` | SmartScreen 首次运行需手动确认 |
| macOS | 系统字体 | `~/Library/Application Support/snake-gui/highscore.json` | Gatekeeper 首次运行需手动确认；macOS <12 兼容性未充分测试 |

---

## 7. 已知限制

- **未签名 / 未公证**：Windows SmartScreen / macOS Gatekeeper 首次运行会触发警告（手动确认即可）
- **macOS <12**：未充分测试，可能存在兼容性问题
- **窗口缩放**：依赖 pygame VIDEORESIZE 事件流；若显卡驱动版本异常，可能无法拖拽窗口
- **中文显示**：依赖打包内置字体（`SourceHanSansCN-Regular.otf`，OFL 协议），位于 `<_MEIPASS>/fonts/` 或 `<game_app>/fonts/`（**r2 修订**）；若字体文件损坏，将回退到系统字体或 SDL 默认字体（中文显示为方框）
- **HiDPI 缩放**：默认启用；若显卡驱动不支持，将自动降级到非缩放模式（可能略糊）
- **退出码**：0 正常 / 1 app 异常 / 2 图形环境不可用 / 3 用户数据目录不可写（**r2 修订**：可供脚本判断错误类型）
```

### 4.13 发布说明 RELEASE_NOTES.md（**G4-6 新增，r2 修订 P2-3 下载链接标注**）

```markdown
# 发布说明：Snake GUI v2.0.0

> 跨平台 GUI 贪吃蛇 · 首次发布 · 2026-08-14

## 0. 发布信息

- **版本**：v2.0.0
- **日期**：2026-08-14（UTC）
- **状态**：released
- **需求**：snake-gui（FR-01~16 + NFR-01~07 全部完成）

## 1. 一句话总结

交付一个跨 Windows / macOS / Linux 三平台的图形界面贪吃蛇游戏，免安装单文件可执行，支持难度分级、暂停/继续、最高分持久化、3 套皮肤（含色盲友好），覆盖需求规格全部验收项。

## 2. 新功能

- **经典玩法**（FR-01~04）：方向控制 / 吃食增长 / 食物不重叠 / 反向禁止 / 撞墙撞身结束
- **难度分级**（FR-05）：三档（简单/普通/困难），游戏中不可切换
- **图形界面**（FR-06~09）：平滑动画 / 窗口缩放 / 美观基线
- **皮肤系统**（FR-10）：3 套皮肤（经典/深色/色盲友好），游戏中可切换
- **暂停/继续**（FR-12）：P 键暂停，窗口失焦自动暂停
- **最高分持久化**（FR-13）：本地 JSON 存储，原子写防损坏
- **三平台免安装**（FR-14）：PyInstaller 单文件打包，零预装依赖
- **跨平台一致**（FR-15）：三平台行为一致
- **用户指南**（FR-16）：五节齐全（下载运行/键位表/难度/皮肤/暂停/平台差异/已知限制）

## 3. 性能指标

- **帧率**：≥60 FPS（P95 帧时间 ≤25ms）—— `scripts/bench_fps.py` 实测
- **内存**：≤300MB —— `scripts/bench_memory.py` 实测
- **CPU**：≤10%（空闲画面，单核）

## 4. 下载与校验

> **r2 修订（P2-3）**：以下链接为**发布占位**，发布时替换为真实下载地址。

参见 `SHA256SUMS` 文件校验下载完整性（由 `scripts/gen_sha256sums.sh` 生成，**r2 修订**：三平台构建脚本不各自生成校验和）。

## 5. 已知问题

参见 `USER_GUIDE.md` §7 已知限制。

## 6. 后续计划

- 优化打包体积（当前 25-30MB，可压缩至 15-20MB）
- 添加音效（可选，需用户拍板）
- 移动端版本（Android / iOS）
- Windows 代码签名 / macOS 苹果公证
```

---

## 5. DFx / 可测试性 / 鲁棒性 / 韧性

### 5.1 可维护性（Maintainability）

- 沿用 iter-1/2/3 约定：每个公开类/方法有 docstring，标注对应 FR/NFR 编号。
- 不变量在代码中以 `# INV-N` 注释 + UT 用例双标注（iter-4 新增 INV-17/18/19/20）。
- 单一职责：`errors.py` 仅管异常类 + 退出码映射；`perf.py` 仅管性能常量；`_constants.py` 仅管路径定位；`fonts/` 仅管打包资源。
- **iter-4 增量入口**仅 4 处：错误类型扩展（`errors.py` G4-2，r2 修订精确子类优先）+ HiDPI 降级包装（`_init_pygame` G4-2）+ 字体加载路径（`_load_cjk_font` G4-5）+ 性能脚本（`scripts/` G4-3），**最小侵入**。

### 5.2 可扩展性（Extensibility）

- **AppConfigV4 子类化扩展**：iter-4+ 若加新运行期常量，可继续子类化 `AppConfigV4(AppConfigV3)`，**不破坏 iter-1/2/3 既有 `AppConfig` 兼容性**。
- **错误类型扩展**：新增异常类只需在 `_EXIT_CODE_MAP` 添加映射（注意精确子类在前），**无需修改 main() 退出逻辑**。
- **打包资源扩展**：新增字体/图片等静态资源只需在 `spec/snake-gui.spec` 的 `datas` 列表添加条目即可（目标子目录与 `get_bundled_font_path` 一致），**app 代码无需修改**。
- **性能脚本扩展**：新增基准维度只需在 `perf.py` 添加常量 + 新建 `scripts/bench_*.py`，**主程序无需修改**。

### 5.3 可部署性（Deployability）

- **PyInstaller 单文件**（G4-1）：`--onefile --windowed --name snake-gui --collect-submodules game_app --collect-submodules platform_storage --collect-submodules gui_renderer --add-data "fonts/SourceHanSansCN-Regular.otf:fonts"` + **r2 修订 P0-1**：spec pathex 含三依赖包源码目录
- **三平台原生构建**（G4-1）：Linux 在 Linux 构建机 / Windows 在 Windows 构建机 / macOS 在 macOS 构建机（PyInstaller 不支持交叉打包）
- **macOS 双架构**（G4-1，r2 修订 P1-3）：`--target-arch x86_64` + `--target-arch arm64` + `lipo -create` 以 arm64 完整 `.app` 为基础合并二进制
- **入口无副作用 import**：`import game_app` 不开窗、不调 `pygame.init()`、不构造 `HighScoreStore`。
- **CI 集成**：可在 GitHub Actions / GitLab CI 配置三平台矩阵（`.github/workflows/release.yml`），触发 tag 自动构建发布物（**iter-4 不实施，仅留扩展点**）。

### 5.4 可测试性（Testability）

- **pygame 依赖可桩化**：UT 通过 `monkeypatch` 替换 `game_app.app + game_app.menu + game_app.storage + game_app.input + game_app.fonts + game_app.config + game_app.errors + game_app.perf` 内部的 pygame + platform_storage + warnings 模块为 fake。
- **错误路径可触发**：fake `Renderer.init.side_effect = (RenderError, pygame.error)` → 触发 GraphicsUnavailableError → 退出码 2；fake `create_storage.side_effect = OSError(...)` → 触发 StorageUnavailableError → 退出码 3。
- **HiDPI 降级可测**：fake `Renderer.init.side_effect = [pygame.error("SCALED unsupported"), MagicMock()]` → 断言第一次失败后降级成功 + `_hidpi_degraded == True`。
- **字体加载可测**：fake `get_bundled_font_path.return_value = "/path/to/font.otf"` → 断言优先用内置字体；fake `pygame.font.Font.side_effect = pygame.error(...)` → 断言回退链生效。
- **性能脚本可测**：mock `time.perf_counter()` + `resource.getrusage()` → 断言 PASS/FAIL 判定逻辑正确；fake `sys.path` 注入 fake 模块验证导入路径（**r2 修订**）。
- **用户指南字段完备性**：解析 `USER_GUIDE.md` Markdown，断言五节齐全（下载运行/键位表/难度/皮肤/暂停/平台差异/已知限制）。
- **构建脚本冒烟**：UT 用 `subprocess.run(['bash', 'scripts/build_linux.sh'], ...)` 在临时目录运行，断言生成 `dist/snake-gui-linux-x86_64` 文件且**可启动**（**r2 修订 P0-1**：BUILD-1 加"产物可启动"断言：subprocess.run 启动产物，3 秒内未崩溃 + ImportError 即通过）。
- **macOS bundle 结构**（**r2 修订 P1-3**）：BUILD-3 断言 `dist/snake-gui.app/Contents/Info.plist` 存在 + `Contents/MacOS/snake-gui` 可执行。

### 5.5 鲁棒性 / 韧性（**G4-2 新增 + iter-1/2/3 沿用，r2 修订 P1-1 一致性**）

| 场景 | 处理 |
|------|------|
| **图形环境缺失**（G4-2） | `Renderer.init` 抛 RenderError → HiDPI 降级（仅第一次）→ 仍失败抛 GraphicsUnavailableError → 退出码 2 + stderr suggestion（"请检查显示器/SDL2/显卡驱动"） |
| **HiDPI 降级**（G4-2） | SCALED 标志失败 → 自动降级到非 SCALED 模式 + stderr warning（HighDPIWarning） + `_hidpi_degraded=True`（INV-18）→ **不退出** |
| **用户数据目录不可写**（G4-2，**r2 修订 P1-1**） | `HighScoreStore.mkdir/save` 抛 OSError / score_callback 内 save 抛 StorageError → 抛 StorageUnavailableError → **退出码 3**（iter-4 新增，区分于一般 AppError）+ stderr suggestion（"请检查 ~/.local/share 目录权限"） |
| **CJK 字体回退**（G4-5） | 打包内置字体（fonts/ 子目录）+ match_font 回退链全失败 → SDL 默认字体 + stderr warning（CJKFontFallbackWarning） + `_cjk_font_fallback=True`（INV-19）→ **不退出**，中文显示为方框 |
| **平台版本不兼容**（G4-2，**r2 修订 P1-2**） | macOS <12 / Windows <10（取 `win32_ver()[0]` 版本号字段）→ stderr warning（PlatformUnsupportedWarning）→ **不退出**，尽力兼容（INV-19） |
| 窗口事件源缺失（r2-2 沿用） | gui-renderer 窗口未带 RESIZABLE → VIDEORESIZE 永不可达 → FR-09 验收不可达（用户指南"已知限制"小节提及） |
| 最高分文件损坏（iter-2 沿用） | `HighScoreStore.load` 备份为 `.corrupt-<ts>.json` 后返 0 |
| 配置非法（iter-2 沿用） | `AppConfig.__post_init__` 抛 ConfigError → 退出码 1 |
| 同一帧多事件（iter-2 沿用） | `_drain_events` 返 list；主循环按序处理；QUIT 优先 break |
| 反向输入（iter-2 沿用） | 透传到 `core.set_direction`；core 内静默忽略 |
| 撞墙/撞身（iter-2 沿用） | `core.step` 返回 `status=OVER`；`_tick` 检测后自动转 `GAME_OVER` |
| 关窗（iter-2 沿用） | `pygame.QUIT` 事件 → `QUIT` action → 主循环 break → `renderer.shutdown()` |
| 窗口失焦（iter-2 沿用） | `pygame.key.get_focused() == False` + PLAYING 态 → 追加 `UNFOCUS` action → `toggle_pause()` → `screen=PAUSED` |

### 5.6 错误处理矩阵（iter-4 G4-2 全量修订 + iter-3 G3-2 沿用，r2 修订 P1-1 一致性确认）

| 错误情形 | 退出码 | 行为 |
|----------|:------:|------|
| `Renderer.init()` 失败 | 2 | GraphicsUnavailableError → stderr suggestion → exit 2 |
| `Renderer.__init__` 校验失败 | 2 | 同上 |
| `AppConfig(fps_cap=0)` | 1 | ConfigError → stderr → exit 1 |
| `AppConfig(window_w < min_window_w)` | 1 | 同上 |
| `AppConfigV3(enable_high_dpi=...)` 非法 | - | 理论不可达（bool 字段无非法值） |
| **HighScoreStore mkdir 失败** | **3** | **StorageUnavailableError → stderr suggestion → exit 3（G4-2 新增退出码）** |
| **HighScoreStore save 失败** | **3** | **同上（r2 修订 P1-1：明确包含 score_callback 内 save 失败）** |
| **`_dispatch_menu(RESET_HIGHSCORE)` 失败** | **3** | **同上（r2 修订 P1-1：明确包含 dispatch 路径失败）** |
| **`score_callback` 内 `storage.save` 失败** | **3** | **同上（r2 修订 P1-1：明确包含 score_callback 路径失败）** |
| **HiDPI 缩放失败** | - | **HighDPIWarning → 自动降级 → 不退出（G4-2 新增非致命警告）** |
| **CJK 字体回退** | - | **CJKFontFallbackWarning → SDL 默认字体 → 不退出（G4-5 新增非致命警告）** |
| **平台版本不兼容** | - | **PlatformUnsupportedWarning → stderr warning → 不退出（G4-2 新增非致命警告）** |
| 皮肤切换失败（iter-3 G3-1） | - | SkinNotFoundError → `_switch_skin` 兜底 stderr 提示 + 维持 `_skin_index` 不变 |
| 窗口缩放过小（iter-3 G3-2） | - | RenderError → `_handle_resize` 兜底 stderr 提示 + 维持当前尺寸 |
| 窗口事件源缺失（r2-2 沿用） | - | gui-renderer 未带 RESIZABLE → FR-09 验收不可达（契约前置） |
| 未捕获异常 | 1 | 走解释器默认行为（stderr traceback + exit 1） |

---

## 6. UT 框架（FO TDD 依据）

### 6.1 测试组织（见 §4.1 文件树）

```
snake-linux/code/game-app/iter-3/tests/test_game_app/
├── conftest.py                        # 沿用 iter-3 fixtures（G3-R-P1-A/B/C）
├── test_app_init.py                   # 沿用 iter-3
├── test_app_loop.py                   # 沿用 iter-3
├── test_input_map.py                  # 沿用 iter-3
├── test_menu_draw.py                  # 沿用 iter-3
├── test_app_iter3_skin.py             # 沿用 iter-3
├── test_app_iter3_resize.py           # 沿用 iter-3
├── test_app_iter3_interp.py           # 沿用 iter-3
├── test_app_iter3_config_v3.py        # 沿用 iter-3
├── test_app_iter3_e2e.py              # 沿用 iter-3
└── test_app_iter4.py                  # G4-2/3/4/5 增量 UT
    ├── test_errors.py                 # G4-2：错误类型 + 退出码映射（r2 修订 P0-3：精确子类优先）
    ├── test_hidpi_fallback.py         # G4-2：HiDPI 降级
    ├── test_platform_check.py         # G4-2：平台版本检查（r2 修订 P1-2：win32_ver()[0]）
    ├── test_font_loading.py           # G4-5：内置字体优先 + 回退链（r2 修订 P0-2：fonts/ 子目录）
    ├── test_perf_constants.py         # G4-3：性能常量正确性
    ├── test_bench_fps.py              # G4-3：NFR-01 帧率基准脚本（r2 修订 P0-4：sys.path 完整）
    ├── test_bench_memory.py           # G4-3：NFR-02 内存基准脚本（r2 修订 P0-4：sys.path 完整）
    ├── test_user_guide.py             # G4-4：用户指南字段完备性
    ├── test_release_notes.py          # G4-6：发布说明字段完备性
    └── test_sha256sums.py             # G4-1：SHA256SUMS 生成正确性（r2 修订 P2-2：仅 gen_sha256sums 生成）
```

### 6.2 桩与夹具（conftest.py，沿用 iter-3 + G4-2 扩展）

```python
# conftest.py — iter-3 fixtures + iter-4 G4-2 扩展


@pytest.fixture
def fake_warnings(monkeypatch):
    """G4-2 新增：桩化 warnings.warn 以断言警告触发。"""
    import warnings as warnings_mod
    warnings_list = []
    def fake_warn(message, category=UserWarning, stacklevel=1):
        warnings_list.append((message, category))
    monkeypatch.setattr(warnings_mod, "warn", fake_warn)
    return warnings_list


@pytest.fixture
def app_iter4(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch, fake_warnings):
    """G4-2 新增：构造已 _init_pygame 的 App，模拟 HiDPI 降级。"""
    from game_app import App, AppConfigV3
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_app import fonts as fonts_mod

    # 第一次 init 失败 → 触发 HiDPI 降级
    fake_renderer_init = MagicMock(side_effect=[pygame.error("SCALED unsupported"), MagicMock()])
    fake_renderer_iter3.init = fake_renderer_init

    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)

    a = App(AppConfigV3(enable_high_dpi=True))
    a._init_pygame()
    return a
```

### 6.3 测试用例清单

| ID | 用例名 | 覆盖场景 | 来源 |
|----|--------|---------|------|
| **ERR-1** | test_graphics_unavailable_exit_2 | Renderer.init 失败 → GraphicsUnavailableError → run() 返 2 | G4-2 |
| **ERR-2** | test_graphics_unavailable_stderr_suggestion | GraphicsUnavailableError.suggestion 写入 stderr | G4-2 |
| **ERR-3** | test_storage_unavailable_exit_3 | create_storage 抛 OSError → StorageUnavailableError → run() 返 3 | G4-2 |
| **ERR-4** | test_storage_unavailable_stderr_suggestion | StorageUnavailableError.suggestion 写入 stderr | G4-2 |
| **ERR-5** | test_error_to_exit_code_mapping | error_to_exit_code(GraphicsUnavailableError) == 2；error_to_exit_code(StorageUnavailableError) == 3；error_to_exit_code(ConfigError) == 1 | G4-2，r2 修订 P0-3 |
| **ERR-6** | test_error_to_exit_code_subclass_priority（**r2 修订**） | 精确子类优先：_EXIT_CODE_MAP 中 GraphicsUnavailableError（精确子类）在 AppError（基类）之前 | r2 P0-3 |
| **ERR-7** | test_main_loop_storage_unavailable_exit_3（**r2 修订 P1-1**） | score_callback 内 storage.save 抛 StorageUnavailableError → 主循环捕获 → 返 3（不返 1） | r2 P1-1 |
| **HIDPI-1** | test_hidpi_first_try_fails_fallback | enable_high_dpi=True init 失败 → 降级到 enable_high_dpi=False init 成功 | G4-2 |
| **HIDPI-2** | test_hidpi_both_fail_raise_graphics_unavailable | HiDPI + 非 HiDPI 都失败 → GraphicsUnavailableError | G4-2 |
| **HIDPI-3** | test_hidpi_warning_emitted | HiDPI 降级触发 stderr HighDPIWarning（INV-18） | G4-2 |
| **HIDPI-4** | test_hidpi_degraded_flag_set | 降级成功后 `_hidpi_degraded == True` | G4-2 |
| **PLAT-1** | test_macos_old_version_warning | macOS <12 → PlatformUnsupportedWarning | G4-2 |
| **PLAT-2** | test_windows_old_version_warning | Windows <10 → PlatformUnsupportedWarning（**r2 修订 P1-2**：mock win32_ver() 返回 ("10", hostname, build, ...) 断言触发） | G4-2，r2 P1-2 |
| **PLAT-3** | test_unsupported_platform_continues | 平台警告后 run() 仍继续（不退出） | G4-2 |
| **FONT-1** | test_bundled_font_priority | get_bundled_font_path 返 `<_MEIPASS>/fonts/<file>` 或 `<game_app>/fonts/<file>` 有效路径 → 优先用内置字体（**r2 修订 P0-2**） | G4-5，r2 P0-2 |
| **FONT-2** | test_match_font_fallback | 内置字体失败 → match_font 回退链生效 | G4-5 |
| **FONT-3** | test_default_font_last_resort | 全失败 → pygame.font.Font(None, size) 兜底 | G4-5 |
| **FONT-4** | test_cjk_font_fallback_warning | CJKFontFallbackWarning 触发（INV-19） | G4-5 |
| **FONT-5** | test_cjk_font_fallback_flag_set | 全失败后 `_cjk_font_fallback == True` | G4-5 |
| **FONT-6** | test_bundled_font_path_consistency（**r2 修订**） | spec datas 目标 `fonts/` 与 get_bundled_font_path 路径一致；fake `_MEIPASS` 包含 `fonts/` 子目录 → 函数返该路径 | r2 P0-2 |
| **PERF-1** | test_perf_constants_values | TARGET_FPS == 60；P95_FRAME_TIME_MS_MAX == 25.0；MEMORY_PEAK_MB_MAX == 300 | G4-3 |
| **PERF-2** | test_bench_fps_pass_when_fast | mock 时间 → frame_time_ms=20 → PASS | G4-3 |
| **PERF-3** | test_bench_fps_fail_when_slow | mock 时间 → frame_time_ms=50 → FAIL | G4-3 |
| **PERF-4** | test_bench_memory_pass_when_low | mock 内存 → peak_mb=200 → PASS | G4-3 |
| **PERF-5** | test_bench_memory_fail_when_high | mock 内存 → peak_mb=400 → FAIL | G4-3 |
| **PERF-6** | test_bench_imports（**r2 修订 P0-4**） | bench_fps.py / bench_memory.py 经 `game_app.perf` 导入常量成功；sys.path 含三依赖包 | r2 P0-4 |
| **GUIDE-1** | test_user_guide_sections_complete | USER_GUIDE.md 包含"下载与运行/键位表/难度/皮肤/暂停/平台差异/已知限制"五节 | G4-4 |
| **GUIDE-2** | test_user_guide_platform_sections | USER_GUIDE.md 包含 Linux/Windows/macOS 三平台说明 | G4-4 |
| **GUIDE-3** | test_user_guide_keymap_table | USER_GUIDE.md 包含 WASD/方向键/P/Q 等键位说明 | G4-4 |
| **REL-1** | test_release_notes_version | RELEASE_NOTES.md 包含 "v2.0.0" | G4-6 |
| **REL-2** | test_release_notes_features | RELEASE_NOTES.md 列出新功能（难度/暂停/最高分/皮肤） | G4-6 |
| **SHA-1** | test_sha256sums_format_relaxed（**r2 修订 P2-1**） | SHA256SUMS 文件每行含 64-hex 即过（不再严格 `<64-hex>  <file>` 格式，避免 certutil 输出格式冲突） | G4-1，r2 P2-1 |
| **SHA-2** | test_sha256sums_match_actual | 重新计算 SHA256 与文件中记录匹配 | G4-1 |
| **BUILD-1** | test_build_linux_smoke（**仅 Linux CI 环境**，**r2 修订 P0-1**） | bash scripts/build_linux.sh → 生成 dist/snake-gui-linux-x86_64 **且可启动**（subprocess.run 启动后 3 秒内不抛 ImportError） | G4-1，r2 P0-1 |
| **BUILD-2** | test_build_windows_smoke（**仅 Windows CI 环境**） | scripts/build_windows.bat → 生成 dist/snake-gui-windows-x86_64.exe | G4-1 |
| **BUILD-3** | test_build_macos_smoke（**仅 macOS CI 环境**，**r2 修订 P1-3**） | bash scripts/build_macos.sh → 生成 dist/snake-gui.app **且 bundle 结构完整**（Info.plist + Contents/MacOS/snake-gui） | G4-1，r2 P1-3 |
| **SPEC-1** | test_spec_file_syntax | spec/snake-gui.spec 语法正确（PyInstaller --clean --dry-run） | G4-1 |
| **SPEC-2** | test_spec_datas_include_fonts | datas 列表包含 SourceHanSansCN-Regular.otf 且目标为 `fonts/` 子目录 | G4-1，r2 P0-2 |
| **SPEC-3** | test_spec_hiddenimports | hiddenimports 包含 game_app/platform_storage/gui_renderer | G4-1 |
| **SPEC-4** | test_spec_pathex_dependencies（**r2 修订 P0-1**） | pathex 列表含 GAME_APP_DIR + GAME_CORE_DIR + GUI_RENDERER_DIR + PLATFORM_STORAGE_DIR | r2 P0-1 |

### 6.4 覆盖率目标

- **行覆盖 ≥ 90%**（`app.py` 主循环 / dispatch / `_init_pygame` / `_load_cjk_font` / `errors.py` 必须 100%；`perf.py` / `_constants.py` / `fonts.py` ≥ 85%）
- **分支覆盖 ≥ 85%**（错误处理分支 / 退出码映射分支 / 字体回退分支 / HiDPI 降级分支 / 平台检查分支）
- **G4-2 修订**：错误路径 UT 覆盖 4 类退出码（0/1/2/3）+ 3 类非致命警告（HiDPI/CJK/PlatformUnsupported）
- **G4-5 修订**：字体加载 UT 覆盖 3 类回退路径（内置/系统/默认）
- **r2 修订**：精确子类优先（ERR-6）+ 主循环退出码一致性（ERR-7）+ 字体路径一致性（FONT-6）+ spec pathex 完整（SPEC-4）

### 6.5 UT 运行命令

```bash
# r2 修订（P2-5）：用 pytest（读 pytest.ini 的 pythonpath），而非 unittest discover
cd snake-linux/code/game-app/iter-3
pytest tests/test_game_app -v --cov=game_app --cov-branch --cov-fail-under=90
```

### 6.6 FO TDD 实施步骤（建议，按 G4 增量分组）

**第一阶段（G4-2 错误处理 + 退出码 3，r2 修订精确子类优先）**：
1. 写 `test_errors.py`（UT ERR-1/2/3/4/5/6）→ 跑（红）→ 改 `errors.py` 加 StorageUnavailableError + suggestion 字段 + error_to_exit_code 函数（绿）；**r2 修订 P0-3**：`_EXIT_CODE_MAP` 精确子类优先（GraphicsUnavailableError/StorageUnavailableError 在 AppError 之前）
2. 改 `app.py._init_pygame` 加 HiDPI 降级包装（§4.7）→ 跑（红）→ 写 `_create_renderer_with_hidpi_fallback`（绿）
3. 写 `test_hidpi_fallback.py`（UT HIDPI-1/2/3/4）→ 跑
4. 写 `test_platform_check.py`（UT PLAT-1/2/3，**r2 修订**：PLAT-2 mock win32_ver() 返 ("10", hostname, build)）→ 跑（红）→ 写 `_check_platform_version`（**r2 修订**：取 `win32_ver()[0]`）（绿）
5. 改 `app.py.run` 加 StorageUnavailableError → exit 3（**r2 修订 P1-1**：主循环 AppError 之前捕获 StorageUnavailableError）+ GraphicsUnavailableError suggestion 写入 stderr（§4.2）

**第二阶段（G4-5 字体加载，r2 修订 P0-2 fonts/ 子目录）**：
6. 下载 `SourceHanSansCN-Regular.otf`（OFL 协议）放到 `game_app/fonts/` 目录
7. 写 `_constants.py.get_bundled_font_path()`（§1.3，**r2 修订**：路径含 `fonts/` 子目录）→ 跑（红）→ 写（绿）
8. 改 `fonts.py._load_cjk_font` 优先内置字体（§4.8，**r2 修订**：路径由 get_bundled_font_path 统一）→ 跑（红）→ 改（绿）
9. 写 `test_font_loading.py`（UT FONT-1/2/3/4/5/6）→ 跑

**第三阶段（G4-3 性能脚本，r2 修订 P0-4 sys.path 完整）**：
10. 写 `perf.py` 性能常量（§1.2）→ 跑（红）→ 写（绿）
11. 写 `scripts/bench_fps.py`（§4.11.1，**r2 修订 P0-4**：sys.path 含三依赖包 + `from game_app.perf import`）→ 跑（红）→ 写（绿）
12. 写 `scripts/bench_memory.py`（§4.11.2，**r2 修订 P0-4**：sys.path 含三依赖包 + `from game_app.perf import`）→ 跑（红）→ 写（绿）
13. 写 `test_perf_constants.py` + `test_bench_fps.py` + `test_bench_memory.py`（UT PERF-1~6）→ 跑

**第四阶段（G4-1 打包，r2 修订 P0-1/P1-3/P2-2）**：
14. 写 `spec/snake-gui.spec`（§4.9，**r2 修订 P0-1**：pathex 含 GAME_APP_DIR + GAME_CORE_DIR + GUI_RENDERER_DIR + PLATFORM_STORAGE_DIR）→ 跑（红）→ 写（绿）
15. 写 `scripts/build_linux.sh` + `scripts/build_windows.bat` + `scripts/build_macos.sh`（§4.10.1/2/3，**r2 修订 P2-2**：不生成 SHA256SUMS；**r2 修订 P1-3**：macOS lipo 以 arm64 完整 .app 为基础）→ 跑（红）→ 写（绿）
16. 写 `scripts/gen_sha256sums.sh`（§4.10.4，**r2 修订 P2-2**：统一汇总三平台包）→ 跑（红）→ 写（绿）
17. 在 Linux 构建机上跑 `bash scripts/build_linux.sh`（**手工**，CI 环境）→ 验证生成 `dist/snake-gui-linux-x86_64`
18. 写 `test_spec_file_syntax.py` + `test_sha256sums.py`（UT SPEC-1/2/3/4 + SHA-1/2，**r2 修订 P2-1**：SHA-1 放宽为"含 64-hex 即过"）→ 跑

**第五阶段（G4-4/G4-6 文档，r2 修订 P2-3）**：
19. 写 `USER_GUIDE.md`（§4.12，**r2 修订 P2-3**：下载链接标注"发布占位"）→ 写 `test_user_guide.py`（UT GUIDE-1/2/3）→ 跑（红）→ 补字段（绿）
20. 写 `RELEASE_NOTES.md`（§4.13，**r2 修订 P2-3**：下载链接标注"发布占位"）→ 写 `test_release_notes.py`（UT REL-1/2）→ 跑（红）→ 补字段（绿）

**第六阶段（端到端 + 真实构建验证）**：
21. 改 `conftest.py` 加 `fake_warnings` + `app_iter4` fixture（§6.2）→ 跑全部 UT（绿）
22. 写 `test_app_iter4_e2e.py`：MENU 启动 → 选难度 → START → 吃食 → P 暂停 → 撞墙 → GAME_OVER → 重开 → 退出（端到端覆盖 ERR/HIDPI/FONT 全链路）
23. 跑覆盖率报告，确保 ≥ 90% 行 / ≥ 85% 分支
24. **手工真实构建验证清单**（FO 实施后三平台构建机）：
    - [ ] Linux 构建机：bash scripts/build_linux.sh → dist/snake-gui-linux-x86_64 → chmod +x → ./snake-gui-linux-x86_64 → 游戏可启动（**r2 修订 P0-1**：BUILD-1 含"产物可启动"断言）
    - [ ] Windows 构建机：scripts\build_windows.bat → dist\snake-gui-windows-x86_64.exe → 双击运行 → 游戏可启动
    - [ ] macOS 构建机：bash scripts/build_macos.sh → dist/snake-gui.app（**r2 修订 P1-3**：Info.plist 完整 + Contents/MacOS/snake-gui 可执行 lipo 合并） → 双击运行 → 游戏可启动（Intel + Apple Silicon 各验证一次）
    - [ ] 真窗口性能验证：python3 scripts/bench_fps.py → P95 帧时间 ≤ 25ms → PASS
    - [ ] 真窗口内存验证：python3 scripts/bench_memory.py → 峰值 ≤ 300MB → PASS

### 6.7 FO 修订清单（**r2 修订 P2-6：iter-3 既有 UT 同步修订**）

> iter-4 把 StorageUnavailableError 退出码从 1 改为 3，iter-3 既有 UT 若断言旧语义需修订：

| 既有用例 | 修订前断言 | 修订后断言 |
|---------|----------|----------|
| `test_app_iter3_storage.py::test_storage_unavailable_returns_1`（若存在） | `app.run() == 1` | `app.run() == 3` |
| `test_app_iter3_storage.py::test_storage_save_callback_returns_1`（若存在） | `app.run() == 1` | `app.run() == 3` |
| `test_app_iter3_dispatch.py::test_reset_highscore_failure_returns_1`（若存在） | `app.run() == 1` | `app.run() == 3` |

> FO 落地时 grep `snake-linux/code/game-app/iter-3/tests/` 中所有 `== 1` 配合 `StorageUnavailable` / `storage_unavailable` 关键字的断言，确认无遗漏。

---

## 附录 A：迭代 4 → 后续版本增量接口预告（仅供 FO 留扩展点，不在本次实现）

### A.1 后续版本增量

- **优化打包体积**（v2.1.0）：剔除 pygame 冗余模块（pygame.tests / pygame.docs 等）；启用 UPX 压缩；体积从 25-30MB 降至 15-20MB
- **音效支持**（v2.2.0，需用户拍板）：pygame.mixer + 简短 BGM / 吃食音效 / 结束音效
- **移动端**（v3.0.0）：Android / iOS 平台（PyInstaller 不支持，需 Kivy / BeeWare 重构）
- **Windows 代码签名**（v2.0.1）：申请代码签名证书，消除 SmartScreen 警告
- **macOS 苹果公证**（v2.0.1）：申请 Apple Developer ID，完成 Gatekeeper 公证
- **CI/CD**（v2.0.1）：GitHub Actions 三平台矩阵构建 + 自动发布 GitHub Release
- **AppConfigV4 子类**（v2.0.1）：继承 AppConfigV3 加 `target_fps: int = 60` / `window_w/h` 由 640×480 默认改为"上次窗口大小"（读 platform-storage）等扩展点

### A.2 接口扩展原则

- 默认参数 + 新增方法，**不破坏迭代 1/2/3/4 既有签名**
- `App` 公开方法（`run()` / `__init__()`）签名迭代 1~4 不变
- `AppConfig` 字段迭代 1 冻结默认值；迭代 3 通过子类化 `AppConfigV3` 扩展；v2.0.1+ 继续子类化
- 错误类型扩展原则：新增异常类 → 在 `_EXIT_CODE_MAP` 添加映射（**精确子类在前**）→ 不修改 main() 退出逻辑
- 打包资源扩展原则：新增字体/图片 → 在 `spec/snake-gui.spec` 的 `datas` 列表添加条目（目标子目录与代码读取路径一致）→ 不修改 app 代码

---

## 附录 B：依赖与版本（G4 增量）

| 依赖 | 版本 | 约束来源 / 当前状态 |
|------|------|---------------------|
| Python | ≥3.8, <4 | 架构 §代码风格约定 |
| pygame | ≥2.0,<3 | gui-renderer 迭代 3 锁定（`code/gui-renderer/iter-3/gui_renderer/constants.py`） |
| **PyInstaller** | **≥5.13**（iter-4 新增） | 架构 §技术选型；支持 `--onefile --windowed` + Python 3.10+ |
| **SourceHanSansCN-Regular.otf** | **OFL 协议开源中文字体**（iter-4 新增） | G4-5 打包内置；优先于系统字体；规避 Linux 字体版本差异 |
| game-core | 迭代 2 接口为准 — `code/game-core/iter-2/game_core/` it_passed | iter-4 不调用新接口（仅沿用 iter-2 接口） |
| gui-renderer | 迭代 3 `code/gui-renderer/iter-3/gui_renderer/` it_passed | iter-4 沿用：Renderer 构造 + init/shutdown + render(snap, hud, *, interp) + set_skin/handle_resize + skin_names/current_skin_name + fps_metric；**r2-2 契约前置**：Renderer 窗口必须带 RESIZABLE 标志 |
| platform-storage | 迭代 2 接入 | iter-4 沿用 |

---

## 附录 C：与 v1 终端版 + v2 iter-1/2/3 差异（iter-4 增量）

| 项 | v1 终端版 | v2 iter-1/2/3 | **v2 iter-4（G4 增量，r2 修订）** |
|----|----------|---------------|--------------------------|
| 错误提示 | curses 错误退出 + 退出码 | 退出码 0/1/2 | **退出码 0/1/2/3（INV-17）+ stderr suggestion + 非致命警告类；r2 修订：精确子类优先映射** |
| 退出码 | 0/1 | 0/1/2 | **0/1/2/3（G4-2 新增退出码 3；r2 修订：iter-3 既有 UT 需同步修订）** |
| 字体 | 终端字符 | CJK 字体回退链 | **打包内置字体优先 + 系统字体回退链（G4-5；r2 修订：fonts/ 子目录与 spec datas 一致）** |
| 打包 | 源码运行 | 源码运行 | **三平台 PyInstaller 单文件可执行（G4-1；r2 修订：spec pathex 含三依赖包）** |
| 性能 | 无实测 | 无实测 | **NFR-01 ≥60FPS / NFR-02 ≤300MB 实测脚本（G4-3；r2 修订：sys.path 完整）** |
| 用户指南 | README 四节 | README 四节 | **USER_GUIDE.md 五节齐全（G4-4；r2 修订：下载链接标注"发布占位"）** |
| 发布物 | snake.py | 源码 | **snake-gui ELF/.exe/.app + SHA256SUMS + RELEASE_NOTES + USER_GUIDE（G4-1/4/6；r2 修订：SHA256SUMS 仅 gen_sha256sums.sh 生成）** |
| HiDPI | 不适用 | AppConfigV3 + enable_high_dpi | **HiDPI 失败自动降级（INV-18，G4-2）** |
| 平台检查 | 无 | 无 | **平台版本检查（macOS <12 / Windows <10，取 win32_ver()[0]，**r2 修订 P1-2**）+ 非致命警告（G4-2）** |
| macOS 双架构 | 不适用 | 不适用 | **lipo 合并以 arm64 完整 .app 为基础替换二进制（**r2 修订 P1-3**）** |

---

## 附录 D：SE 评审修订对照（**r2 新增**：逐条对应 r1 SE 评审意见）

> 本附录按 SE 评审 `snake-linux/review/design/game-app/iter-4/snake-linux-game-app-design-iter4-r1.md` 编号逐一修订。

| 编号 | 评审意见摘要 | 修订位置 | 修订方式 |
|------|------------|---------|---------|
| **P0-1** | spec 打包缺依赖模块收集 → 产物运行必崩 | §4.1 / §4.9 / §6.1 / §6.3（SPEC-4 新增） / §6.6 第一步 | spec `pathex` 增加 game-core/iter-2、gui-renderer/iter-3、platform-storage/iter-2 三个绝对路径；BUILD-1 加"产物可启动"断言（subprocess.run 启动后 3 秒内不抛 ImportError 即过） |
| **P0-2** | `get_bundled_font_path` 查找路径与 spec datas 目标目录不匹配 | §1.3 / §4.1 / §4.8 / §6.3（FONT-6 新增） / §6.6 第二步 | `_constants.py` 增加 `BUNDLED_FONT_SUBDIR = "fonts"` 常量；`get_bundled_font_path()` 查找 `<_MEIPASS>/fonts/<file>` 与 `<game_app>/fonts/<file>` 两条路径；FONT-6 UT 断言一致 |
| **P0-3** | `error_to_exit_code` 映射顺序 bug → 退出码 2/3 永远返回 1 | §3.7 / §6.3（ERR-6 新增） / §6.6 第一步 | `_EXIT_CODE_MAP` 重排：ConfigError(1) → GraphicsUnavailableError(2) → StorageUnavailableError(3) → AppError(1 兜底)；ERR-6 UT 断言精确子类优先 |
| **P0-4** | 性能基准脚本 import 路径错误 | §4.11.1 / §4.11.2 / §6.3（PERF-6 新增） / §6.6 第三步 | bench_fps.py / bench_memory.py `sys.path.insert` 增加 game-core/iter-2、gui-renderer/iter-3、platform-storage/iter-2 三依赖包路径；`from perf import` 改为 `from game_app.perf import`；PERF-6 UT 断言导入成功 |
| **P1-1** | 主循环内 StorageUnavailableError 退出码与错误矩阵矛盾 | §4.2 / §5.5 / §5.6 / §6.3（ERR-7 新增） / §6.6 第一步 | 主循环 `except AppError` 前加 `except StorageUnavailableError → return 3`；错误矩阵 §5.6 明确 score_callback / dispatch_menu 路径均映射 3；ERR-7 UT 断言主循环捕获时返 3 |
| **P1-2** | Windows 平台版本检查取错字段 → 判断永不触发 | §4.7 / §6.3（PLAT-2 修订） / §6.6 第一步 | `_check_platform_version()` Windows 段：`platform.win32_ver()[0]`（NT 版本 "10"/"11"），fallback 到 `platform.release()`；PLAT-2 UT mock win32_ver() 返 ("10", hostname, build) 断言触发 |
| **P1-3** | build_macos.sh lipo 合并只合并二进制，.app bundle 结构不完整 | §4.10.3 / §5.4 / §6.3（BUILD-3 修订） / §6.6 第四步 | macOS lipo 合并改为 `cp -R dist/snake-gui-arm64.app dist/snake-gui.app` + `lipo -create -output dist/snake-gui.app/Contents/MacOS/snake-gui ...`；BUILD-3 UT 断言 Info.plist 存在 |
| **P1-4** | MDE 产物落盘位置错误（流程级） | §0 / §4.1 / §6.7 / 本附录 | 迭代 4 设计产物固定落 `workspace/snake-linux/design/game-app/`（与 modules.json `design.product` 一致）；r2 已落盘到正确路径；后续 spawn 指令不再有路径歧义 |
| **P2-1** | certutil SHA256 输出格式与 §6.3 断言标准不符 | §4.10.2 / §6.3（SHA-1 修订） / §6.6 第四步 | build_windows.bat 不再生成 SHA256SUMS（r2 修订 P2-2）；SHA-1 UT 放宽为"含 64-hex 即过" |
| **P2-2** | 三平台构建脚本各自生成 SHA256SUMS + gen_sha256sums.sh 又生成一次 → 职责重复且文件名冲突 | §4.10.1/2/3 / §4.10.4 / §5.3 / §6.6 第四步 | 构建脚本（build_linux.sh / build_windows.bat / build_macos.sh）只产包不产校验和；SHA256SUMS 仅由 `scripts/gen_sha256sums.sh` 统一生成 |
| **P2-3** | 下载链接为 `https://example.com/...` 占位符 | §4.12 / §4.13 | USER_GUIDE.md §1.1 + RELEASE_NOTES.md §4 加注"r2 修订：发布占位，发布时替换为真实下载地址" |
| **P2-4** | §3.4 App docstring 声称 `_on_bench_complete` 钩子但 §4.11.1 未实现 | §3.4 / §4.11.1 / §4.11.2 / §6.6 第三步 | 删除 docstring 中 `_on_bench_complete` 声明；bench_fps.py / bench_memory.py 直接调 `_init_pygame / _new_game / _tick / _render` |
| **P2-5** | §6.5 UT 运行命令不读 pytest.ini pythonpath | §6.5 | UT 运行命令改为 `pytest tests/test_game_app -v --cov=game_app --cov-branch --cov-fail-under=90` |
| **P2-6** | iter-3 既有 UT 若断言 StorageUnavailableError → exit 1 需同步修改 | §3.6 / §6.7 | 新增 §6.7 FO 修订清单；列出 `test_app_iter3_storage.py` / `test_app_iter3_dispatch.py` 中相关用例的修订前后断言 |

---

## 附录 E：已知 issue（iter-4 增量，不阻塞 SE）

- **issue-004（PyInstaller 交叉打包，**新增**）**：PyInstaller 不支持交叉打包，三平台需在对应原生系统构建——需 CI 三平台矩阵（GitHub Actions runner 三平台）支持，iter-4 仅产出构建脚本，CI 集成留 v2.0.1+。
- **issue-005（macOS 公证，**新增**）**：未签名的 .app 在 macOS Gatekeeper 触发警告——需 Apple Developer ID 证书 + `codesign` + `notarytool`，iter-4 在 USER_GUIDE.md §7 明确告知用户手动确认，签名留 v2.0.1+。
- **issue-006（Windows SmartScreen，**新增**）**：未签名的 .exe 在 Windows SmartScreen 触发警告——需代码签名证书（EV 证书或普通证书），iter-4 在 USER_GUIDE.md §7 明确告知用户手动确认，签名留 v2.0.1+。
- **issue-007（内置字体 license，**新增**）**：打包内置 `SourceHanSansCN-Regular.otf`（或同源字体）需确认 OFL / Apache 2.0 等开源协议兼容性——iter-4 优先选择 OFL 协议字体（Source Han Sans、Noto Sans CJK 等），确认 license 后再打包。
- **issue-008（r2 新增：设计产物路径，**新增**）**：r1 设计产物误落 `zteam/snake-linux/design/game-app/`，与 modules.json `design.product = "snake-linux/design/game-app/"` 不一致；r2 已迁移至 `workspace/snake-linux/design/game-app/` 并在 §0 §P1-4 固化。

---

## 附录 F：依赖契约实核（对照锁定代码）

| 设计引用 | 实核结果（基于 `code/gui-renderer/iter-3/gui_renderer/` + `code/game-core/iter-2/game_core/` + `code/platform-storage/iter-2/platform_storage/`） |
|----------|----------|
| `Renderer((W,H), *, skin=None, vsync=True, cell_size=..., grid_cols=..., grid_rows=..., enable_high_dpi=True)` 构造 | ✅ `renderer.py` 第 118-148 行签名一致；iter-4 沿用 |
| `init()` 建屏（`pygame.SCALED` + `pygame.RESIZABLE` 标志） | ✅ `renderer.py` 第 205-225 行；flags 含 `getattr(pygame, "SCALED", 0)` + `getattr(pygame, "RESIZABLE", 0)`（iter-3 r2-2 契约前置已落实） |
| `handle_resize(w, h)` 重 set_mode 保留 `SCALED` + `RESIZABLE` 标志 | ✅ `renderer.py` 第 255-290 行；iter-4 沿用 |
| `render(snap, hud, *, interp=None)` | ✅ `renderer.py` 第 303+ 行；iter-4 沿用 |
| `set_skin(name)` 不在 SKIN_REGISTRY 抛 SkinNotFoundError | ✅ `renderer.py` 第 241-253 行；iter-4 沿用 |
| `handle_resize(w, h)` < MIN_PLAYABLE_W/H 抛 RenderError | ✅ `renderer.py` 第 255-290 行；iter-4 沿用 + G4-2 HiDPI 降级包装 |
| `skin_names()` / `current_skin_name` / `fps_metric()` | ✅ `renderer.py` 第 195-203 行；iter-4 沿用（G4-3 性能脚本调用 `fps_metric()`） |
| `InterpolationState(alpha, prev_snake_body, prev_food=None)` | ✅ `types.py` 第 101-114 行；iter-4 沿用 |
| `SKIN_REGISTRY` 3 套皮肤 | ✅ `constants.py` 第 90-95 行；iter-4 沿用 |
| `HudData(score, high_score, length, difficulty_label, status_label)` 5 字段 | ✅ `types.py` 第 60-69 行；iter-4 沿用 |
| `Snapshot(snake_body, food, score, length, status, difficulty, tick_ms)` 7 字段 | ✅ `code/game-core/iter-2/game_core/state.py`；iter-4 沿用 |
| `GameState(width, height, difficulty, rng=Random())` 构造（全关键字） | ✅ `code/game-core/iter-2/game_core/state.py`；iter-4 沿用 |
| `set_direction` / `step` / `toggle_pause` / `snapshot` / `set_score_callback` | ✅ `code/game-core/iter-2/game_core/state.py`；iter-4 沿用 |
| `Difficulty` (EASY/MEDIUM/HARD) + base_tick_ms (250/160/100) | ✅ `code/game-core/iter-2/game_core/difficulty.py`；iter-4 沿用 |
| `GameStatus` (RUN/PAUSED/OVER) | ✅ `code/game-core/iter-2/game_core/types.py`；iter-4 沿用 |
| `get_user_data_dir()` 三平台定位 | ✅ `code/platform-storage/iter-2/platform_storage/dirs.py`；iter-4 沿用 |
| `HighScoreStore(path)` + `load/save/reset` 原子写 | ✅ `code/platform-storage/iter-2/platform_storage/highscore.py`；iter-4 沿用 + G4-2 抛 OSError → StorageUnavailableError |

---

> **本修订版（r2）提交 SE 复审前自查**：
> - [x] **P0-1**：spec pathex 补三依赖包路径，BUILD-1 加"产物可启动"断言
> - [x] **P0-2**：`get_bundled_font_path` 与 datas 目标目录统一（`fonts/` 子目录），FONT-6 UT 断言一致
> - [x] **P0-3**：`error_to_exit_code` 精确子类优先，ERR-6 UT 断言相符
> - [x] **P0-4**：bench 脚本 sys.path 补全 + `game_app.perf` 导入修正，PERF-6 UT 断言可导入
> - [x] **P1-1**：主循环 StorageUnavailableError → 退出码 3（score_callback / dispatch_menu 路径均覆盖），错误矩阵 §5.6 一致
> - [x] **P1-2**：Windows 版本取 `win32_ver()[0]` 或 `platform.release()`，PLAT-2 UT 断言可达
> - [x] **P1-3**：macOS lipo 以 arm64 完整 .app 为基础替换二进制，BUILD-3 UT 断言 bundle 结构完整
> - [x] **P1-4**：设计产物迁移至 `workspace/snake-linux/design/game-app/`（r2 已落盘），§0 §4.1 固化
> - [x] **P2-1**：certutil SHA256 输出兼容（构建脚本不生成 SHA256SUMS，SHA-1 UT 放宽）
> - [x] **P2-2**：SHA256SUMS 仅 `gen_sha256sums.sh` 统一生成
> - [x] **P2-3**：USER_GUIDE / RELEASE_NOTES 下载链接标注"发布占位"
> - [x] **P2-4**：删除 `_on_bench_complete` 钩子声明，bench 脚本直调 App 内部接口
> - [x] **P2-5**：UT 运行命令改为 pytest
> - [x] **P2-6**：iter-3 既有 UT 同步修订清单 §6.7
> - [x] **G4-1**：三平台 PyInstaller 打包矩阵（spec + scripts + 内置字体 + SHA256SUMS）
> - [x] **G4-2**：错误提示完善（退出码 3 + suggestion 字段 + 3 类非致命警告 + HiDPI 降级 + 精确子类优先映射）
> - [x] **G4-3**：性能 profile 脚本（perf.py 常量 + bench_fps.py + bench_memory.py；r2 sys.path 完整）
> - [x] **G4-4**：USER_GUIDE.md 五节齐全（下载运行/键位表/难度/皮肤/暂停/平台差异/已知限制；r2 下载链接标注）
> - [x] **G4-5**：打包内置字体（SourceHanSansCN-Regular.otf + get_bundled_font_path；r2 fonts/ 子目录与 spec datas 一致）
> - [x] **G4-6**：RELEASE_NOTES.md（v2.0.0 changelog；r2 下载链接标注）
> - [x] **G4-7**：回归全模块（iter-4 UT 覆盖错误路径 + 打包脚本 + 用户指南 + 性能脚本）
> - [x] 依赖契约逐条实核通过（基于锁定代码，r2-2 契约前置已落实）
> - [x] 沿用 iter-1/2/3 全部修订（R3-1/2/4/5/7/8/9/10/11/12/14/15 + G2-1~7 + G3-1/2/3/4/5 + r2-1/2/3/4/5/6/7）
> - [x] iter-4 不新建 iter-4 代码目录（同 v2.0.0 一个发布单元）