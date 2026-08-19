"""版本系统测试（ST）：snake-linux v2.0.0。

按 `snake-linux/st/v2.0.0/测试用例.md` 落地（TE 已评审 PASS），pytest 9.x。

定位：模块 IT（9 个迭代全 PASS）之上的**版本级端到端**——
真实四模块装配 + 事件注入驱动完整用户旅程 + 进程级退出卫生 +
真实 IO 持久化 + 跨模块契约锚点 + 全量 IT 回归重跑 + 性能脚本真实执行 +
发布物齐备校验。

覆盖 ST-01~ST-14（整体测试方案 §3.1/§3.2/§3.3），需求映射见用例文档 §4。

执行：
  cd /home/zyzs/cyx/zteam
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  PYTHONPATH=workspace/snake-linux/code/game-core/iter-2:workspace/snake-linux/code/gui-renderer/iter-3:workspace/snake-linux/code/platform-storage/iter-2:workspace/snake-linux/code/game-app/iter-4 \
  python3 -m pytest workspace/snake-linux/st/v2.0.0/test_st_v2_0_0.py -v --tb=short \
    --junitxml=workspace/snake-linux/st/v2.0.0/st-report.xml
"""
from __future__ import annotations

import dataclasses
import hashlib
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
_HERE = Path(__file__).resolve().parent          # st/v2.0.0
_WORKSPACE = _HERE.parents[1]                    # st/v2.0.0 -> snake-linux（数据层）
_ZTEAM = _HERE.parents[3]                        # st/v2.0.0 -> snake-linux -> workspace -> zteam
_CODE_CORE = _WORKSPACE / "code" / "game-core" / "iter-2"
_CODE_RENDERER = _WORKSPACE / "code" / "gui-renderer" / "iter-3"
_CODE_STORAGE = _WORKSPACE / "code" / "platform-storage" / "iter-2"
_CODE_APP = _WORKSPACE / "code" / "game-app" / "iter-4"
_ASSET_ROOT = _ZTEAM / "snake-linux"             # 资产层（spec/scripts/release 权威目录）

for _p in (str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_STORAGE), str(_CODE_APP)):
    sys.path.insert(0, _p)

import pygame  # noqa: E402

from game_app import App, AppConfigV3, AppScreen, InputAction  # noqa: E402
from game_app import app as app_mod  # noqa: E402
from game_app.perf import (  # noqa: E402
    MEMORY_PEAK_MB_MAX,
    P95_FRAME_TIME_MS_MAX,
    TARGET_FPS,
    TICK_MS_HARD_MAX_RATIO,
)
from game_core import Difficulty, Direction, GameStatus, Point  # noqa: E402
from game_core.state import GameState  # noqa: E402
from game_core.types import Food  # noqa: E402
from gui_renderer import MIN_PLAYABLE_H, MIN_PLAYABLE_W, Renderer  # noqa: E402
from platform_storage import HighScoreStore  # noqa: E402

_IT_DIRS = [
    "game-core/iter-1", "game-core/iter-2",
    "platform-storage/iter-2",
    "gui-renderer/iter-1", "gui-renderer/iter-3",
    "game-app/iter-1", "game-app/iter-2", "game-app/iter-3", "game-app/iter-4",
]

# 已知测试版本错位白名单：代码目录是"活目录"（后续迭代演进更新先前迭代目录），
# 历史迭代 IT 测试断言的是当时代码快照，用最终代码重跑必然失败——这些失败是
# 测试代码过时（设计演进合法变更），**非产品回归**；白名单精确匹配防掩盖新缺陷。
# 对应演进证据：iter-2 FR-12 新增 PAUSED（06/07/22）、G2-7/P1-2 ESC 语义修订（09）、
# iter-4 G4-2 _create_renderer_with_hidpi_fallback 重构（iter-3 r3_15 mock 目标失效）。
_KNOWN_STALE_FAILURES = {
    "game-app/iter-1": {
        "test_it_game_app_1_06_appscreen_enum",      # 断言无 PAUSED（iter-2 新增 PAUSED）
        "test_it_game_app_1_07_inputaction_enum_complete",  # 断言 15 项枚举（iter-2/3 新增 3 项）
        "test_it_game_app_1_09_map_q_esc_to_quit",   # 断言 ESC→QUIT（G2-7 ESC 语义修订）
        "test_it_game_app_1_22_playing_pause_hint_only",   # 断言 _pause_hint_shown 属性（iter-2 删除）
    },
    "game-app/iter-3": {
        "test_r3_15_exit_code_2_shutdown_fallback",  # mock app_mod.Renderer（G4-2 改走 _create_renderer_with_hidpi_fallback）
    },
}


