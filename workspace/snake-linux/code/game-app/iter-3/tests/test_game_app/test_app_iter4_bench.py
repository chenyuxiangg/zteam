"""G4-3 性能基准脚本 UT（UT PERF-2~5）。

覆盖：
- PERF-2：bench_fps 帧时间快（≤限值）→ PASS
- PERF-3：bench_fps 帧时间慢（>限值）→ FAIL
- PERF-4：bench_memory 峰值低（≤限值）→ PASS
- PERF-5：bench_memory 峰值高（>限值）→ FAIL

被测对象：scripts/bench_fps.py / scripts/bench_memory.py 中的**纯判定逻辑**
（不启动真实窗口——headless 环境无显示器，构造 App 会失败；判定函数是
脚本内可导入的纯函数，脚本主体 run_benchmark 只在有显示环境时执行）。

脚本路径解析：SNAKE_LINUX_ROOT 环境变量（默认 /home/zyzs/cyx/zteam/snake-linux，
与 test_app_iter4_spec.py 一致）。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("SNAKE_LINUX_ROOT", "/home/zyzs/cyx/zteam/snake-linux"))


def _load_script_module(name: str):
    """从 scripts/ 目录按路径加载 bench 脚本模块（避免执行 main）。"""
    path = ROOT / "scripts" / name
    assert path.exists(), f"脚本不存在: {path}"
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    # 阻止脚本 __main__ 入口执行（仅收集函数定义）
    spec.loader.exec_module(mod)
    return mod


class TestBenchFpsJudge:
    """PERF-2/3：NFR-01 帧率判定逻辑。"""

    @pytest.fixture(scope="class")
    def bench_fps(self):
        return _load_script_module("bench_fps.py")

    def test_script_exists(self):
        assert (ROOT / "scripts" / "bench_fps.py").exists()

    def test_judge_pass_when_fast(self, bench_fps):
        """PERF-2：P95 帧时间 ≤ 25ms 且平均 FPS ≥ 60 → PASS。"""
        judge = bench_fps.judge_fps
        assert judge(avg_fps=60.0, p95_frame_ms=20.0) == "PASS"
        assert judge(avg_fps=120.0, p95_frame_ms=10.0) == "PASS"

    def test_judge_fail_when_slow(self, bench_fps):
        """PERF-3：P95 帧时间 > 25ms 或平均 FPS < 60 → FAIL。"""
        judge = bench_fps.judge_fps
        assert judge(avg_fps=60.0, p95_frame_ms=50.0) == "FAIL"
        assert judge(avg_fps=30.0, p95_frame_ms=20.0) == "FAIL"
        assert judge(avg_fps=55.0, p95_frame_ms=30.0) == "FAIL"

    def test_judge_boundary_exact_limit(self, bench_fps):
        """边界：恰好在限值上 → PASS（≤ 语义）。"""
        from game_app.perf import P95_FRAME_TIME_MS_MAX, TARGET_FPS
        assert bench_fps.judge_fps(TARGET_FPS, P95_FRAME_TIME_MS_MAX) == "PASS"

    def test_bench_duration_default(self, bench_fps):
        """--duration 默认值 = BENCH_DURATION_SECONDS（60s）。"""
        from game_app.perf import BENCH_DURATION_SECONDS
        assert bench_fps.DEFAULT_DURATION == BENCH_DURATION_SECONDS

    def test_cli_difficulty_choices(self, bench_fps):
        """CLI --difficulty 只接受 easy/medium/hard。"""
        assert bench_fps.DIFFICULTY_CHOICES == ["easy", "medium", "hard"]


class TestBenchMemoryJudge:
    """PERF-4/5：NFR-02 内存判定逻辑。"""

    @pytest.fixture(scope="class")
    def bench_memory(self):
        return _load_script_module("bench_memory.py")

    def test_script_exists(self):
        assert (ROOT / "scripts" / "bench_memory.py").exists()

    def test_judge_pass_when_low(self, bench_memory):
        """PERF-4：峰值 ≤ 300MB → PASS。"""
        judge = bench_memory.judge_memory
        assert judge(peak_mb=200.0) == "PASS"
        assert judge(peak_mb=150.0) == "PASS"

    def test_judge_fail_when_high(self, bench_memory):
        """PERF-5：峰值 > 300MB → FAIL。"""
        judge = bench_memory.judge_memory
        assert judge(peak_mb=400.0) == "FAIL"
        assert judge(peak_mb=9999.0) == "FAIL"

    def test_judge_boundary_exact_limit(self, bench_memory):
        """边界：恰在 300MB → PASS（≤ 语义）。"""
        from game_app.perf import MEMORY_PEAK_MB_MAX
        assert bench_memory.judge_memory(float(MEMORY_PEAK_MB_MAX)) == "PASS"

    def test_bench_duration_default(self, bench_memory):
        """--duration 默认值 = BENCH_DURATION_SECONDS。"""
        from game_app.perf import BENCH_DURATION_SECONDS
        assert bench_memory.DEFAULT_DURATION == BENCH_DURATION_SECONDS
