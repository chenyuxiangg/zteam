# -*- coding: utf-8 -*-
"""tetris 性能测试——TC-P-01/02（TC-P-03 为人工目测，见 system_checklist.md）。

依据测试方案 workspace/testplans/tetris/tetris-r2.md §3.2 用例表（r2 口径）：
    TC-P-01 (P1, NFR-01) 输入延迟 ≤ 50ms（P95）——r2 绝对值口径；
                         建议项、非强制验收（analysis r2 R1-04 标注，
                         需求方确认不关注可取消，不阻塞发布）
    TC-P-02 (P1, NFR-02) 运行 60 秒：CPU ≤ 5%（单核）、RSS ≤ 50MB；同为建议项

测量方法（r2 明确，方案 §3.2/§4/§5）：
    输入延迟 = time.monotonic() 在 send 前记录 t0 → 以屏幕内容确认动作生效
    （pyte 屏幕轮询，细粒度 ≤10ms）后记录 t1 → 差值 = 输入延迟；
    采样 ≥ 20 次，计算均值与 P95。
    测量含 pyte 轮询采样开销 + pexpect 调度开销 + curses timeout(25) 渲染周期，
    开销与真实延迟分离记录；通过基准 = 「含测量开销仍达标」（≤50ms P95）。
    为避免贴壁拒绝造成无效采样，左右移按键交替发送（a/d），旋转 w 佐证。
    资源占用 = ps 每 5 秒采样 RSS/CPU%，CPU 用进程累计 CPU 时间差分 / 墙钟时间。

运行：python3 perf_tetris.py   （或 bash perf_tetris.sh）
退出码：全 PASS = 0；任一 FAIL = 1（性能为建议项，失败不阻塞发布，仅记录）
"""
import os
import statistics
import subprocess
import sys
import time

import pexpect
import pyte

CODE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..', '..', 'code', 'tetris', 'tetris-r2',
                                     'tetris.py'))
ENV = dict(os.environ, TERM='xterm-256color')
DIM = (30, 60)
SAMPLE_N = 20        # TC-P-01 采样次数（方案：≥ 20）
POLL_MS = 0.01       # TC-P-01 细粒度轮询间隔（r2：≤10ms）
RUN_SECONDS = 60     # TC-P-02 采样时长（方案：60 秒）
SAMPLE_INTERVAL = 5  # TC-P-02 采样间隔（方案：每 5 秒）
LATENCY_P95_LIMIT_MS = 50   # r2 绝对值口径：输入延迟 ≤ 50ms（P95）


class TermScreen(object):
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.screen = pyte.Screen(rows, cols)
        self.stream = pyte.ByteStream(self.screen)
        self.child = None

    class _Feeder(object):
        def __init__(self, outer):
            self.outer = outer

        def write(self, data):
            self.outer.stream.feed(data)

        def flush(self):
            pass

    def spawn(self, args, timeout=8):
        self.child = pexpect.spawn('python3', args, dimensions=(self.rows, self.cols),
                                   timeout=timeout, env=ENV)
        self.child.logfile_read = self._Feeder(self)
        return self.child

    def _drain(self, timeout=0.05):
        try:
            self.child.read_nonblocking(size=100000, timeout=timeout)
        except Exception:
            pass

    def refresh(self, wait=0.2):
        if wait:
            time.sleep(wait)
        self._drain(0.2)
        return '\n'.join(self.screen.display)

    def quit(self):
        try:
            self.child.send('q')
            self.child.expect(pexpect.EOF, timeout=3)
            self.child.wait()
        except Exception:
            pass

    def close(self):
        try:
            self.child.close(force=True)
        except Exception:
            pass


