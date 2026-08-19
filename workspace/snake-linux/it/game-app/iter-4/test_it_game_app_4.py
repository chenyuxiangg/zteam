"""模块 IT 测试：game-app（snake-linux v2.0.0 迭代 4）。

按 `snake-linux/it/game-app/iter-4/测试用例.md` 落地，pytest 9.x。

定位：与 FO UT（186 用例，全 fake/mock 单方法白盒）互补的**真实集成测试**——
真实 pygame（SDL dummy 驱动）+ 真实 game-core / gui-renderer / platform-storage
依赖模块装配 + 真实子进程（退出码/stderr/退出卫生）+ 性能脚本真实执行 +
打包资产一致性 + 跨迭代回归锚点。

覆盖 FR-14/15/16 + NFR-01/02/03/07（G4-1~G4-7）+ 回归 FR-01~13。

执行：
  cd /home/zyzs/cyx/zteam
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  PYTHONPATH=workspace/snake-linux/code/game-core/iter-2:workspace/snake-linux/code/gui-renderer/iter-3:workspace/snake-linux/code/platform-storage/iter-2:workspace/snake-linux/code/game-app/iter-4 \
  python3 -m pytest workspace/snake-linux/it/game-app/iter-4/test_it_game_app_4.py -v --tb=short \
    --junitxml=workspace/snake-linux/it/game-app/iter-4/it-report.xml
"""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---- SDL dummy 必须在 pygame import 前设置（headless CI 兼容） ----
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# ---- 被测代码路径注入（数据层 code 目录） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/game-app/iter-4 -> snake-linux
_CODE_CORE = _WORKSPACE / "code" / "game-core" / "iter-2"
_CODE_RENDERER = _WORKSPACE / "code" / "gui-renderer" / "iter-3"
_CODE_STORAGE = _WORKSPACE / "code" / "platform-storage" / "iter-2"
_CODE_APP = _WORKSPACE / "code" / "game-app" / "iter-4"
_ASSET_ROOT = Path("/home/zyzs/cyx/zteam/snake-linux")  # 资产层（spec/scripts/release 权威目录）

for _p in (str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_STORAGE), str(_CODE_APP)):
    sys.path.insert(0, _p)

import pygame  # noqa: E402

from game_app import App, AppConfig, AppConfigV3, AppScreen, InputAction  # noqa: E402
from game_app import app as app_mod  # noqa: E402
from game_app import storage as storage_mod  # noqa: E402
from game_app._constants import BUNDLED_FONT_FILENAME, get_bundled_font_path  # noqa: E402
from game_app.errors import (  # noqa: E402
    CJKFontFallbackWarning,
    ConfigError,
    GraphicsUnavailableError,
    HighDPIWarning,
    PlatformUnsupportedWarning,
    StorageUnavailableError,
    error_to_exit_code,
)
from game_app.fonts import _load_cjk_font  # noqa: E402
from game_app.perf import (  # noqa: E402
    MEMORY_PEAK_MB_MAX,
    P95_FRAME_TIME_MS_MAX,
    TARGET_FPS,
    TICK_MS_HARD_MAX_RATIO,
)
from game_core import Difficulty, Direction, GameStatus  # noqa: E402
from gui_renderer import MIN_PLAYABLE_H, MIN_PLAYABLE_W, Renderer  # noqa: E402
from platform_storage import HighScoreStore  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "p0: 发布阻塞级")
    config.addinivalue_line("markers", "p1: 重要边界")
    config.addinivalue_line("markers", "p2: 体验增强")


# ============================================================
# 公共设施：真实装配 fixture + 子进程 runner
# ============================================================

@pytest.fixture
def app_real(tmp_path):
    """真实装配：真实 Renderer（SDL dummy）+ 真实 HighScoreStore(tmp 隔离)。

    注入 _storage 后 _init_pygame 跳过 create_storage（不触碰真实用户目录）；
    Renderer 用真实 gui_renderer 实现（dummy 驱动创建离屏 surface）。
    """
    a = App(AppConfigV3(enable_high_dpi=False))
    a._storage = HighScoreStore(tmp_path / "highscore.json")
    a._init_pygame()
    return a


