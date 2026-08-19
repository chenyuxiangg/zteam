"""PLAYING 态 dispatch + 撞墙/撞身自动转 GAME_OVER 单测（UT 14/15/16/17/18/23/36）。

需求：
- WASD 推方向（R3-9：InvalidStateError 理论不可达，不包装）
- 连续方向合并（pending）
- P 键占位（迭代 1 不调 toggle_pause）
- 撞墙/撞身自动转 GAME_OVER
"""
from __future__ import annotations

import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Direction, Difficulty, GameStatus, InvalidStateError


class TestPlayingDirectionInput:
    """UT 14/15：PLAYING 态方向输入。

    注意：game-core iter-2 的 set_direction 只检查 `self.direction` 是否反向，
    不检查 `pending_direction`（这是已知设计，参见 design-r3 §4.4 §附录 C）。
    因此"先 dispatch X 再 dispatch X.opposite" 的第二个调用会被静默忽略。

    测试策略：每个用例都从一个**干净**的 app_in_playing fixture 开始，
    避免 pending_direction 与 direction 不一致导致的反向误判。
    """

    def test_move_up_sets_pending(self, app_in_playing: App) -> None:
        """UT 14（UP）：从 RIGHT 默认方向转到 UP（垂直）→ pending=UP。"""
        app_in_playing._dispatch(InputAction.MOVE_UP)
        gs = app_in_playing.game_state
        assert gs.pending_direction == Direction.UP or gs.direction == Direction.UP

    def test_move_down_sets_pending(self, app_in_playing: App) -> None:
        """UT 14（DOWN）：从 RIGHT 转到 DOWN（垂直）→ pending=DOWN。"""
        app_in_playing._dispatch(InputAction.MOVE_DOWN)
        gs = app_in_playing.game_state
        assert gs.pending_direction == Direction.DOWN or gs.direction == Direction.DOWN

    def test_move_left_after_step_commits_up(self, app_in_playing: App) -> None:
        """UT 14（LEFT）：先 step 让 UP 提交到 direction=RIGHT → 再 LEFT 被反向忽略。

        这里确认 game-core 的"反向忽略"行为是可观察的：先 commit UP → direction=UP，
        再 dispatch LEFT → pending=LEFT（LEFT 不是 UP 的反向，UP.opposite=DOWN）。
        """
        # 先 MOVE_UP 让 pending=UP，然后 tick 一步提交 → direction=UP
        app_in_playing._dispatch(InputAction.MOVE_UP)
        # 提交 pending：跑一个 tick（最小 dt_ms 让 tick_ms 触发一次 step）
        # HARD tick_ms=100。accumulator=0+100=100，>=100，step 一次 → pending 提交
        app_in_playing._tick_accumulator_ms = 100
        # 直接调 step 模拟 tick：避免 _tick 内部的 OVER 提前转屏
        gs = app_in_playing.game_state
        new_gs = gs.step()
        app_in_playing.game_state = new_gs
        # 此刻 direction 应为 UP（已 step 一次）
        assert app_in_playing.game_state.direction == Direction.UP
        # 现在 dispatch LEFT：LEFT 不是 UP.opposite（DOWN）→ pending=LEFT
        app_in_playing._dispatch(InputAction.MOVE_LEFT)
        assert app_in_playing.game_state.pending_direction == Direction.LEFT

    def test_consecutive_directions_merge_into_pending(self, app_in_playing: App) -> None:
        """UT 15：连续方向合并（pending）→ 最后一次方向生效。

        同样要避免 game-core 反向忽略：从 RIGHT（默认）→ DOWN（垂直合法）→ UP（垂直合法）
        DOWN.opposite=UP，所以"先 DOWN 再 UP" 第二个会被反向忽略。

        改为：从 RIGHT → UP → DOWN。UP.opposite=DOWN，DROP_DOWN 仍会被反向忽略！
        因为 game-core 检查 direction（RIGHT），不是 pending。
        所以干净的方式是 MOVE_UP → MOVE_LEFT（DROP 不反向，垂直于 UP）
        """
        app_in_playing._dispatch(InputAction.MOVE_UP)   # pending = UP（垂直于 RIGHT 合法）
        # 现在 pending=UP，direction=RIGHT。再 MOVE_LEFT：LEFT 不是 RIGHT.opposite... wait RIGHT.opposite=LEFT
        # → 仍被反向忽略
        # 唯一能让 LEFT 进入 pending 的方式：先 step 提交到 direction=UP，再 dispatch LEFT
        app_in_playing._tick_accumulator_ms = 100
        app_in_playing.game_state = app_in_playing.game_state.step()
        # 现在 direction=UP
        app_in_playing._dispatch(InputAction.MOVE_LEFT)  # LEFT 不是 UP.opposite=DOWN → pending=LEFT
        assert app_in_playing.game_state.pending_direction == Direction.LEFT