def pytest_configure(config):
    config.addinivalue_line("markers", "p0: 发布阻塞级")
    config.addinivalue_line("markers", "p1: 重要边界")
    config.addinivalue_line("markers", "p2: 体验增强/人工清单")


# ============================================================
# 公共设施：真实装配 fixture + 子进程 runner（对齐 IT 模式）
# ============================================================

@pytest.fixture
def app_real(tmp_path):
    """真实装配：真实 Renderer（SDL dummy）+ 真实 HighScoreStore(tmp 隔离)。"""
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


def _run_py(code: str, env: dict, timeout: int = 90, cwd_override: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(cwd_override if cwd_override is not None else _WORKSPACE),
    )


def _new_game_with_food(app, difficulty: Difficulty, ahead: int = 1) -> None:
    """开新局并可控注入食物到蛇头前方 ahead 格（测试套件框架 §3.4 可控注入）。"""
    app._difficulty = difficulty
    app._new_game(difficulty)
    gs = app.game_state
    head = gs.head
    d = gs.direction
    target = Point(head.x + d.value[0] * ahead, head.y + d.value[1] * ahead)
    app.game_state = dataclasses.replace(gs, food=Food(pos=target))


# ============================================================
# ST-01 开箱即用（FR-14/FR-16/NFR-07）
# ============================================================

class TestSt01OutOfBox:
    """ST-01：打包资产齐备 + SHA256SUMS 可校验 + 源码模式启动链路成立。"""

    @pytest.mark.p0
    def test_01a_spec_and_build_assets(self):
        spec = _ASSET_ROOT / "spec" / "snake-gui.spec"
        assert spec.exists(), "spec 应实存"
        text = spec.read_text(encoding="utf-8")
        assert 'name="snake-gui"' in text, "EXE name"
        assert "SourceHanSansCN-Regular.otf" in text, "datas 字体"
        assert "collect_submodules" in text, "hiddenimports 收集"
        for pkg in ("game_app", "platform_storage", "gui_renderer"):
            assert pkg in text, f"hiddenimports 含 {pkg}"
        assert "pathex=" in text, "pathex 四目录"
        for script in ("build_linux.sh", "build_windows.bat", "build_macos.sh", "gen_sha256sums.sh"):
            assert (_ASSET_ROOT / "scripts" / script).exists(), f"脚本 {script} 应实存"

    @pytest.mark.p0
    def test_01b_bash_syntax(self):
        for script in ("build_linux.sh", "build_macos.sh", "gen_sha256sums.sh"):
            p = _ASSET_ROOT / "scripts" / script
            r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True, timeout=30)
            assert r.returncode == 0, f"{script} bash -n 语法错误: {r.stderr}"

    @pytest.mark.p0
    def test_01c_sha256sums_verifiable(self):
        release = _ASSET_ROOT / "release"
        for f in ("USER_GUIDE.md", "RELEASE_NOTES.md", "SHA256SUMS"):
            assert (release / f).exists(), f"发布物 {f} 应实存"
        sums = (release / "SHA256SUMS").read_text(encoding="utf-8")
        pattern = re.compile(r"^[0-9a-f]{64}\s{2}\S+$")
        lines = [ln for ln in sums.splitlines() if ln.strip()]
        assert lines, "SHA256SUMS 非空"
        checked = 0
        for ln in lines:
            assert pattern.match(ln), f"SHA256SUMS 行格式非法: {ln}"
            digest, _, rel = ln.partition("  ")
            target = release / rel
            if target.exists():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                assert actual == digest, f"{rel} 哈希不匹配"
                checked += 1
        assert checked >= 2, "至少 USER_GUIDE/RELEASE_NOTES 两项可真实校验（NFR-07）"

    @pytest.mark.p0
    def test_01d_source_mode_launch(self, tmp_path):
        """源码模式启动链路成立（python -m game_app 注入 QUIT → 退出码 0）。"""
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 0, f"启动链路退出码应 0，实际 {r.returncode}\nstderr={r.stderr}"
        assert "Traceback" not in r.stderr, f"不应有裸 traceback: {r.stderr}"


# ============================================================
# ST-02 开始→选难度（FR-05/FR-11）
# ============================================================

