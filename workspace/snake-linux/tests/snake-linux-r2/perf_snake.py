#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能测试：TC-P-01（输入延迟）/ TC-P-02（CPU/RSS 占用）。

对应测试方案 §5 的 `bash tests/perf_snake.sh`（pidstat 采样 + 延迟计时）——
本脚本为其实质实现：延迟测量用 pexpect PTY + 屏幕轮询；CPU/RSS 采样优先
pidstat（若可用），否则 ps 轮询兜底（pidstat 缺失不阻塞执行）。

依赖：pexpect（测试侧依赖）。
运行：python3 perf_snake.py [--duration 30]（或 bash perf_snake.sh）
退出码：0 = 指标达标；1 = 指标超标（记录缺陷单，不阻塞 P0/P1 功能门禁）。

判定口径（测试方案 TC-P-01/02）：
- TC-P-01（P1，NFR-01）：按键到转向生效延迟均值与 P95 <= 200ms（<= 1 tick）；
- TC-P-02（P1，NFR-02）：运行期 CPU 均值 <= 5%（单核）、RSS 均值 <= 50MB。
测试方案 §4/§6：性能指标受终端渲染与机器负载影响，P0 判定不依赖性能用例；
失败时记录缺陷单并在固定机复测。
"""
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

try:
    import pexpect
except ImportError:
    sys.stderr.write('缺少测试侧依赖 pexpect：pip install pexpect（仅测试环境需要）\n')
    sys.exit(2)

from miniterm import MiniTerm

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.abspath(os.path.join(TESTS_DIR, '..', '..', '..'))
SNAKE_PY = os.path.join(WORKSPACE_DIR, 'code', 'snake-linux', 'snake-linux-r1',
                        'snake.py')

DIR2KEY = {(0, -1): 'w', (0, 1): 's', (-1, 0): 'a', (1, 0): 'd'}
KEY2DIR = {v: k for k, v in DIR2KEY.items()}

# 顺时针键序：每个键与上一键方向垂直，保证不会触发 FR-07 反向禁止
CLOCKWISE_KEYS = ['w', 'd', 's', 'a']


def launch(args, cols=80, lines=30, timeout=30):
    env = dict(os.environ)
    env['TERM'] = 'xterm'
    child = pexpect.spawn(sys.executable, [SNAKE_PY] + args,
                          env=env, timeout=timeout)
    child.setwinsize(lines, cols)
    return child


def read_screen(child, mt, wait=0.04):
    end = time.time() + wait
    while time.time() < end:
        try:
            data = child.read_nonblocking(4096, 0.02)
            if data:
                mt.feed(data.decode('utf-8', 'replace'))
        except pexpect.TIMEOUT:
            pass
        except pexpect.EOF:
            break
    return mt


def wait_ui(child, mt, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        read_screen(child, mt, 0.1)
        if mt.find('O') and mt.find('*') and 'Score:' in mt.text():
            return True
    return False


def head_dir(child, mt):
    """读取当前蛇头移动方向向量：(vx, vy)。读不到返回 None。"""
    read_screen(child, mt, 0.05)
    a = mt.find('O')
    time.sleep(0.05)
    read_screen(child, mt, 0.05)
    b = mt.find('O')
    if a is None or b is None or a == b:
        return None
    return (b[0] - a[0], b[1] - a[1])


def pick_perpendicular(v):
    """选一个与当前方向 v 垂直的按键（顺时针序中第一个垂直者）。"""
    for k in CLOCKWISE_KEYS:
        d = KEY2DIR[k]
        if d[0] + v[0] == 0 and d[1] + v[1] == 0:
            continue        # 反向，跳过
        if d == v:
            continue        # 同向，跳过
        return k
    return None


def tc_p01(samples=20, max_seconds=90):
    """TC-P-01（P1，NFR-01）：按键 → 转向生效延迟（均值/P95 <= 200ms）。"""
    child = launch(['--tick', '200'])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return ('FAIL', '未出现界面', [])
    latencies = []
    start = time.time()
    while len(latencies) < samples and time.time() - start < max_seconds:
        v = head_dir(child, mt)
        if v is None:
            continue
        key = pick_perpendicular(v)
        if key is None:
            continue
        target = KEY2DIR[key]
        t0 = time.time()
        child.send(key)
        deadline = t0 + 1.0
        got = None
        while time.time() < deadline:
            v2 = head_dir(child, mt)
            if v2 == target:
                got = time.time() - t0
                break
        if got is not None:
            latencies.append(got)
    child.close(force=True)
    if len(latencies) < 15:
        return ('FAIL',
                '有效采样 {0}/{1}（<15，延迟无法统计）'.format(len(latencies), samples),
                latencies)
    mean = statistics.mean(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]
    detail = '均值 {0:.0f}ms / P95 {1:.0f}ms（采样 {2} 次）'.format(
        mean * 1000, p95 * 1000, len(latencies))
    if p95 > 0.200:
        return ('FAIL', detail + '（P95 > 200ms，超标）', latencies)
    if mean > 0.200:
        return ('FAIL', detail + '（均值 > 200ms，超标）', latencies)
    return ('PASS', detail, latencies)


def _ps_sample(pid, duration, interval):
    """ps 轮询采样：每 interval 秒读一次 %cpu 与 rss(KB)，返回 [(cpu%, rss_kb)]。"""
    samples = []
    end = time.time() + duration
    while time.time() < end:
        time.sleep(interval)
        try:
            out = subprocess.run(
                ['ps', '-o', '%cpu=,rss=', '-p', str(pid)],
                capture_output=True, text=True, timeout=5).stdout.strip()
        except subprocess.TimeoutExpired:
            continue
        parts = out.split()
        if len(parts) == 2:
            try:
                samples.append((float(parts[0]), int(parts[1])))
            except ValueError:
                pass
    return samples


def _pidstat_sample(pid, duration, interval):
    """pidstat 采样（若可用）：-u CPU / -r RSS(KB)，每 interval 秒一条。"""
    samples = []
    if not shutil.which('pidstat'):
        return samples
    try:
        out = subprocess.run(
            ['pidstat', '-p', str(pid), '-u', '-r', str(interval), str(duration)],
            capture_output=True, text=True, timeout=duration + 15).stdout
    except (subprocess.TimeoutExpired, OSError):
        return samples
    for line in out.splitlines():
        m = re.match(r'\s*\d+\s+\S+\s+\S+\s+\S+\s+([\d.]+)\s+\S+\s+([\d.]+)',
                     line)
        # pidstat 数据行: PID %usr %system %guest %CPU CPU ... 与 RSS 行不同，
        # 解析失败即跳过（ps 采样作兜底统计）
        parts = line.split()
        if len(parts) >= 8 and parts[0].isdigit():
            try:
                cpu = float(parts[4])          # %CPU 列（-u 输出）
            except ValueError:
                continue
            rss_kb = None
            if len(parts) >= 12:               # -r 追加列：RSS 在更后面
                try:
                    rss_kb = int(parts[10]) if re.match(r'^\d+$', parts[10]) else None
                except ValueError:
                    pass
            samples.append((cpu, rss_kb))
    return samples


def tc_p02(duration=30, interval=5):
    """TC-P-02（P1，NFR-02）：运行期 CPU <= 5%、RSS <= 50MB（均值）。"""
    child = launch(['--tick', '200'])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return ('FAIL', '未出现界面', [])
    pid = child.pid
    pid_samples = _pidstat_sample(pid, duration, interval)
    if not pid_samples or all(rss is None for _, rss in pid_samples):
        pid_samples = _ps_sample(pid, duration, interval)
    child.close(force=True)
    if not pid_samples:
        return ('FAIL', 'CPU/RSS 采样为空（pidstat 与 ps 均失败）', [])
    cpus = [c for c, _ in pid_samples if c is not None]
    rsses = [r for _, r in pid_samples if r is not None]
    if not cpus:
        return ('FAIL', '无 CPU 采样', [])
    cpu_avg = sum(cpus) / len(cpus)
    rss_avg_mb = (sum(rsses) / len(rsses)) / 1024.0 if rsses else None
    detail = 'CPU 均值 {0:.2f}% / RSS 均值 {1}（采样 {2} 点，{3}s 运行期）'.format(
        cpu_avg,
        '{0:.1f}MB'.format(rss_avg_mb) if rss_avg_mb is not None else 'N/A',
        len(pid_samples), duration)
    fails = []
    if cpu_avg > 5:
        fails.append('CPU {0:.2f}% > 5%'.format(cpu_avg))
    if rss_avg_mb is not None and rss_avg_mb > 50:
        fails.append('RSS {0:.1f}MB > 50MB'.format(rss_avg_mb))
    if fails:
        return ('FAIL', detail + '（' + '; '.join(fails) + '）', pid_samples)
    return ('PASS', detail, pid_samples)


def main():
    import argparse
    ap = argparse.ArgumentParser(prog='perf_snake.py',
                                 description='贪吃蛇性能测试（TC-P-01/02）')
    ap.add_argument('--duration', type=int, default=30,
                    help='TC-P-02 采样时长（秒），默认 30')
    ap.add_argument('--samples', type=int, default=20,
                    help='TC-P-01 延迟采样次数，默认 20')
    args = ap.parse_args()

    print('=' * 78)
    print('性能测试（测试方案 TC-P-01/02；TC-P-03 见 checklist-system.md 人工目测）')
    print('被测代码: {0}'.format(SNAKE_PY))
    print('=' * 78)

    st1, d1, _ = tc_p01(samples=args.samples)
    print('TC-P-01  [P1] 输入延迟（NFR-01，P95<=200ms）  {0}  --  {1}'.format(
        'PASS ' if st1 == 'PASS' else 'FAIL ', d1))

    st2, d2, _ = tc_p02(duration=args.duration)
    print('TC-P-02  [P1] CPU/RSS 占用（NFR-02，<=5%/<=50MB）  {0}  --  {1}'.format(
        'PASS ' if st2 == 'PASS' else 'FAIL ', d2))

    print('-' * 78)
    ok = st1 == 'PASS' and st2 == 'PASS'
    print('汇总: TC-P-01={0} TC-P-02={1}'.format(st1, st2))
    if ok:
        print('阻塞结论: PASS（性能指标达标）')
    else:
        print('阻塞结论: 不阻塞（P1 性能用例，按测试方案 §4/§6 记录缺陷单、'
              '固定机复测；P0 判定以功能用例为准）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