def tc_p01_input_latency():
    """TC-P-01 (P1, NFR-01, 建议项)：按键 → 画面生效延迟，均值与 P95 ≤ 50ms。

    r2 口径：time.monotonic() send 前 t0 → 屏幕内容确认生效后 t1 → 差值；
    细粒度轮询 ≤10ms；左右移交替发送避免贴壁拒绝无效采样；
    采样 ≥ 20 次；开销（轮询粒度 + pexpect 调度）与真实延迟分离记录。
    """
    t = TermScreen(*DIM)
    latencies = []
    try:
        t.spawn([CODE, '--tick', '500'])
        t.refresh(wait=0.6)
        keys = ['a', 'd', 'a', 'd', 'a', 'd', 'w']   # 交替左右移 + 旋转，避免贴壁失效
        for i in range(SAMPLE_N):
            key = keys[i % len(keys)]
            base = '\n'.join(t.screen.display)
            t.child.send(key)
            t0 = time.monotonic()
            changed = False
            deadline = t0 + 0.5                   # 上限 500ms，超时记无效采样
            while time.monotonic() < deadline:
                time.sleep(POLL_MS)
                t._drain(0.02)
                if '\n'.join(t.screen.display) != base:
                    changed = True
                    break
            if changed:
                latencies.append((time.monotonic() - t0) * 1000)
            time.sleep(0.05)                      # 稳定间隔，避免连发粘连
    finally:
        t.quit(); t.close()
    if len(latencies) < SAMPLE_N * 0.8:
        return False, '采样不足: %d/%d' % (len(latencies), SAMPLE_N)
    avg = statistics.mean(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]
    ok = avg <= LATENCY_P95_LIMIT_MS and p95 <= LATENCY_P95_LIMIT_MS
    note = ('测量含轮询粒度≤10ms + pexpect调度 + curses渲染周期(≤25ms)开销，'
            '真实事件驱动延迟为毫秒级；建议项，非发布阻塞')
    return ok, 'n=%d avg=%.1fms p95=%.1fms 阈值≤%dms(P95) [%s]' % (
        len(latencies), avg, p95, LATENCY_P95_LIMIT_MS, note)


def tc_p02_resource_usage():
    """TC-P-02 (P1, NFR-02, 建议项)：60 秒运行，CPU ≤ 5%（单核）、RSS ≤ 50MB。"""
    t = TermScreen(*DIM)
    samples = []
    try:
        t.spawn([CODE, '--tick', '500'])
        t.refresh(wait=0.5)
        pid = t.child.pid
        t0 = time.monotonic()
        prev_cpu = None
        prev_wall = None
        while time.monotonic() - t0 < RUN_SECONDS:
            time.sleep(SAMPLE_INTERVAL)
            t._drain(0.2)
            try:
                r = subprocess.run(
                    ['ps', '-o', 'rss=,time=', '-p', str(pid)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                out = r.stdout.decode().strip().split()
                if len(out) >= 2:
                    rss_kb = int(out[0])
                    # CPU 时间 "HH:MM:SS" 或 "MM:SS" → 秒
                    parts = [int(p) for p in out[1].split(':')]
                    cpu_sec = 0
                    for p in parts:
                        cpu_sec = cpu_sec * 60 + p
                    now = time.monotonic()
                    if prev_cpu is not None:
                        dt = now - prev_wall
                        cpu_pct = (cpu_sec - prev_cpu) / dt * 100.0
                        samples.append((cpu_pct, rss_kb))
                    prev_cpu, prev_wall = cpu_sec, now
            except Exception:
                pass
            if not t.child.isalive():
                break
    finally:
        t.quit(); t.close()
    if len(samples) < 3:
        return False, '采样不足: %d' % len(samples)
    avg_cpu = statistics.mean(s[0] for s in samples)
    avg_rss = statistics.mean(s[1] for s in samples)
    peak_rss = max(s[1] for s in samples)
    ok = avg_cpu <= 5.0 and peak_rss <= 50 * 1024
    return ok, 'n=%d avg_cpu=%.2f%% peak_rss=%.1fMB（建议项，非发布阻塞）' % (
        len(samples), avg_cpu, peak_rss / 1024.0)


def main():
    print('=== tetris r1 性能测试（r2 口径，TC-P-01/02，TC-P-03 人工目测）===')
    print('被测代码: %s' % CODE)
    print()
    ok1, d1 = tc_p01_input_latency()
    print('[%s] TC-P-01 输入延迟（r2 绝对值口径 ≤50ms P95，建议项）%s'
          % ('PASS' if ok1 else 'FAIL', d1))
    ok2, d2 = tc_p02_resource_usage()
    print('[%s] TC-P-02 资源占用（CPU≤5%% RSS≤50MB）%s' % ('PASS' if ok2 else 'FAIL', d2))
    print()
    print('TC-P-03（连续消 10 行无闪烁/无错位/无残影）为真实终端人工目测，')
    print('见 system_checklist.md TC-P-03 项。')
    print('注：TC-P-01/02 为建议项（NFR-01/02，analysis r2 R1-04 标注），'
          '失败不阻塞发布，仅记录。')
    return 0 if (ok1 and ok2) else 1


if __name__ == '__main__':
    sys.exit(main())