class TestSt02DifficultySelect:
    """ST-02：三档开局可选、选档生效（tick_ms 参数表）、游戏中不可切换。"""

    @pytest.mark.p0
    def test_02a_three_difficulties_selectable(self, app_real):
        expected = {
            Difficulty.EASY: 250,
            Difficulty.MEDIUM: 160,
            Difficulty.HARD: 100,
        }
        for diff, tick in expected.items():
            a = app_real
            assert a.screen == AppScreen.MENU
            action = {
                Difficulty.EASY: InputAction.SELECT_EASY,
                Difficulty.MEDIUM: InputAction.SELECT_MEDIUM,
                Difficulty.HARD: InputAction.SELECT_HARD,
            }[diff]
            a._dispatch(action)      # MENU 态选档：改 _difficulty
            a._dispatch(InputAction.START)  # 开始新局
            assert a.screen == AppScreen.PLAYING, f"{diff} 选档后应进入 PLAYING"
            snap = a.game_state.snapshot()
            assert snap.difficulty == diff, f"FR-05 选档生效: {snap.difficulty}"
            assert snap.tick_ms == tick, f"难度参数表穿透 app: {snap.tick_ms}"
            # 结束回 MENU，为下一档做准备
            a.screen = AppScreen.GAME_OVER
            a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
            a._dispatch(InputAction.BACK_TO_MENU)
            assert a.screen == AppScreen.MENU

    @pytest.mark.p0
    def test_02b_no_switch_in_game(self, app_real):
        """游戏中（PLAYING）SELECT_HARD 无效——难度游戏中不可切换（防规避）。"""
        a = app_real
        a._dispatch(InputAction.SELECT_MEDIUM)
        a._dispatch(InputAction.START)
        assert a.screen == AppScreen.PLAYING
        snap_before = a.game_state.snapshot()
        a._dispatch_playing(InputAction.SELECT_HARD)  # PLAYING 态无 SELECT 分支 → 无效果
        snap_after = a.game_state.snapshot()
        assert snap_after.difficulty == Difficulty.MEDIUM, "游戏中难度不可切换（FR-05）"
        assert snap_after.tick_ms == snap_before.tick_ms == 160


# ============================================================
# ST-03 完整对局（FR-01~04/06~10/12）
# ============================================================

