"""Concurrency tests for zlog.logger and Logger → Sink pipelines.

Most assertions rely on the GIL keeping CPython dict/list operations atomic,
but they document the contract: callers may freely share a Logger across
threads. If a future Python runtime drops the GIL or someone restructures
dispatch without locks, these tests should fail.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest

from zlog import (
    DEBUG,
    INFO,
    FileSink,
    MemorySink,
    Sink,
    template,
)
from zlog.logger import _loggers

from ._helpers import ZlogTestCase, test_get_logger as get_logger


def _barrier(n: int) -> threading.Barrier:
    """Wait for ``n`` threads to arrive before any proceeds."""
    return threading.Barrier(n)


# ---- Registry race -------------------------------------------------------


class GetLoggerRace(ZlogTestCase):
    """Concurrent get_logger("same") must return the same Logger instance.

    Without locking, two threads can both find the dict empty, both create
    a Logger, and the second write wins. CPython's GIL usually hides this,
    but the contract should not depend on GIL internals.
    """

    def test_concurrent_get_returns_same_instance(self) -> None:
        N = 100
        seen: list[int] = []
        seen_lock = threading.Lock()
        barrier = _barrier(N)

        def worker() -> None:
            barrier.wait()
            lg = get_logger("contended")
            with seen_lock:
                seen.append(id(lg))

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(seen), N)
        self.assertEqual(len(set(seen)), 1, "get_logger returned multiple instances")

    def test_concurrent_distinct_names_all_distinct(self) -> None:
        # Sanity check: under contention, distinct names produce distinct loggers.
        N = 50
        barrier = _barrier(N)

        def worker(i: int) -> None:
            barrier.wait()
            get_logger(f"distinct-{i}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        distinct = [name for name in _loggers if name.startswith("distinct-")]
        self.assertEqual(len(distinct), N)


# ---- Dispatch under contention ------------------------------------------


class EmitUnderContention(ZlogTestCase):
    def test_no_records_lost(self) -> None:
        n_threads = 20
        n_per_thread = 200
        total = n_threads * n_per_thread

        mem = MemorySink(level=DEBUG, formatter=lambda r: r.message)
        log = get_logger("emit-race").add_sink(mem).set_level(DEBUG)

        barrier = _barrier(n_threads)
        errors: list[BaseException] = []
        err_lock = threading.Lock()

        def worker(tid: int) -> None:
            try:
                barrier.wait()
                for i in range(n_per_thread):
                    log.info(f"t{tid}-{i}")
            except BaseException as e:  # noqa: BLE001
                with err_lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"workers raised: {errors[:3]}")
        self.assertEqual(len(mem.records), total, "some records were lost")

    def test_records_addressed_correctly_per_thread(self) -> None:
        # Every record's payload should match the thread that emitted it.
        mem = MemorySink(level=DEBUG, formatter=lambda r: r.message)
        log = get_logger("thread-tag").add_sink(mem).set_level(DEBUG)

        n_threads = 10
        n_per_thread = 50
        barrier = _barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(n_per_thread):
                log.info(f"t{tid}-{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        from collections import Counter

        counts = Counter(r.rsplit("-", 1)[0] for r in mem.records)
        for t in range(n_threads):
            self.assertEqual(counts[f"t{t}"], n_per_thread)


# ---- Mutation during emit ------------------------------------------------


class MutationDuringEmit(ZlogTestCase):
    def test_add_sink_during_emit_does_not_crash(self) -> None:
        log = get_logger("mut-add").set_level(DEBUG)
        sink_added = threading.Event()
        errs: list[BaseException] = []

        def emitter() -> None:
            try:
                for i in range(2000):
                    log.info(f"e{i}")
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        def adder() -> None:
            try:
                for i in range(50):
                    time.sleep(0.001)
                    log.add_sink(MemorySink(formatter=lambda r: r.message))
                    sink_added.set()
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        threads = [threading.Thread(target=emitter) for _ in range(5)]
        threads.append(threading.Thread(target=adder))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errs, [], f"raised: {errs[:3]}")
        self.assertTrue(sink_added.is_set())

    def test_remove_sink_during_emit_does_not_crash(self) -> None:
        # Add a sink we can remove, plus a stable sink to verify emit still works.
        stable = MemorySink(formatter=lambda r: r.message)
        removable = MemorySink(formatter=lambda r: r.message)
        log = get_logger("mut-rm").add_sink(stable).add_sink(removable).set_level(DEBUG)
        errs: list[BaseException] = []

        def emitter() -> None:
            try:
                for i in range(2000):
                    log.info(f"e{i}")
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        def remover() -> None:
            try:
                for _ in range(50):
                    time.sleep(0.001)
                    log.remove_sink(removable)
                    log.add_sink(removable)  # re-add so emitter always has ≥1 sink
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        threads = [threading.Thread(target=emitter) for _ in range(5)]
        threads.append(threading.Thread(target=remover))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errs, [], f"raised: {errs[:3]}")
        # Stable sink must have received everything.
        self.assertEqual(len(stable.records), 2000 * 5)

    def test_set_level_during_emit_does_not_crash(self) -> None:
        log = get_logger("mut-lvl").add_sink(MemorySink(formatter=lambda r: r.message))
        log.set_level(DEBUG)
        errs: list[BaseException] = []

        def emitter() -> None:
            try:
                for i in range(2000):
                    log.info(f"e{i}")
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        def level_churn() -> None:
            try:
                for lvl in (DEBUG, INFO, 40, 50):
                    log.set_level(lvl)
            except BaseException as e:  # noqa: BLE001
                errs.append(e)

        threads = [threading.Thread(target=emitter) for _ in range(3)]
        threads.append(threading.Thread(target=level_churn))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errs, [], f"raised: {errs[:3]}")


# ---- End-to-end Logger → FileSink ---------------------------------------


class LoggerToFileSinkConcurrency(ZlogTestCase):
    def test_concurrent_log_calls_produce_clean_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "concurrent.log")
            log = (
                get_logger("e2e")
                .add_sink(FileSink(path, formatter=template("{message}")))
                .set_level(DEBUG)
            )

            n_threads = 10
            n_per_thread = 50
            barrier = _barrier(n_threads)

            def worker(tid: int) -> None:
                barrier.wait()
                for i in range(n_per_thread):
                    log.info(f"t{tid}-{i}")

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            with open(path) as f:
                lines = [line for line in f if line.endswith("\n")]
            self.assertEqual(len(lines), n_threads * n_per_thread)
            for line in lines:
                line = line.rstrip("\n")
                self.assertRegex(line, r"^t\d+-\d+$")


# ---- Slow sink isolation -------------------------------------------------


class SlowSinkIsolation(ZlogTestCase):
    """Contract: dispatch is synchronous per-sink, slow sinks do not crash,
    and every registered sink still receives the record."""

    def test_slow_sink_still_lets_fast_sink_receive(self) -> None:
        slow_captured: list[str] = []

        class SlowSink(Sink):
            """Same formatter as ``fast`` — only difference is the sleep."""

            def __init__(self) -> None:
                super().__init__(formatter=lambda r: r.message)
                self.captured = slow_captured

            def _emit(self, line: str) -> None:
                time.sleep(0.01)
                self.captured.append(line)

        fast = MemorySink(formatter=lambda r: r.message)
        log = get_logger("slow").add_sink(SlowSink()).add_sink(fast).set_level(DEBUG)

        n = 20
        for i in range(n):
            log.info(f"x{i}")

        # Both sinks got every record — slow doesn't poison the pipeline.
        self.assertEqual(slow_captured, [f"x{i}" for i in range(n)])
        self.assertEqual(fast.records, [f"x{i}" for i in range(n)])


# ---- load_config_dict race ------------------------------------------------


class LoadConfigRace(ZlogTestCase):
    def test_concurrent_load_config_does_not_crash(self) -> None:
        # Reloading the same logger config from multiple threads must not
        # leave the registry half-built or crash with dict-iteration races.
        from zlog import load_config_dict

        N = 30
        barrier = _barrier(N)

        def worker() -> None:
            barrier.wait()
            load_config_dict(
                {
                    "loggers": {
                        "race-x": {"channel": "memory", "level": "INFO"},
                        "race-y": {"channel": "memory", "level": "DEBUG"},
                    }
                }
            )

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Both loggers are present and have valid sinks.
        for name in ("race-x", "race-y"):
            self.assertIn(name, _loggers)
            self.assertGreater(len(_loggers[name].sinks), 0)