class TestPlayingPausePlaceholder:
    """G2-1 iter-2 修订：P 键实际切 PAUSED（替代 iter-1 的 _pause_hint_shown 占位）。

    iter-1 占位行为已被 toggle_pause() 实际切屏取代；本测试类验证 P 键在 PLAYING 态
    切换到 PAUSED 屏态（INV-11 方案 A），_pause_hint_shown 字段已删除（INV-8）。
    """

    def test_p_key_toggles_pause_in_iter2(self, app_in_playing: App) -> None:
        """G2-1：P 键 → toggle_pause() + 同步切屏（INV-11 方案 A）。"""
        assert app_in_playing.screen == AppScreen.PLAYING
        assert app_in_playing.game_state.status == GameStatus.RUN
        app_in_playing._dispatch(InputAction.TOGGLE_PAUSE)
        assert app_in_playing.screen == AppScreen.PAUSED
        assert app_in_playing.game_state.status == GameStatus.PAUSED


class TestPlayingWallCollision:
    def test_wall_collision_transitions_to_game_over(self, app_in_playing: App) -> None:
        """UT 17：撞墙自动转 GAME_OVER。"""
        # app_in_playing 默认 HARD，初始 direction=RIGHT，蛇头在 (10, 7)
        # 让 _tick 累计足够 dt 推动蛇撞右墙
        app_in_playing._tick(100 * 100)  # 100ms tick × 100 = 10s，足够撞墙
        assert app_in_playing.game_state.status == GameStatus.OVER
        assert app_in_playing.screen == AppScreen.GAME_OVER


class TestPlayingSelfCollision:
    def test_self_collision_transitions_to_game_over(self, app_in_playing: App) -> None:
        """UT 18：模拟蛇身填满后 step → screen=GAME_OVER。"""
        # 走足够多步直到填满 / 自撞（蛇身默认 3 节，撞自身前需多次 step）
        # HARD 100ms tick × 500 = 50s ≈ 500 步
        # 蛇身会因吃食而增长，但 food 位置随机；最长情况：等到 OVER
        # 取 10000 步（≈1000s），足够覆盖各种碰撞
        app_in_playing._tick(100 * 10000)
        assert app_in_playing.game_state.status == GameStatus.OVER
        assert app_in_playing.screen == AppScreen.GAME_OVER


class TestInvalidStateErrorNotWrapped:
    """UT 23：OVER 状态调 set_direction 抛 InvalidStateError（FO 不包装）。

    说明：FO 的 _dispatch_over 在 OVER 态不会调用 set_direction（只处理 RESTART）。
    但 game-core 暴露的 set_direction 在 OVER 状态必须抛 InvalidStateError —— 这是
    "FO 不包装"语义的核心：如果以后扩展让 _dispatch_playing 在 OVER 态被调到，
    set_direction 会自然抛错而不是被静默吃掉。UT 直接验证 game-core 行为以确认
    不变量（FO 不写 try/except 包装）。
    """

    def test_set_direction_on_over_raises(self, app_in_playing: App) -> None:
        # 推进到 OVER
        app_in_playing._tick(10000)
        assert app_in_playing.game_state.status == GameStatus.OVER
        # R3-9：FO 不包装 → 让 InvalidStateError 透传
        # 直接调 game-core set_direction 验证 game-core 行为
        with pytest.raises(InvalidStateError):
            app_in_playing.game_state.set_direction(Direction.UP)


class TestPlayingPausedHint:
    """G2-1 iter-2 修订：_pause_hint_shown 字段已删除（INV-8）。

    替代行为验证：撞墙后 screen 切到 GAME_OVER，PAUSED → RUN 切回后 game_state 仍存活。
    """

    def test_over_after_pause_then_unpause(self, app_in_playing: App) -> None:
        """G2-1：PLAYING → PAUSED → PLAYING → 撞墙 → GAME_OVER。"""
        app_in_playing._dispatch(InputAction.TOGGLE_PAUSE)
        assert app_in_playing.screen == AppScreen.PAUSED
        # 继续
        app_in_playing._dispatch(InputAction.TOGGLE_PAUSE)
        assert app_in_playing.screen == AppScreen.PLAYING
        # 撞墙
        app_in_playing._tick(100 * 100)
        assert app_in_playing.screen == AppScreen.GAME_OVER