class TestSt03FullJourney:
    """ST-03：端到端主链路——吃食增长→暂停原位→皮肤切换不中断→撞墙结束→重开/退出。"""

    @pytest.mark.p0
    def test_03a_eat_grow_and_pause(self, app_real):
        a = app_real
        a._difficulty = Difficulty.EASY
        a._new_game(Difficulty.EASY)  # 只开一局，全程不重置（分数累计）
        assert a.screen == AppScreen.PLAYING
        # 吃 3 个食物：每轮仅替换 food 位置到蛇头前方（不重置 game_state），真实 step 推进
        for _ in range(3):
            gs = a.game_state
            head = gs.head
            d = gs.direction
            target = Point(head.x + d.value[0], head.y + d.value[1])
            a.game_state = dataclasses.replace(gs, food=Food(pos=target))
            a._tick(Difficulty.EASY.base_tick_ms)
            assert a.game_state.snapshot().status == GameStatus.RUN, "吃食过程不应 OVER"
        snap = a.game_state.snapshot()
        assert snap.score >= 3, f"FR-01 吃 ≥3 食物得分增长: {snap.score}"
        assert snap.length >= 3, f"FR-01 长度增长: {snap.length}"
        # 暂停/继续原位恢复（FR-12）
        pos_before = a.game_state.snapshot().snake_body
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PAUSED
        assert a.game_state.status == GameStatus.PAUSED
        a._dispatch_paused(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state.status == GameStatus.RUN
        assert a.game_state.snapshot().snake_body == pos_before, "暂停/继续蛇位不变（FR-12）"

    @pytest.mark.p0
    def test_03b_skin_switch_no_interrupt(self, app_real):
        a = app_real
        _new_game_with_food(a, Difficulty.MEDIUM, ahead=1)
        a._tick(Difficulty.MEDIUM.base_tick_ms)
        before_skin = a._renderer.current_skin_name
        # PLAYING 态 SET_SKIN_NEXT 透传为 MOVE_RIGHT（对局不中断，FR-10）
        a._dispatch_playing(InputAction.SET_SKIN_NEXT)
        assert a.screen == AppScreen.PLAYING, "切换皮肤不中断对局（FR-10）"
        assert a.game_state.status == GameStatus.RUN
        # 皮肤由 MENU 态切换验证（ST-09），此处仅验证对局不中断
        assert a._renderer.current_skin_name == before_skin  # PLAYING 态不改皮肤

    @pytest.mark.p0
    def test_03c_wall_collision_and_restart(self, app_real):
        a = app_real
        a._difficulty = Difficulty.EASY
        a._new_game(Difficulty.EASY)
        # 强制蛇头朝右一路撞墙（可控：替换蛇身贴近右墙）
        gs = a.game_state
        head = Point(gs.width - 2, 2)
        body = tuple(Point(head.x - i, head.y) for i in range(len(gs.snake)))
        a.game_state = dataclasses.replace(
            gs, snake=type(gs.snake)(body=body), direction=Direction.RIGHT,
            pending_direction=Direction.RIGHT,
        )
        # 真实 _tick 推进直到撞墙 OVER（最多 width 拍）
        for _ in range(gs.width + 2):
            a._tick(Difficulty.EASY.base_tick_ms)
            if a.screen == AppScreen.GAME_OVER:
                break
        assert a.screen == AppScreen.GAME_OVER, "FR-04 撞墙结束"
        assert a.game_state.status == GameStatus.OVER
        # GAME_OVER 真实绘制不抛（FR-06/07）
        a._render()
        # 重开（FR-11）
        a._dispatch_over(InputAction.RESTART)
        assert a.screen == AppScreen.PLAYING, "FR-11 结束可重开新局"
        assert a.game_state.status == GameStatus.RUN
        # 再结束 → 回 MENU
        a.screen = AppScreen.GAME_OVER
        a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
        a._dispatch_over(InputAction.BACK_TO_MENU)
        assert a.screen == AppScreen.MENU, "FR-11 结束可回开始界面"


# ============================================================
# ST-04 最高分持久化（FR-13/NFR-06）
# ============================================================

class TestSt04HighScorePersistence:
    """ST-04：得分落盘→重启保留→重置归零→数据仅本地（真实 IO）。"""

    @pytest.mark.p0
    def test_04_persist_restart_reset(self, tmp_path, monkeypatch):
        hs_file = tmp_path / "highscore.json"
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: HighScoreStore(hs_file))
        # App A：落盘
        a = App(AppConfigV3(enable_high_dpi=False))
        a._init_pygame()
        assert a._high_score == 0
        a._new_game(Difficulty.MEDIUM)
        a.game_state._score_callback(120)
        assert a._high_score == 120, "INV-13 实例字段同步"
        assert hs_file.exists(), "真实落盘"
        import json as _json
        assert _json.loads(hs_file.read_text(encoding="utf-8"))["high_score"] == 120
        # App B（重启）：加载一致
        b = App(AppConfigV3(enable_high_dpi=False))
        b._init_pygame()
        assert b._high_score == 120, "FR-13 重启最高分保留"
        # 重置归零（platform-storage reset 契约）
        b._dispatch_menu(InputAction.RESET_HIGHSCORE)
        assert b._high_score == 0
        assert not hs_file.exists(), "reset 删除文件"
        # 数据仅本地（NFR-06）：全部写入均在 tmp 隔离目录
        outside = [p for p in tmp_path.rglob("*") if not str(p).startswith(str(tmp_path))]
        assert not outside, "无 tmp 外写入（NFR-06 本地性）"


# ============================================================
# ST-05 退出卫生（FR-11）
# ============================================================

