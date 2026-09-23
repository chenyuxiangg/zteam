"""并发锁测试（commit 7 强化）。

模拟多 tick 同时调度的真实场景：
- 测试 1：同一全局锁互斥（两个线程不能同时持有，写计数器）
- 测试 2：不同项目锁互不阻塞（项目 A + 项目 B 并发执行）
- 测试 3：同项目锁串行（同项目两个线程必须排队，最终计数正确）
- 测试 4：全局锁 ↔ 项目锁独立（全局锁不阻塞项目锁，反之亦然——分文件）
- 测试 5：状态文件最终一致性（多线程并发 claim 不同需求，无丢失/重复）

目的：捕捉 flock 互斥、项目/全局锁分离、claim 并发安全等回归。
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._helpers import StatectlTestCase


class _Counter:
    """线程安全计数器 + 最大并发观察。"""
    def __init__(self) -> None:
        self.n = 0
        self.max_concurrent = 0
        self.current = 0
        self._lock = threading.Lock()
        self._conc_lock = threading.Lock()

    def enter(self) -> None:
        with self._conc_lock:
            self.current += 1
            self.max_concurrent = max(self.max_concurrent, self.current)

    def leave(self) -> None:
        with self._conc_lock:
            self.current -= 1
        with self._lock:
            self.n += 1


class GlobalLockMutualExclusion(StatectlTestCase):
    """全局锁互斥：两个线程不能同时持有。"""

    def setUp(self) -> None:
        super().setUp()
        # StatectlTestCase 已建好 WORKDIR/LOCK_FILE 等必要目录

    def test_only_one_thread_in_critical_section(self) -> None:
        from statectl_core.status import acquire_lock
        counter = _Counter()
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()  # 4 个线程同时起跑
            with acquire_lock(timeout=10):
                counter.enter()
                time.sleep(0.05)  # 给竞争机会
                counter.leave()

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(worker) for _ in range(4)]
            for f in as_completed(futures):
                f.result()  # 任何一个抛异常就立刻失败

        self.assertEqual(counter.n, 4, "应全部 4 次进入")
        self.assertEqual(counter.max_concurrent, 1, "全局锁保证同时只能 1 个线程")


class ProjectLockConcurrency(StatectlTestCase):
    """项目锁：同项目串行，跨项目并发。"""

    def setUp(self) -> None:
        super().setUp()
        self.wp_a = self.make_project("demoA")
        self.wp_b = self.make_project("demoB")

    def test_different_projects_concurrent(self) -> None:
        """项目 A + 项目 B 同时持锁：max_concurrent 应 = 2。"""
        from statectl_core.status import acquire_lock
        counter = _Counter()
        barrier = threading.Barrier(2)

        def worker(project: str):
            barrier.wait()
            with acquire_lock(timeout=10, project=project):
                counter.enter()
                time.sleep(0.05)
                counter.leave()

        t_a = threading.Thread(target=worker, args=("demoA",))
        t_b = threading.Thread(target=worker, args=("demoB",))
        t_a.start(); t_b.start()
        t_a.join(); t_b.join()

        self.assertEqual(counter.n, 2)
        self.assertEqual(counter.max_concurrent, 2,
                         "不同项目锁独立，应并发")

    def test_same_project_serialized(self) -> None:
        """同项目两个线程：必须排队，max_concurrent=1。"""
        from statectl_core.status import acquire_lock
        counter = _Counter()
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            with acquire_lock(timeout=10, project="demoA"):
                counter.enter()
                time.sleep(0.03)
                counter.leave()

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(worker) for _ in range(4)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(counter.n, 4)
        self.assertEqual(counter.max_concurrent, 1,
                         "同项目锁互斥，max_concurrent 应 = 1")

    def test_global_lock_does_not_block_project_lock(self) -> None:
        """全局锁（无 project）和项目锁（project=demoA）应分文件，互不阻塞。"""
        from statectl_core.status import acquire_lock
        counter = _Counter()
        barrier = threading.Barrier(2)

        def global_worker():
            barrier.wait()
            with acquire_lock(timeout=10):  # 全局锁
                counter.enter()
                time.sleep(0.05)
                counter.leave()

        def project_worker():
            barrier.wait()
            with acquire_lock(timeout=10, project="demoA"):  # 项目锁
                counter.enter()
                time.sleep(0.05)
                counter.leave()

        t_g = threading.Thread(target=global_worker)
        t_p = threading.Thread(target=project_worker)
        t_g.start(); t_p.start()
        t_g.join(); t_p.join()

        self.assertEqual(counter.n, 2)
        self.assertEqual(counter.max_concurrent, 2,
                         "全局锁和项目锁分文件，应并发")


class ConcurrentClaimConsistency(StatectlTestCase):
    """多线程并发 claim：最终一致性（无丢失/重复）。"""

    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_concurrent_register_then_claim(self) -> None:
        """两个线程同时启动 register + tick，验证最终 status.json 一致。"""
        # 先 seed 一个 pending 需求（input/ 注册新条目是 register_new_inputs 干的事，
        # 这里直接 seed 进 status.json）
        from statectl_core.status import read_status, write_status
        seed = {
            "demo/R1": {
                "status": "pending",
                "round": 0,
                "max_rounds": 3,
                "forced": False,
                "analysis": None,
                "reviews": [],
                "failures": 0,
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
            }
        }
        write_status(seed, project="demo")

        from statectl_core.status import acquire_lock, read_status
        # 两个线程同时尝试在 demo 项目锁下做点事（验证不崩 + 不丢数据）
        barrier = threading.Barrier(2)
        results = []

        def worker(tag: str):
            barrier.wait()
            with acquire_lock(timeout=10, project="demo"):
                st = read_status(project="demo")
                # 模拟一些逻辑：读 + 改 + 写
                st["demo/R1"]["round"] = st["demo/R1"].get("round", 0) + 1
                st["demo/R1"]["updated_at"] = "2026-09-01T00:00:00Z"
                # 模拟一点点计算时间，放大竞争窗口
                time.sleep(0.02)
                from statectl_core.status import write_status as _ws
                _ws(st, project="demo")
                results.append((tag, st["demo/R1"]["round"]))

        t1 = threading.Thread(target=worker, args=("A",))
        t2 = threading.Thread(target=worker, args=("B",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # 验证：两个线程都成功执行 + round 累加到 2（因为 lock 串行）
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(r[1] for r in results), [1, 2],
                         f"round 应严格累加，实际 {results}")

        # 读最终状态
        st = read_status(project="demo")
        self.assertEqual(st["demo/R1"]["round"], 2)


class LockTimeoutBehavior(StatectlTestCase):
    """acquire_lock 超时：timeout 太小 → RuntimeError。"""

    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_timeout_when_held(self) -> None:
        """持锁线程先抢，再尝试时 timeout=0.5 应抛 RuntimeError。"""
        from statectl_core.status import acquire_lock

        holder_acquired = threading.Event()
        holder_release = threading.Event()

        def holder():
            with acquire_lock(timeout=10, project="demo"):
                holder_acquired.set()
                holder_release.wait(timeout=5)

        def waiter():
            holder_acquired.wait(timeout=2)
            with self.assertRaises(RuntimeError) as cm:
                with acquire_lock(timeout=0.5, project="demo"):
                    pass
            self.assertIn("超时", str(cm.exception))

        t_h = threading.Thread(target=holder)
        t_w = threading.Thread(target=waiter)
        t_h.start(); t_w.start()
        t_w.join()
        holder_release.set()
        t_h.join()


if __name__ == "__main__":
    unittest.main()