def _child_env(tmp_path, extra=None) -> dict:
    """子进程环境：PYTHONPATH 四 code 目录 + SDL dummy + XDG 隔离。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_STORAGE), str(_CODE_APP)]
    )
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    env["HOME"] = str(tmp_path / "home")
    if extra:
        env.update(extra)
    return env


def _run_py(code: str, env: dict, timeout: int = 60, cwd_override: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(cwd_override if cwd_override is not None else _WORKSPACE),
    )


# ============================================================
# A. 真实装配与渲染闭环
# ============================================================

class TestRealAssembly:
    """IT-game-app-4-01：真实装配（SDL dummy 真实 Renderer + 真实 storage）。"""

    @pytest.mark.p0
    def test_04_01_real_assembly(self, tmp_path):
        from game_app import App as RealApp

        a = RealApp(AppConfigV3(enable_high_dpi=True))
        # 构造无副作用（R3-10）
        assert a._renderer is None
        assert a.game_state is None
        assert pygame.get_init() is False
        # 真实装配
        a._storage = HighScoreStore(tmp_path / "hs.json")
        a._init_pygame()
        assert isinstance(a._renderer, Renderer), "必须用真实 Renderer"
        assert a._renderer._screen is not None, "Renderer.init() 已执行"
        assert isinstance(a._storage, HighScoreStore)
        assert a._high_score == a._storage.load(), "INV-12 _high_score 与 storage.load 一致"
        assert a._hidpi_degraded is False, "dummy 驱动下 SCALED 可用，不应降级"
        # 关闭 HiDPI 的构造路径也成功
        b = RealApp(AppConfigV3(enable_high_dpi=False))
        b._storage = HighScoreStore(tmp_path / "hs2.json")
        b._init_pygame()
        assert isinstance(b._renderer, Renderer)


class TestRealRenderLoop:
    """IT-game-app-4-02：真实渲染闭环（三态真实绘制不抛异常）。"""

    @pytest.mark.p0
    def test_04_02_render_loop_three_states(self, app_real):
        a = app_real
        a._difficulty = Difficulty.MEDIUM
        a._new_game(Difficulty.MEDIUM)
        assert a.screen == AppScreen.PLAYING
        snap = a.game_state.snapshot()
        assert snap.tick_ms == Difficulty.MEDIUM.base_tick_ms
        # PLAYING 真实绘制（30 帧，无异常）
        for _ in range(30):
            a._tick(16)
            a._render()
        # PAUSED 真实绘制
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PAUSED
        a._render()
        # 恢复 PLAYING 绘制
        a._dispatch_paused(InputAction.TOGGLE_PAUSE)
        a._render()
        # GAME_OVER 真实绘制（app 自绘）
        a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
        a.screen = AppScreen.GAME_OVER
        a._render()


class TestRealEventLoop:
    """IT-game-app-4-03：真实事件驱动主循环（QUIT → run() 返 0）。"""

    @pytest.mark.p0
    def test_04_03_quit_event_returns_0(self, tmp_path):
        a = App(AppConfigV3(enable_high_dpi=False))
        a._storage = HighScoreStore(tmp_path / "hs.json")
        a._init_pygame()
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        rc = a.run()
        assert rc == 0, "QUIT 后主循环正常退出码 0"
        assert pygame.display.get_init() is False, "INV-5 shutdown 已执行"


class TestRealStorageIntegration:
    """IT-game-app-4-04：真实存储集成（INV-12/13，真实 IO）。"""

    @pytest.mark.p0
    def test_04_04_score_persist_roundtrip(self, tmp_path, monkeypatch):
        hs_file = tmp_path / "highscore.json"

        # 走完整真实路径：monkeypatch create_storage 返回真实 HighScoreStore(hs_file)
        # （不注入 _storage——注入会跳过 _init_pygame 的 load()，重启加载路径无法验证）
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: HighScoreStore(hs_file))

        # 第一个 App：空文件 load=0
        a = App(AppConfigV3(enable_high_dpi=False))
        a._init_pygame()
        assert a._high_score == 0

        # 新局注册回调 → 触发得分 → 真实落盘
        a._new_game(Difficulty.MEDIUM)
        assert a.game_state._score_callback is not None
        a.game_state._score_callback(50)
        assert a._high_score == 50, "INV-13 直接写实例字段"
        assert hs_file.exists(), "真实落盘"
        assert json_load(hs_file)["high_score"] == 50, "真实落盘内容（schema high_score 字段）"

        # 得分不降（max 语义）
        a.game_state._score_callback(30)
        assert a._high_score == 50
        assert json_load(hs_file)["high_score"] == 50

        # 第二个 App（重启）：load() 走真实文件 → 加载一致（INV-12）
        b = App(AppConfigV3(enable_high_dpi=False))
        b._init_pygame()
        assert b._high_score == 50, "重启最高分保留（FR-13）"

        # 重置归零（platform-storage 契约：reset 删除文件 + 缓存归 0）
        b._dispatch_menu(InputAction.RESET_HIGHSCORE)
        assert b._high_score == 0
        assert not hs_file.exists(), "reset 删除文件（platform-storage 契约）"


def json_load(p: Path):
    import json
    return json.loads(p.read_text(encoding="utf-8"))


# ============================================================
# B. 进程级错误路径（NFR-03 / IT-app-4-01/02）
# ============================================================

class TestProcessExitCodes:
    """进程级退出码与 stderr 可读性（真实子进程）。"""

    @pytest.mark.p0
    def test_04_05_exit_code_0(self, tmp_path):
        """python -m game_app 注入 QUIT → 退出码 0。"""
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 0, f"退出码应 0，实际 {r.returncode}\nstderr={r.stderr}"

    @pytest.mark.p0
    def test_04_06_exit_code_2_graphics_unavailable(self, tmp_path):
        """SDL 图形环境不可用 → 退出码 2 + 人类可读 stderr。"""
        code = (
            "from game_app import main; import sys\n"
            "sys.exit(main())"
        )
        # 强制 SDL 无可用视频驱动（非 dummy，指向非法驱动）
        r = _run_py(code, _child_env(tmp_path, {"SDL_VIDEODRIVER": "invalid_driver_xyz"}))
        assert r.returncode == 2, (
            f"图形环境不可用应退出码 2，实际 {r.returncode}\nstderr={r.stderr}"
        )
        assert "[错误]" in r.stderr and "建议" in r.stderr, (
            f"stderr 应含可读提示（NFR-03）: {r.stderr}"
        )

    @pytest.mark.p0
    def test_04_07_exit_code_3_storage_unavailable(self, tmp_path):
        """create_storage 抛 OSError → 退出码 3（G4-2 新增）+ stderr 提示。

        注意：app.py 用 `from .storage import create_storage` 绑定名字，
        必须 patch `game_app.app.create_storage`（模块属性 patch 无效）。
        """
        code = (
            "import game_app.app as app_mod\n"
            "def boom(*a, **kw):\n"
            "    raise OSError('permission denied')\n"
            "app_mod.create_storage = boom\n"
            "from game_app import main; import sys\n"
            "sys.exit(main())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 3, (
            f"存储不可用应退出码 3，实际 {r.returncode}\nstderr={r.stderr}"
        )
        assert "用户数据目录不可写" in r.stderr and "建议" in r.stderr, (
            f"stderr 应含存储建议（NFR-03/G4-2）: {r.stderr}"
        )

    @pytest.mark.p0
    def test_04_08_no_bare_traceback(self, tmp_path):
        """两类错误路径 stderr 均无裸 Traceback（NFR-03 最小集）。"""
        code_main = "from game_app import main; import sys; sys.exit(main())"
        r1 = _run_py(code_main, _child_env(tmp_path, {"SDL_VIDEODRIVER": "invalid_driver_xyz"}))
        r2 = _run_py(
            "import game_app.app as app_mod\n"
            "def boom(*a, **kw): raise OSError('denied')\n"
            "app_mod.create_storage = boom\n"
            "from game_app import main; import sys; sys.exit(main())",
            _child_env(tmp_path),
        )
        for r in (r1, r2):
            assert "Traceback" not in r.stderr, f"不应有裸 traceback: {r.stderr}"
            assert "File \"" not in r.stderr, f"不应泄露堆栈: {r.stderr}"

    @pytest.mark.p0
    def test_04_09_exit_hygiene(self, tmp_path):
        """退出 1 秒内结束 + 无残留进程（IT-app-4-02）。"""
        import time
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        t0 = time.monotonic()
        r = _run_py(code, _child_env(tmp_path))
        elapsed = time.monotonic() - t0
        assert r.returncode == 0
        assert elapsed < 1.0, f"退出应 1 秒内，实际 {elapsed:.2f}s"
        # 无残留进程：ps 中无 game_app 相关子进程
        ps = subprocess.run(
            ["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=30
        ).stdout
        leftovers = [
            ln for ln in ps.splitlines()
            if "game_app" in ln and "test_it_game_app" not in ln and "grep" not in ln
        ]
        assert not leftovers, f"存在残留进程: {leftovers}"


# ============================================================
# C. 错误/降级/字体真实模块路径
# ============================================================

class TestFontAndFallback:
    """IT-game-app-4-10：内置字体真实路径（G4-5/INV-20）。"""

    @pytest.mark.p1
    def test_04_10_bundled_font_real(self, app_real):
        path = get_bundled_font_path()
        assert path, "内置字体路径应非空"
        assert os.path.isfile(path), "字体文件应实存"
        assert path.endswith(f"fonts/{BUNDLED_FONT_FILENAME}"), (
            f"应命中 fonts/ 子目录（r2 F-2 修订）: {path}"
        )
        font = _load_cjk_font(22)
        assert isinstance(font, pygame.font.Font), "真实加载成功"
        assert app_real._cjk_font_fallback is False, "INV-19 内置字体命中，未回退"


class TestHidpiFallbackReal:
    """IT-game-app-4-11：HiDPI 降级真实包装（G4-2/INV-18）。"""

    @pytest.mark.p1
    def test_04_11_hidpi_fallback_real_renderer(self, monkeypatch, tmp_path):
        import gui_renderer.renderer as renderer_mod

        orig_init = renderer_mod.Renderer.init
        calls = []

        def fake_init(self):
            calls.append(1)
            if len(calls) == 1:
                raise pygame.error("SCALED unsupported")
            return orig_init(self)

        monkeypatch.setattr(renderer_mod.Renderer, "init", fake_init)

        a = App(AppConfigV3(enable_high_dpi=True))
        a._storage = HighScoreStore(tmp_path / "hs.json")
        with pytest.warns(HighDPIWarning):
            a._init_pygame()
        assert len(calls) == 2, "第一次失败 + 第二次降级成功"
        assert isinstance(a._renderer, Renderer), "降级后仍是真实 Renderer"
        assert a._hidpi_degraded is True, "INV-18 降级标志"


class TestPlatformCheckReal:
    """IT-game-app-4-12：平台检查真实函数（G4-2，F-3 修订）。"""

    @pytest.mark.p1
    def test_04_12_platform_check(self, monkeypatch):
        import platform as platform_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Darwin")
        monkeypatch.setattr(platform_mod, "mac_ver", lambda: ("11.5.2", ("", "", ""), ""))
        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

        monkeypatch.setattr(platform_mod, "system", lambda: "Windows")
        monkeypatch.setattr(platform_mod, "win32_ver", lambda: ("8.1", "", "", ""))
        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

        # 空版本号兜底（F-3 修订）
        monkeypatch.setattr(platform_mod, "win32_ver", lambda: ("", "", "", ""))
        monkeypatch.setattr(platform_mod, "release", lambda: "6.1")
        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

        monkeypatch.setattr(platform_mod, "system", lambda: "Linux")
        # Linux 不检查：不应触发任何警告
        with warnings_capture() as wlist:
            app_mod._check_platform_version()
        assert not any(issubclass(w.category, PlatformUnsupportedWarning) for w in wlist)


import warnings as _warnings_mod  # noqa: E402


def warnings_capture():
    import contextlib

    @contextlib.contextmanager
    def _cap():
        with _warnings_mod.catch_warnings(record=True) as wlist:
            _warnings_mod.simplefilter("always")
            yield wlist
    return _cap()


class TestErrorMappingReal:
    """IT-game-app-4-13：错误映射与 suggestion 真实生效（G4-2/INV-17）。"""

    @pytest.mark.p1
    def test_04_13_error_mapping_and_suggestion(self):
        assert error_to_exit_code(ConfigError("bad")) == 1
        assert error_to_exit_code(GraphicsUnavailableError("no display")) == 2
        assert error_to_exit_code(StorageUnavailableError("no write")) == 3
        assert error_to_exit_code(ValueError("x")) == 1

        e1 = GraphicsUnavailableError("SDL2 missing", suggestion="请安装 libsdl2-dev")
        assert e1.suggestion == "请安装 libsdl2-dev"
        e2 = StorageUnavailableError("disk full", suggestion="清理磁盘空间")
        assert e2.suggestion == "清理磁盘空间"
        assert GraphicsUnavailableError("m").suggestion == ""
        assert StorageUnavailableError("m").suggestion == ""

    @pytest.mark.p1
    def test_04_13b_run_returns_3_real_error_object(self, monkeypatch, tmp_path):
        """run() 在 _init_pygame 抛真实 StorageUnavailableError 时返 3。"""
        a = App(AppConfigV3(enable_high_dpi=False))
        a._storage = HighScoreStore(tmp_path / "hs.json")

        def boom_init(self):
            raise StorageUnavailableError("用户数据目录不可写", suggestion="检查权限")

        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)
        assert a.run() == 3


# ============================================================
# D. 性能脚本真实执行（NFR-01/02）
# ============================================================

class TestBenchScriptsReal:
    """bench 脚本真实执行（进程级冒烟，G4-3）。"""

    @pytest.mark.p0
    def test_04_14_bench_fps_real_run(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(_ASSET_ROOT / "scripts" / "bench_fps.py"),
             "--duration", "2", "--difficulty", "medium"],
            capture_output=True, text=True, timeout=120,
            env=_child_env(tmp_path), cwd=str(_ASSET_ROOT),
        )
        assert r.returncode in (0, 1), (
            f"bench_fps 应可跑通（PASS=0/FAIL=1），实际 {r.returncode}\nstderr={r.stderr}"
        )
        for token in ("平均 FPS", "P95 帧时间", "NFR-01 评估:"):
            assert token in r.stdout, f"stdout 缺 {token}: {r.stdout}"
        assert re.search(r"NFR-01 评估: (PASS|FAIL)", r.stdout), f"判定输出缺失: {r.stdout}"

    @pytest.mark.p1
    def test_04_15_bench_memory_real_run(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(_ASSET_ROOT / "scripts" / "bench_memory.py"),
             "--duration", "2"],
            capture_output=True, text=True, timeout=120,
            env=_child_env(tmp_path), cwd=str(_ASSET_ROOT),
        )
        assert r.returncode in (0, 1), (
            f"bench_memory 应可跑通，实际 {r.returncode}\nstderr={r.stderr}"
        )
        for token in ("内存峰值", "NFR-02 评估:"):
            assert token in r.stdout, f"stdout 缺 {token}: {r.stdout}"
        assert re.search(r"NFR-02 评估: (PASS|FAIL)", r.stdout), f"判定输出缺失: {r.stdout}"


class TestPerfConstantContract:
    """IT-game-app-4-16：性能常量 × 难度参数表一致性（跨模块契约）。"""

    @pytest.mark.p1
    def test_04_16_perf_and_difficulty_consistent(self):
        ticks = {
            Difficulty.EASY: Difficulty.EASY.base_tick_ms,
            Difficulty.MEDIUM: Difficulty.MEDIUM.base_tick_ms,
            Difficulty.HARD: Difficulty.HARD.base_tick_ms,
        }
        assert ticks == {Difficulty.EASY: 250, Difficulty.MEDIUM: 160, Difficulty.HARD: 100}, (
            f"难度参数表: {ticks}"
        )
        assert ticks[Difficulty.HARD] <= ticks[Difficulty.EASY] * TICK_MS_HARD_MAX_RATIO, (
            "NFR-01 困难档 ≤ 简单档 50%（档位可感知差异）"
        )
        assert TARGET_FPS == 60
        assert P95_FRAME_TIME_MS_MAX == 25.0
        assert MEMORY_PEAK_MB_MAX == 300
        assert 1000.0 / TARGET_FPS <= P95_FRAME_TIME_MS_MAX, "P95 上限 ≥ 单帧预算（自洽）"


# ============================================================
# E. 打包资产一致性（G4-1/G4-4/G4-6/NFR-07）
# ============================================================

class TestPackagingAssets:
    """IT-game-app-4-17：打包资产齐备（spec 关键项 + 探测逻辑 F-1 回归）。"""

    @pytest.mark.p0
    def test_04_17_spec_and_build_assets(self):
        spec = _ASSET_ROOT / "spec" / "snake-gui.spec"
        assert spec.exists(), "spec 应实存"
        text = spec.read_text(encoding="utf-8")
        assert "snake-gui" in text, "EXE name"
        assert "SourceHanSansCN-Regular.otf" in text, "datas 字体（G4-5）"
        assert "collect_submodules" in text, "hiddenimports 收集"
        for pkg in ("game_app", "platform_storage", "gui_renderer"):
            assert pkg in text, f"hiddenimports 含 {pkg}"
        for script in (
            "build_linux.sh", "build_windows.bat", "build_macos.sh", "gen_sha256sums.sh",
        ):
            assert (_ASSET_ROOT / "scripts" / script).exists(), f"脚本 {script} 应实存"

    @pytest.mark.p0
    def test_04_17b_spec_probe_hits_real_dir(self):
        """F-1 回归：模拟 SPECPATH 探测，GAME_APP_DIR 必须命中含 __main__.py 的真实目录。"""
        spec_dir = _ASSET_ROOT / "spec"
        specpath = str(spec_dir)
        candidates = [
            os.path.join(specpath, "..", "code", "game-app", "iter-4", "game_app"),
            os.path.join(specpath, "..", "code", "game-app", "iter-3", "game_app"),
            os.path.join(specpath, "..", "..", "workspace", "snake-linux", "code", "game-app", "iter-4", "game_app"),
            os.path.join(specpath, "..", "..", "workspace", "snake-linux", "code", "game-app", "iter-3", "game_app"),
        ]
        hit = None
        for c in candidates:
            if os.path.isfile(os.path.join(c, "__main__.py")):
                hit = os.path.abspath(c)
                break
        assert hit is not None, "探测必须命中真实代码目录"
        assert os.path.isfile(os.path.join(hit, "__main__.py")), "入口 __main__.py 实存"
        font = os.path.join(hit, "fonts", "SourceHanSansCN-Regular.otf")
        assert os.path.isfile(font), f"datas 字体随 GAME_APP_DIR 解析: {font}"


class TestBuildScripts:
    """IT-game-app-4-18：构建脚本语法检查（G4-1）。"""

    @pytest.mark.p1
    def test_04_18_bash_syntax(self):
        for script in ("build_linux.sh", "build_macos.sh", "gen_sha256sums.sh"):
            p = _ASSET_ROOT / "scripts" / script
            assert p.exists()
            r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True, timeout=30)
            assert r.returncode == 0, f"{script} bash -n 语法错误: {r.stderr}"
        bat = _ASSET_ROOT / "scripts" / "build_windows.bat"
        assert bat.exists()
        text = bat.read_text(encoding="utf-8", errors="replace")
        assert "pyinstaller" in text.lower(), "bat 应含 pyinstaller 调用"


class TestReleaseDocs:
    """IT-game-app-4-19：发布物文档齐备（FR-16/G4-4/G4-6/NFR-07）。"""

    @pytest.mark.p1
    def test_04_19_release_docs(self):
        release = _ASSET_ROOT / "release"
        guide = (release / "USER_GUIDE.md").read_text(encoding="utf-8")
        for sec in ("下载与运行", "键位表", "难度", "皮肤", "暂停", "平台差异", "已知限制"):
            assert sec in guide, f"USER_GUIDE 缺小节: {sec}"
        for plat in ("Linux", "Windows", "macOS"):
            assert plat in guide, f"USER_GUIDE 缺平台: {plat}"

        notes = (release / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        assert "v2.0.0" in notes
        for feat in ("难度", "暂停", "最高分", "皮肤", "三平台"):
            assert feat in notes, f"RELEASE_NOTES 缺功能: {feat}"

        sums = (release / "SHA256SUMS").read_text(encoding="utf-8")
        pattern = re.compile(r"^[0-9a-f]{64}\s{2}\S+$")
        lines = [ln for ln in sums.splitlines() if ln.strip()]
        assert lines, "SHA256SUMS 非空"
        import hashlib
        for ln in lines:
            assert pattern.match(ln), f"SHA256SUMS 行格式非法: {ln}"
            digest, _, rel = ln.partition("  ")
            target = release / rel
            if target.exists():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                assert actual == digest, f"{rel} 哈希不匹配"


class TestBundledFontAsset:
    """IT-game-app-4-20：内置字体交付（G4-5）。"""

    @pytest.mark.p1
    def test_04_20_font_file_real(self):
        font_file = _CODE_APP / "game_app" / "fonts" / BUNDLED_FONT_FILENAME
        assert font_file.exists(), "字体文件实存"
        assert font_file.stat().st_size > 1_000_000, f"真实字体（>1MB），实际 {font_file.stat().st_size}"
        f = pygame.font.Font(str(font_file), 22)
        assert isinstance(f, pygame.font.Font), "字体可被 pygame 加载"
        assert BUNDLED_FONT_FILENAME == "SourceHanSansCN-Regular.otf"


# ============================================================
# F. 跨迭代回归（整体测试方案 §3.2 回归锚点）
# ============================================================

class TestRegressionCoreContract:
    """IT-game-app-4-21：真实 GameState 契约经 app 装配（回归锚点 1）。"""

    @pytest.mark.p0
    def test_04_21_game_state_contract(self, app_real):
        for diff in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            a = app_real
            a._difficulty = diff
            a._new_game(diff)
            snap = a.game_state.snapshot()
            # 快照 7 字段
            for field in ("snake_body", "food", "score", "length", "status", "difficulty", "tick_ms"):
                assert hasattr(snap, field), f"snapshot 缺字段 {field}"
            assert snap.status == GameStatus.RUN, "INV-1"
            assert snap.difficulty == diff, "INV-3"
            assert snap.tick_ms == diff.base_tick_ms, "难度参数表穿透 app"
        # 转向经 dispatch 透传（1 tick 内生效）
        a = app_real
        a._new_game(Difficulty.MEDIUM)
        before = a.game_state.snapshot().snake_body[0]
        a._dispatch_playing(InputAction.MOVE_DOWN)
        a._tick(Difficulty.MEDIUM.base_tick_ms)
        after = a.game_state.snapshot().snake_body[0]
        assert (after.x, after.y) != (before.x, before.y), "step 生效"


class TestRegressionRendererContract:
    """IT-game-app-4-22：真实 Renderer 皮肤/缩放契约经 app 调用链（回归锚点 2）。"""

    @pytest.mark.p0
    def test_04_22_skin_and_resize_real(self, app_real, capsys):
        a = app_real
        # 皮肤契约：3 套
        names = a._renderer.skin_names()
        assert set(names) == {"classic", "dark", "colorblind_friendly"}, f"3 套皮肤: {names}"
        assert a._renderer.current_skin_name == "classic"
        # app 调用链：MENU 态切皮肤
        a._switch_skin(InputAction.SET_SKIN_NEXT)
        assert a._renderer.current_skin_name == "dark", "真实 set_skin 生效（FR-10）"
        # 缩放契约：真实 VIDEORESIZE 事件 → handle_resize（FR-09）
        pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600))
        actions = a._drain_events()
        assert InputAction.RESIZE not in actions, "RESIZE 不入 dispatch"
        surface = pygame.display.get_surface()
        assert surface is not None and surface.get_size() == (800, 600), "真实 resize 生效"
        # 缩放兜底：< MIN_PLAYABLE → RenderError → stderr 提示 + 不抛（INV-15）
        a._handle_resize(pygame.event.Event(pygame.VIDEORESIZE, w=100, h=100))
        err = capsys.readouterr().err
        assert "窗口缩放失败" in err, f"RenderError 兜底 stderr: {err}"
        assert a.screen == AppScreen.MENU, "缩放失败不中断（INV-15）"


class TestRegressionIter2StateMachine:
    """IT-game-app-4-23：iter-2 状态机回归（真实 GameState）。"""

    @pytest.mark.p0
    def test_04_23_pause_state_machine_real(self, app_real, monkeypatch):
        a = app_real
        a._new_game(Difficulty.MEDIUM)
        # P 暂停：同步切屏（INV-11）
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PAUSED
        assert a.game_state.status == GameStatus.PAUSED, "INV-10"
        # PAUSED 态 MOVE 忽略
        a._dispatch_paused(InputAction.MOVE_LEFT)
        assert a.game_state.status == GameStatus.PAUSED
        # P 继续
        a._dispatch_paused(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state.status == GameStatus.RUN
        # 失焦自动暂停（G2-4）
        monkeypatch.setattr(app_mod.pygame.key, "get_focused", lambda: False)
        actions = a._drain_events()
        assert InputAction.UNFOCUS in actions, "失焦追加 UNFOCUS（仅 PLAYING 态）"
        a._dispatch_playing(InputAction.UNFOCUS)
        assert a.screen == AppScreen.PAUSED, "失焦自动暂停（G2-4）"


class TestRegressionIter1:
    """IT-game-app-4-24：iter-1 修订项回归。"""

    @pytest.mark.p1
    def test_04_24_iter1_regression(self, app_real, tmp_path):
        # 构造无副作用（R3-10）：在干净子进程中验证 App() 不 init pygame
        code = (
            "import pygame, sys\n"
            "from game_app import App\n"
            "a = App()\n"
            "print('renderer:', a._renderer is None)\n"
            "print('storage:', a._storage is None)\n"
            "print('game_state:', a.game_state is None)\n"
            "print('pygame_init:', pygame.get_init())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 0, f"子进程失败: {r.stderr}"
        assert "renderer: True" in r.stdout and "storage: True" in r.stdout
        assert "game_state: True" in r.stdout
        assert "pygame_init: False" in r.stdout, f"R3-10 构造不应 init pygame: {r.stdout}"
        # 屏态兜底（R3-1）：MENU 态未映射键 → START
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
        actions = app_real._drain_events()
        assert InputAction.START in actions, "R3-1 MENU 屏态兜底"
        # 死代码清理（R3-7）
        assert not hasattr(app_real, "_quit"), "R3-7 _quit 已删除"


class TestStaticChecks:
    """IT-game-app-4-25/26：静态检查（NFR-05/06）。"""

    @pytest.mark.p2
    def test_04_25_no_network_no_audio_imports(self):
        src_files = list((_CODE_APP / "game_app").glob("*.py"))
        assert src_files, "game_app 源码存在"
        combined = "\n".join(f.read_text(encoding="utf-8") for f in src_files)
        for banned in ("import socket", "import urllib", "import http", "import requests",
                       "pygame.mixer", "pygame.music"):
            assert banned not in combined, f"静态检查失败: 出现 {banned}"

    @pytest.mark.p2
    def test_04_26_runtime_no_network_modules(self, tmp_path):
        """运行期零网络依赖：被测四包源码不含网络 import（AST 级，含依赖包）。

        注：不断言 sys.modules——pygame 自身可能间接加载 socket/http/urllib
        （NFR-06 语义是"被测代码不 import 网络模块"，不是"运行环境无网络模块"）。
        """
        code = (
            "import ast, pathlib, sys\n"
            "pkgs = [\n"
            "    pathlib.Path('code/game-app/iter-4/game_app'),\n"
            "    pathlib.Path('code/game-core/iter-2/game_core'),\n"
            "    pathlib.Path('code/gui-renderer/iter-3/gui_renderer'),\n"
            "    pathlib.Path('code/platform-storage/iter-2/platform_storage'),\n"
            "]\n"
            "banned = ('socket', 'urllib', 'http', 'requests')\n"
            "violations = []\n"
            "for root in pkgs:\n"
            "    for f in root.glob('*.py'):\n"
            "        tree = ast.parse(f.read_text(encoding='utf-8'))\n"
            "        for node in ast.walk(tree):\n"
            "            if isinstance(node, ast.Import):\n"
            "                for a in node.names:\n"
            "                    if a.name.split('.')[0] in banned:\n"
            "                        violations.append(f'{f}:{node.lineno} import {a.name}')\n"
            "            elif isinstance(node, ast.ImportFrom):\n"
            "                if node.module and node.module.split('.')[0] in banned:\n"
            "                    violations.append(f'{f}:{node.lineno} from {node.module}')\n"
            "print('VIOLATIONS:' + repr(violations))"
        )
        r = _run_py(code, _child_env(tmp_path), cwd_override=_WORKSPACE)
        assert r.returncode == 0, f"子进程失败: {r.stderr}"
        assert "VIOLATIONS:[]" in r.stdout, f"被测代码不应 import 网络模块: {r.stdout}"