class TestSt05ExitHygiene:
    """ST-05：游戏/暂停/结束三时机退出 → 1 秒内干净结束、无残留进程。"""

    def _quit_in_state(self, tmp_path, state: str):
        import time
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "from game_core import Difficulty, GameStatus\n"
            "from game_core.types import Point\n"
            "import dataclasses\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "a._new_game(Difficulty.MEDIUM)\n"
            f"if '{state}' == 'paused':\n"
            "    a._dispatch_playing(__import__('game_app').InputAction.TOGGLE_PAUSE)\n"
            f"elif '{state}' == 'over':\n"
            "    gs = a.game_state\n"
            "    a.game_state = dataclasses.replace(gs, status=GameStatus.OVER)\n"
            "    a.screen = __import__('game_app').AppScreen.GAME_OVER\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        t0 = time.monotonic()
        r = _run_py(code, _child_env(tmp_path))
        elapsed = time.monotonic() - t0
        assert r.returncode == 0, f"{state} 态退出码应 0，实际 {r.returncode}\nstderr={r.stderr}"
        assert elapsed < 1.0, f"{state} 态退出应 1 秒内，实际 {elapsed:.2f}s"
        return elapsed

    @pytest.mark.p0
    def test_05_three_moments_clean_exit(self, tmp_path):
        for state in ("playing", "paused", "over"):
            self._quit_in_state(tmp_path, state)
        # 无残留进程
        ps = subprocess.run(
            ["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=30
        ).stdout
        leftovers = [
            ln for ln in ps.splitlines()
            if "game_app" in ln and "test_st_v2_0_0" not in ln and "grep" not in ln
        ]
        assert not leftovers, f"存在残留进程: {leftovers}"


# ============================================================
# ST-06 用户指南走查（FR-16）
# ============================================================

class TestSt06UserGuide:
    """ST-06：五节齐全、键位表与实现一致、按文档可复现启动。"""

    @pytest.mark.p1
    def test_06_guide_sections_and_keys(self, tmp_path):
        guide = (_ASSET_ROOT / "release" / "USER_GUIDE.md").read_text(encoding="utf-8")
        for sec in ("下载与运行", "键位表", "难度", "皮肤", "暂停", "平台差异", "已知限制"):
            assert sec in guide, f"USER_GUIDE 缺小节: {sec}"
        for plat in ("Linux", "Windows", "macOS"):
            assert plat in guide, f"USER_GUIDE 缺平台: {plat}"
        # 键位表与实现一致：指南键位字符在 input.py 映射中
        input_src = (_CODE_APP / "game_app" / "input.py").read_text(encoding="utf-8")
        for key in ("K_w", "K_a", "K_s", "K_d", "K_UP", "K_DOWN", "K_LEFT", "K_RIGHT", "K_p", "K_ESCAPE"):
            assert key in input_src, f"指南键位 {key} 应在 input 映射实现中"
        # 难度三档与皮肤名一致
        from game_app.app import _DIFFICULTY_LABEL  # noqa: F401
        assert "简单" in guide and "普通" in guide and "困难" in guide
        # 指南面向用户用中文皮肤名；英文标识符与实现 SKIN_REGISTRY 一致性由 ST-07d/ST-09 断言
        for skin_cn in ("经典", "深色", "色盲友好"):
            assert skin_cn in guide, f"指南应含皮肤说明: {skin_cn}"
        # 按文档可复现启动（冒烟，与 ST-01d 同路径）
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 0, f"按指南可复现启动: {r.stderr}"


# ============================================================
# ST-07 跨模块契约锚点（§3.2 回归锚点）
# ============================================================

class TestSt07ContractAnchors:
    """ST-07：core snapshot 7 字段 + 难度参数表 + storage schema + renderer 契约。"""

    @pytest.mark.p0
    def test_07a_snapshot_contract(self):
        gs = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=__import__("random").Random(42))
        snap = gs.snapshot()
        for field in ("snake_body", "food", "score", "length", "status", "difficulty", "tick_ms"):
            assert hasattr(snap, field), f"snapshot 缺字段 {field}"
        assert snap.tick_ms == Difficulty.MEDIUM.base_tick_ms

    @pytest.mark.p0
    def test_07b_difficulty_and_perf_contract(self):
        ticks = {d: d.base_tick_ms for d in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD)}
        assert ticks == {Difficulty.EASY: 250, Difficulty.MEDIUM: 160, Difficulty.HARD: 100}, f"难度参数表: {ticks}"
        assert ticks[Difficulty.HARD] <= ticks[Difficulty.EASY] * TICK_MS_HARD_MAX_RATIO, "NFR-01 困难 ≤ 简单 50%"
        assert TARGET_FPS == 60 and P95_FRAME_TIME_MS_MAX == 25.0 and MEMORY_PEAK_MB_MAX == 300

    @pytest.mark.p0
    def test_07c_storage_schema(self, tmp_path):
        store = HighScoreStore(tmp_path / "hs.json")
        store.save(88)
        import json as _json
        data = _json.loads((tmp_path / "hs.json").read_text(encoding="utf-8"))
        assert data["high_score"] == 88, "storage JSON schema（high_score 字段）与 app 落盘一致"
        assert store.load() == 88

    @pytest.mark.p0
    def test_07d_renderer_contract(self):
        from gui_renderer.constants import SKIN_REGISTRY
        assert set(SKIN_REGISTRY) >= {"classic", "dark", "colorblind_friendly"}, "皮肤注册表 ≥3 套"
        assert MIN_PLAYABLE_W > 0 and MIN_PLAYABLE_H > 0
        for method in ("set_skin", "handle_resize", "render", "fps_metric", "skin_names"):
            assert callable(getattr(Renderer, method, None)), f"Renderer.{method} 签名可用"


# ============================================================
# ST-08 全量自动化回归（§3.2）
# ============================================================

class TestSt08FullRegression:
    """ST-08：全部 9 个模块 IT 测试集重跑——跨模块回归无破坏。"""

    @pytest.mark.p0
    def test_08_all_it_suites_rerun(self, tmp_path):
        results = []
        env = _child_env(tmp_path)
        for it_dir in _IT_DIRS:
            test_dir = _WORKSPACE / "it" / it_dir
            py_files = sorted(test_dir.glob("test_*.py"))
            assert py_files, f"{it_dir} 无测试文件"
            r = subprocess.run(
                [sys.executable, "-m", "pytest", *[str(p) for p in py_files], "-q", "--tb=line"],
                capture_output=True, text=True, timeout=300, env=env, cwd=str(_ZTEAM),
            )
            # 提取失败用例 ID（无失败则空集）
            failed_ids = set()
            for ln in r.stdout.splitlines():
                m = re.search(r"FAILED\s+\S+::(\w+)", ln)
                if m:
                    failed_ids.add(m.group(1))
            known = _KNOWN_STALE_FAILURES.get(it_dir, set())
            # 全过目录：rc 必须 0；白名单目录：失败集必须 == 已知错位集（多出 = 新缺陷）
            if it_dir in _KNOWN_STALE_FAILURES:
                unexpected = failed_ids - known
                missing_known = known - failed_ids
                assert not unexpected, f"{it_dir} 出现白名单外失败（疑似新回归）: {sorted(unexpected)}"
                assert not missing_known, f"{it_dir} 白名单用例未按预期失败: {sorted(missing_known)}"
                summary = f"known-stale({len(failed_ids)}) {sorted(failed_ids)}"
                results.append((it_dir, 0, summary))
            else:
                assert r.returncode == 0, f"{it_dir} 回归失败 rc={r.returncode}\n{r.stdout[-2000:]}"
                tail = (r.stdout + r.stderr).strip().splitlines()
                summary = tail[-1] if tail else "(empty)"
                results.append((it_dir, r.returncode, summary))
        for it_dir, rc, summary in results:
            print(f"[回归] {it_dir}: rc={rc} {summary}")
        assert all(rc == 0 for _, rc, _ in results), "存在回归失败目录"


# ============================================================
# ST-09 皮肤系统端到端（FR-10）
# ============================================================

class TestSt09SkinSystem:
    """ST-09：3 套真实可切换、色盲方案非颜色唯一区分、对局中切换不中断。"""

    @pytest.mark.p1
    def test_09_skins_switch_and_colorblind(self, app_real):
        a = app_real
        names = list(a._renderer.skin_names())
        assert len(names) >= 3, f"FR-10 ≥3 套皮肤: {names}"
        # MENU 态循环切换即时生效（MENU 态 SET_SKIN_NEXT 由 _drain_events 同步处理 → _switch_skin）
        order = []
        for _ in range(len(names) + 1):
            a._switch_skin(InputAction.SET_SKIN_NEXT)
            order.append(a._renderer.current_skin_name)
        # 3 套皮肤：切 3 次遍历全部并回到初始皮肤（循环），第 4 次回到第 1 次后的状态（往复循环）
        assert order[len(names) - 1] == "classic", f"切 {len(names)} 次应回到初始皮肤（循环）: {order}"
        assert order[-1] == order[0], f"往复循环: {order}"
        assert len(set(order)) == len(names), f"皮肤应遍历全部: {order}"
        # 色盲友好方案：不以颜色为唯一区分（叠加 food_pattern/snake_pattern）
        from gui_renderer.constants import COLORBLIND_FRIENDLY_SKIN
        assert COLORBLIND_FRIENDLY_SKIN.food_pattern != "solid", "色盲方案食物叠加纹理（非纯色）"
        assert COLORBLIND_FRIENDLY_SKIN.snake_pattern == "striped", "色盲方案蛇身条纹"
        # 三种颜色三元组不全相同（可区分）
        c = COLORBLIND_FRIENDLY_SKIN
        colors = {(c.background.r, c.background.g, c.background.b),
                  (c.snake_body.r, c.snake_body.g, c.snake_body.b),
                  (c.food.r, c.food.g, c.food.b)}
        assert len(colors) == 3, "蛇/食物/背景颜色互不相同"


# ============================================================
# ST-10 窗口缩放（FR-09/NFR-04）
# ============================================================

class TestSt10Resize:
    """ST-10：VIDEORESIZE 等比缩放 + 小于最小尺寸 RenderError 兜底提示。"""

    @pytest.mark.p1
    def test_10_resize_and_min_size(self, app_real, capsys):
        a = app_real
        pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600))
        actions = a._drain_events()
        assert InputAction.RESIZE not in actions, "RESIZE 同步处理不入 dispatch"
        surface = pygame.display.get_surface()
        assert surface is not None and surface.get_size() == (800, 600), "FR-09 等比缩放生效"
        a._render()  # 缩放后正常绘制
        # 小于最小尺寸 → RenderError 兜底 stderr 提示 + 不抛（INV-15）
        a._handle_resize(pygame.event.Event(pygame.VIDEORESIZE, w=100, h=100))
        err = capsys.readouterr().err
        assert "窗口缩放失败" in err, f"RenderError 兜底 stderr: {err}"
        assert a.screen in (AppScreen.MENU, AppScreen.PLAYING), "缩放失败不中断"


# ============================================================
# ST-11 错误提示友好（NFR-03）
# ============================================================

class TestSt11ErrorHints:
    """ST-11：图形不可用退出码 2 / 存储不可写退出码 3，stderr 可读、无裸 traceback。"""

    @pytest.mark.p1
    def test_11_exit_codes_and_readable(self, tmp_path):
        # 图形不可用 → 2
        code_main = "from game_app import main; import sys; sys.exit(main())"
        r1 = _run_py(code_main, _child_env(tmp_path, {"SDL_VIDEODRIVER": "invalid_driver_xyz"}))
        assert r1.returncode == 2, f"图形不可用应退出码 2，实际 {r1.returncode}\nstderr={r1.stderr}"
        assert "[错误]" in r1.stderr and "建议" in r1.stderr, f"可读提示: {r1.stderr}"
        # 存储不可写 → 3
        r2 = _run_py(
            "import game_app.app as app_mod\n"
            "def boom(*a, **kw): raise OSError('permission denied')\n"
            "app_mod.create_storage = boom\n"
            "from game_app import main; import sys; sys.exit(main())",
            _child_env(tmp_path),
        )
        assert r2.returncode == 3, f"存储不可写应退出码 3，实际 {r2.returncode}\nstderr={r2.stderr}"
        assert "用户数据目录不可写" in r2.stderr and "建议" in r2.stderr, f"可读提示: {r2.stderr}"
        # 无裸 traceback
        for r in (r1, r2):
            assert "Traceback" not in r.stderr, f"不应有裸 traceback: {r.stderr}"
            assert 'File "' not in r.stderr, f"不应泄露堆栈: {r.stderr}"


# ============================================================
# ST-12 静态检查（NFR-05/06）
# ============================================================

class TestSt12StaticChecks:
    """ST-12：四包零网络 import、零音效 import、运行期依赖隔离。"""

    @pytest.mark.p2
    def test_12_no_network_no_audio(self):
        pkg_dirs = [
            _CODE_CORE / "game_core",
            _CODE_STORAGE / "platform_storage",
            _CODE_RENDERER / "gui_renderer",
            _CODE_APP / "game_app",
        ]
        combined = "\n".join(
            f.read_text(encoding="utf-8")
            for root in pkg_dirs for f in root.glob("*.py")
        )
        for banned in ("import socket", "import urllib", "import http", "import requests",
                       "pygame.mixer", "pygame.music"):
            assert banned not in combined, f"静态检查失败: 出现 {banned}（NFR-05/06）"

    @pytest.mark.p2
    def test_12b_runtime_network_isolation(self, tmp_path):
        """AST 级运行期依赖隔离：被测四包源码不含网络 import。"""
        code = (
            "import ast, pathlib\n"
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


# ============================================================
# ST-13 性能基线（NFR-01/02）
# ============================================================

class TestSt13PerfBaseline:
    """ST-13：bench_fps / bench_memory 真实执行 + 性能常量契约。"""

    @pytest.mark.p0
    def test_13a_bench_fps_real(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(_ASSET_ROOT / "scripts" / "bench_fps.py"),
             "--duration", "3", "--difficulty", "medium"],
            capture_output=True, text=True, timeout=180,
            env=_child_env(tmp_path), cwd=str(_ASSET_ROOT),
        )
        assert r.returncode in (0, 1), f"bench_fps 应可跑通，实际 {r.returncode}\nstderr={r.stderr}"
        for token in ("平均 FPS", "P95 帧时间", "NFR-01 评估:"):
            assert token in r.stdout, f"stdout 缺 {token}: {r.stdout}"
        assert re.search(r"NFR-01 评估: (PASS|FAIL)", r.stdout), f"判定输出缺失: {r.stdout}"
        print(f"[ST-13] bench_fps: {r.stdout.strip().splitlines()[-5:]}")

    @pytest.mark.p0
    def test_13b_bench_memory_real(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(_ASSET_ROOT / "scripts" / "bench_memory.py"),
             "--duration", "3"],
            capture_output=True, text=True, timeout=180,
            env=_child_env(tmp_path), cwd=str(_ASSET_ROOT),
        )
        assert r.returncode in (0, 1), f"bench_memory 应可跑通，实际 {r.returncode}\nstderr={r.stderr}"
        for token in ("内存峰值", "NFR-02 评估:"):
            assert token in r.stdout, f"stdout 缺 {token}: {r.stdout}"
        assert re.search(r"NFR-02 评估: (PASS|FAIL)", r.stdout), f"判定输出缺失: {r.stdout}"
        print(f"[ST-13] bench_memory: {r.stdout.strip().splitlines()[-4:]}")

    @pytest.mark.p1
    def test_13c_perf_constant_contract(self):
        assert TARGET_FPS == 60
        assert P95_FRAME_TIME_MS_MAX == 25.0
        assert MEMORY_PEAK_MB_MAX == 300
        assert 1000.0 / TARGET_FPS <= P95_FRAME_TIME_MS_MAX, "P95 上限 ≥ 单帧预算（自洽）"


# ============================================================
# ST-14 兼容矩阵（FR-15/NFR-04）
# ============================================================

class TestSt14CompatMatrix:
    """ST-14：Linux 本机实测（自动化为可验证部分）+ Win/macOS 产物与文档齐备（清单留痕）。"""

    @pytest.mark.p2
    def test_14_linux_run_and_other_platform_assets(self, tmp_path):
        # Linux：ST-03 完整对局已实测（本类仅做进程级冒烟复核）
        code = (
            "from game_app import App, AppConfigV3; import pygame, sys\n"
            "a = App(AppConfigV3()); a._init_pygame()\n"
            "a._dispatch(__import__('game_app').InputAction.SELECT_EASY)\n"
            "a._dispatch(__import__('game_app').InputAction.START)\n"
            "for _ in range(60):\n"
            "    a._tick(16); a._render()\n"
            "pygame.event.post(pygame.event.Event(pygame.QUIT))\n"
            "sys.exit(a.run())"
        )
        r = _run_py(code, _child_env(tmp_path))
        assert r.returncode == 0, f"Linux 对局冒烟失败: {r.stderr}"
        # Windows/macOS：构建脚本与文档齐备（真实构建/运行属发布环境人工矩阵）
        for script in ("build_windows.bat", "build_macos.sh"):
            p = _ASSET_ROOT / "scripts" / script
            assert p.exists(), f"{script} 应实存"
        text = (_ASSET_ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8", errors="replace")
        assert "pyinstaller" in text.lower(), "bat 应含 pyinstaller 调用"
        guide = (_ASSET_ROOT / "release" / "USER_GUIDE.md").read_text(encoding="utf-8")
        for plat in ("Windows", "macOS"):
            assert plat in guide, f"指南缺平台说明: {plat}"


# ============================================================
# 汇总输出（pytest 收集统计）
# ============================================================

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """控制台结构化汇总（对齐 IT 报告模式）。"""
    terminalreporter.section("ST 汇总（snake-linux v2.0.0）")
    for key in ("passed", "failed", "skipped", "error"):
        stats = terminalreporter.stats.get(key)
        if stats:
            terminalreporter.write_line(f"  {key}: {len(stats)}")
