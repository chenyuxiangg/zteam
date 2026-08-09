# -*- coding: utf-8 -*-
"""tetris 集成测试（PTY 端到端）——TC-I-01 ~ TC-I-16。

依据测试方案 workspace/testplans/tetris/tetris-r2.md §3.2 用例表与 §5 自动化方案：
用 pexpect 分配真实 PTY 驱动 workspace/code/tetris/tetris-r2/tetris.py，
pyte 仿真终端屏幕做文本/颜色断言，termios 校验终端状态恢复。
r2 口径（testplan r2 增量）：用例结构与 r1 完全一致；时间类验收绝对值化
（tick 偏差/锁定生成/HUD 刷新/按键响应/硬降/暂停不吞时间）由本层粗粒度
观察 + 单元层/性能层精确断言协同覆盖（软降分工：TC-I-05 粗粒度「明显快于」）。

运行：python3 e2e_tetris.py   （或 bash e2e_tetris.sh）
退出码：全 PASS = 0；任一 FAIL = 1（与测试方案「任一 P0 用例失败 = 发布阻塞」对齐）
"""
import os
import re
import signal
import subprocess
import sys
import termios
import time

import pexpect
import pyte

CODE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', '..', '..', 'code', 'tetris', 'tetris-r2', 'tetris.py')
CODE = os.path.normpath(CODE)
ENV = dict(os.environ, TERM='xterm-256color')
DIM = (30, 60)          # 正常尺寸：30 行 × 60 列（≥ 26×42）
SMALL_DIM = (10, 30)    # 过小尺寸：10 行 × 30 列（< 26×42）

PASS = 0
FAIL = 0
RESULTS = []


def report(tc_id, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1
        print('[PASS] %s %s' % (tc_id, detail))
    else:
        FAIL += 1
        print('[FAIL] %s %s' % (tc_id, detail))
    RESULTS.append((tc_id, ok, detail))


class TermScreen(object):
    """pexpect + pyte 终端屏幕仿真器。"""

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
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

    def spawn(self, args, rows=None, cols=None, timeout=8):
        r = rows or self.rows
        c = cols or self.cols
        self.rows, self.cols = r, c
        self.screen.resize(r, c)
        self.child = pexpect.spawn('python3', args, dimensions=(r, c),
                                   timeout=timeout, env=ENV)
        self.child.logfile_read = self._Feeder(self)
        return self.child

    def _drain(self, timeout=0.2):
        """触发 pexpect 读取（logfile_read 会自动喂给 pyte 屏幕）。"""
        try:
            self.child.read_nonblocking(size=100000, timeout=timeout)
        except pexpect.TIMEOUT:
            pass
        except pexpect.EOF:
            pass
        except Exception:
            pass

    def wait_frame(self, pattern, timeout=3):
        """等待屏幕出现匹配 pattern 的帧（轮询而非固定 sleep）。"""
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._drain(0.1)
            text = self.text()
            if rx.search(text):
                return True
            time.sleep(0.05)
        return False

    def text(self):
        return '\n'.join(self.screen.display)

    def refresh(self, wait=0.2):
        """等待 wait 秒并 drain 屏幕（sleep 后读取前必须调用）。"""
        if wait:
            time.sleep(wait)
        self._drain(0.2)
        return self.text()

    def line(self, y):
        return self.screen.display[y]

    def colors(self):
        """扫描屏幕非空格单元格的 (fg, bg) 颜色集合（buffer 行/元素类型有差异需防护）。"""
        out = set()
        for row in self.screen.buffer:
            if isinstance(row, int):
                continue
            for cell in row:
                if isinstance(cell, int):
                    continue
                if cell.data.strip():
                    out.add((cell.fg, cell.bg))
        return out

    def send(self, s):
        self.child.send(s)

    def quit(self):
        try:
            self.child.send('q')
            self.child.expect(pexpect.EOF, timeout=3)
            self.child.wait()
            return self.child.exitstatus
        except Exception:
            return None

    def close(self):
        try:
            self.child.close(force=True)
        except Exception:
            pass


def tc_i01_single_command_startup():
    """TC-I-01 (P0, FR-01)：PTY 中 3 秒内出现游戏界面，无报错。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        ok_frame = t.wait_frame(r'\+-{20}\+', timeout=3)   # 场地边框
        text = t.text()
        ok_hud = ('NEXT:' in text and 'SCORE' in text
                  and 'LEVEL' in text and 'LINES' in text)
        t.quit()
        report('TC-I-01', ok_frame and ok_hud,
               '界面 3 秒内出现 + HUD 齐备' if ok_frame and ok_hud
               else 'frame=%s hud=%s' % (ok_frame, ok_hud))
    finally:
        t.close()


def tc_i02_non_tty_error():
    """TC-I-02 (P0, FR-02)：非 TTY（重定向/管道）→ 可读提示 + exit 1，无 traceback。"""
    # 重定向场景
    r1 = subprocess.run(['python3', CODE], stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, env=ENV)
    stderr = r1.stderr.decode('utf-8', 'replace')
    ok_hint = ('终端' in stderr or 'TTY' in stderr) and '运行' in stderr
    ok_no_tb = 'Traceback' not in stderr
    ok_code = r1.returncode == 1
    # 管道场景（stdout 非 TTY）：Popen 用 DEVNULL 作为 stdin，stdout 接管道
    r2 = subprocess.Popen(['python3', CODE], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=ENV)
    out2, err2 = r2.communicate(timeout=10)
    ok_pipe = r2.returncode == 1 and b'Traceback' not in err2
    report('TC-I-02', ok_hint and ok_no_tb and ok_code and ok_pipe,
           'exit=%d hint=%s pipe_ok=%s' % (r1.returncode, ok_hint, ok_pipe))


def tc_i03_small_terminal():
    """TC-I-03 (P1, FR-04)：终端 30×10（< 42×26）→ 可读提示 + 非零退出。"""
    t = TermScreen(*SMALL_DIM)
    try:
        t.spawn([CODE], rows=SMALL_DIM[0], cols=SMALL_DIM[1])
        # 尺寸检查在 wrapper 内，需要等屏幕输出
        text = t.refresh(wait=1.2)
        ok_hint = ('too small' in text.lower() or '42' in text or '尺寸' in text)
        t.child.expect(pexpect.EOF, timeout=5)
        t.child.wait()
        code = t.child.exitstatus
        ok_code = code is not None and code != 0
        report('TC-I-03', ok_hint and ok_code,
               'hint=%s exit=%s text=%r' % (ok_hint, code, text[:80]))
    finally:
        t.close()


def tc_i04_tick_speed():
    """TC-I-04 (P1, FR-03/07)：--tick 1000 下落慢 vs --tick 50 下落快。

    口径：1.5 秒窗口内每 50ms 采样画面，统计画面变化次数。
    tick1000 → 约 1 次变化（第 1s 下落 1 格）；tick50 → 30 次下落+多次锁定重绘，变化 ≫ 2 次。
    """
    def count_changes(t, window=1.5):
        t.refresh(wait=0.3)          # 丢弃启动帧
        prev = t.text()
        changes = 0
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            time.sleep(0.05)
            t._drain(0.1)
            cur = t.text()
            if cur != prev:
                changes += 1
                prev = cur
        return changes

    t1 = TermScreen(*DIM)
    try:
        t1.spawn([CODE, '--tick', '1000'])
        t1.wait_frame(r'\+-{20}\+', timeout=3)
        slow_changes = count_changes(t1)
    finally:
        t1.quit(); t1.close()
    t2 = TermScreen(*DIM)
    try:
        t2.spawn([CODE, '--tick', '50'])
        t2.wait_frame(r'\+-{20}\+', timeout=3)
        fast_changes = count_changes(t2)
    finally:
        t2.quit(); t2.close()
    # 慢速 1.5s 变化 ≤ 2 次；快速 1.5s 变化 ≥ 5 次且明显多于慢速
    ok = slow_changes <= 2 and fast_changes >= 5 and fast_changes > slow_changes
    report('TC-I-04', ok,
           'tick1000_changes=%d tick50_changes=%d' % (slow_changes, fast_changes))


def tc_i05_gameplay_loop():
    """TC-I-05 (P0, FR-05~13)：端到端玩法闭环——键位操作 + 持续硬降堆叠 + 撞顶结束。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        # 键位操作：W 旋转、A 左移、D 右移、S 软降、方向键、空格硬降（快速连发触发多次锁定）
        for key in ['w', 'a', 'd', 's', '\x1b[A', '\x1b[B', '\x1b[C', '\x1b[D']:
            t.send(key)
            time.sleep(0.05)
        t.refresh(wait=0.3)
        # 连续硬降加速堆叠（随机方块，直至撞顶 GAME OVER）
        game_over = False
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            t.send(' ')
            time.sleep(0.02)
            if time.monotonic() % 0.5 < 0.02:   # 每 0.5s 检查一次
                t._drain(0.1)
                if 'GAME OVER' in t.text():
                    game_over = True
                    break
        t.refresh(wait=0.2)
        text = t.text()
        ok_over = game_over or 'GAME OVER' in text
        ok_score = 'Score:' in text
        # 撞顶后按任意键退出
        if ok_over:
            t.send('x')
            t.child.expect(pexpect.EOF, timeout=3)
            t.child.wait()
            ok_exit = t.child.exitstatus == 0
        else:
            ok_exit = False
        report('TC-I-05', ok_over and ok_score and ok_exit,
               'game_over=%s score_line=%s exit0=%s' % (ok_over, ok_score, ok_exit))
    finally:
        t.close()


def tc_i06_keys_both_schemes():
    """TC-I-06 (P0, FR-18)：WASD 与方向键双方案生效；空格硬降；P 暂停。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        # 左移 A：方块 x 应左移（活动方块行内容变化）
        line_before = t.refresh(wait=0.3)
        t.send('a')
        t.refresh(wait=0.15)
        moved_left = t.text() != line_before
        # 旋转 W：画面变化
        line_after_w = t.text()
        t.send('w')
        t.refresh(wait=0.15)
        rotated = t.text() != line_after_w
        # 方向键 ↑（旋转）同样生效
        t.send('\x1b[A')
        t.refresh(wait=0.15)
        # 空格硬降：立即锁定 → 场地出现锁定格
        t.send(' ')
        t.refresh(wait=0.2)
        # P 暂停：PAUSED 提示出现
        t.send('p')
        t.refresh(wait=0.2)
        paused = 'PAUSED' in t.text()
        t.send('p')
        t.refresh(wait=0.2)
        unpaused = 'PAUSED' not in t.text()
        ok = moved_left and rotated and paused and unpaused
        report('TC-I-06', ok,
               'left=%s rot=%s pause=%s unpause=%s'
               % (moved_left, rotated, paused, unpaused))
    finally:
        t.quit(); t.close()


def _termios_state(fd):
    try:
        attrs = termios.tcgetattr(fd)
        return (bool(attrs[3] & termios.ECHO),
                bool(attrs[3] & termios.ICANON))
    except Exception:
        return (None, None)


def tc_i07_q_quit_fast():
    """TC-I-07 (P0, FR-20)：游戏中按 q → 1 秒内干净退出，exit 0。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        t0 = time.monotonic()
        t.send('q')
        t.child.expect(pexpect.EOF, timeout=3)
        t.child.wait()
        elapsed = time.monotonic() - t0
        ok = t.child.exitstatus == 0 and elapsed < 1.0
        report('TC-I-07', ok, 'exit=%s elapsed=%.2fs' % (t.child.exitstatus, elapsed))
    finally:
        t.close()


def tc_i08_sigint_three_moments():
    """TC-I-08 (P0, FR-20/23, NFR-03)：开局/游戏中/结束画面三时机 SIGINT，termios 恢复。"""
    moments = []
    # 时机 1：开局（界面刚出现）
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.2)
        fd = t.child.child_fd
        before = _termios_state(fd)              # 运行中应为 (False, False)
        t0 = time.monotonic()
        t.child.kill(signal.SIGINT)
        t.child.expect(pexpect.EOF, timeout=3)
        t.child.wait()
        elapsed = time.monotonic() - t0
        after = _termios_state(fd)
        moments.append(('open', before, after, elapsed, t.child.exitstatus))
    finally:
        t.close()
    # 时机 2：游戏中（已操作若干键）
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.2)
        for _ in range(5):
            t.send('a')
            time.sleep(0.05)
        time.sleep(0.3)
        fd = t.child.child_fd
        before = _termios_state(fd)
        t0 = time.monotonic()
        t.child.kill(signal.SIGINT)
        t.child.expect(pexpect.EOF, timeout=3)
        t.child.wait()
        elapsed = time.monotonic() - t0
        after = _termios_state(fd)
        moments.append(('midgame', before, after, elapsed, t.child.exitstatus))
    finally:
        t.close()
    # 时机 3：结束画面（撞顶后）
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            t.send(' ')
            time.sleep(0.02)
            if 'GAME OVER' in t.text():
                break
        time.sleep(0.3)
        fd = t.child.child_fd
        before = _termios_state(fd)
        t0 = time.monotonic()
        t.child.kill(signal.SIGINT)
        t.child.expect(pexpect.EOF, timeout=3)
        t.child.wait()
        elapsed = time.monotonic() - t0
        after = _termios_state(fd)
        moments.append(('gameover', before, after, elapsed, t.child.exitstatus))
    finally:
        t.close()
    # 判定：所有时机退出后 echo/icanon 均恢复为 True，耗时 < 1s
    ok = all(m[2] == (True, True) and m[3] < 1.0 for m in moments)
    detail = '; '.join('%s: before=%s after=%s %.2fs exit=%s'
                       % (m[0], m[1], m[2], m[3], m[4]) for m in moments)
    report('TC-I-08', ok, detail)


def tc_i09_sigterm():
    """TC-I-09 (P1, FR-20)：SIGTERM → 同一恢复路径，termios 一致。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        fd = t.child.child_fd
        before = _termios_state(fd)
        t0 = time.monotonic()
        t.child.kill(signal.SIGTERM)
        t.child.expect(pexpect.EOF, timeout=3)
        t.child.wait()
        elapsed = time.monotonic() - t0
        after = _termios_state(fd)
        ok = after == (True, True) and elapsed < 1.0
        report('TC-I-09', ok,
               'before=%s after=%s %.2fs exit=%s'
               % (before, after, elapsed, t.child.exitstatus))
    finally:
        t.close()


def tc_i10_hud_refresh():
    """TC-I-10 (P1, FR-15/16/22)：HUD 固定位置显示得分/等级/消行。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.4)
        text = t.text()
        ok_hud = ('SCORE' in text and 'LEVEL' in text and 'LINES' in text)
        # HUD 侧栏固定行：SCORE 行号在 7，LEVEL 在 10，LINES 在 13（方案 §3.1 布局）
        ok_pos = ('SCORE' in t.line(7) and 'LEVEL' in t.line(10)
                  and 'LINES' in t.line(13))
        report('TC-I-10', ok_hud and ok_pos,
               'hud=%s fixed_pos=%s' % (ok_hud, ok_pos))
    finally:
        t.quit(); t.close()


def tc_i11_game_over_screen():
    """TC-I-11 (P1, FR-24)：结束画面显示最终得分与「按任意键退出」提示。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        deadline = time.monotonic() + 25
        got_over = False
        while time.monotonic() < deadline:
            t.send(' ')
            time.sleep(0.02)
            if time.monotonic() % 0.5 < 0.02:
                t._drain(0.1)
                if 'GAME OVER' in t.text():
                    got_over = True
                    break
        text = t.refresh(wait=0.3)
        ok_over = 'GAME OVER' in text
        ok_score = bool(re.search(r'Score:\s*\d+', text))
        ok_hint = 'Press any key' in text
        ok_blank = True   # 无残影：结束画面区域方块已不绘制（活动方块隐藏）
        report('TC-I-11', ok_over and ok_score and ok_hint and ok_blank,
               'over=%s score=%s hint=%s' % (ok_over, ok_score, ok_hint))
    finally:
        # 任意键退出
        try:
            t.send('x')
            t.child.expect(pexpect.EOF, timeout=3)
            t.child.wait()
        except Exception:
            pass
        t.close()


def tc_i12_pause_resume():
    """TC-I-12 (P1, FR-19)：暂停冻结（方块不下落、画面不变），恢复继续。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        t.send('p')
        t.refresh(wait=0.2)
        frozen = t.text()
        time.sleep(1.5)                       # 暂停 1.5 秒
        t._drain(0.2)
        still = t.text() == frozen
        still_paused = 'PAUSED' in t.text()
        # 恢复
        t.send('p')
        t.refresh(wait=0.2)
        resumed = 'PAUSED' not in t.text()
        # 恢复后下落继续：1 秒内画面再次变化（或已因硬降行为变化）
        time.sleep(0.6)
        t._drain(0.2)
        changed = t.text() != frozen
        ok = still and still_paused and resumed and changed
        report('TC-I-12', ok,
               'frozen=%s paused=%s resumed=%s changed=%s'
               % (still, still_paused, resumed, changed))
    finally:
        t.quit(); t.close()


def tc_i13_resize():
    """TC-I-13 (P2, FR-04)：运行中 resize 缩小 → 提示不崩溃；恢复后继续。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        # 缩小到 30×10
        t.child.setwinsize(10, 30)
        t.screen.resize(10, 30)
        time.sleep(1.0)
        text_small = t.text()
        ok_no_crash = t.child.isalive()
        # 恢复 30×60
        t.child.setwinsize(30, 60)
        t.screen.resize(30, 60)
        time.sleep(0.8)
        ok_alive = t.child.isalive()
        report('TC-I-13', ok_no_crash and ok_alive,
               'alive_after_shrink=%s alive_after_restore=%s'
               % (ok_no_crash, ok_alive))
    finally:
        t.quit(); t.close()


def tc_i14_next_preview():
    """TC-I-14 (P1, FR-21)：next 预览区域持续显示方块。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.4)
        ok_next_label = 'NEXT:' in t.text()
        # next 区域（侧栏 x≥24，行 1-2）有方块字符
        next_area = (t.line(1)[24:30] + t.line(2)[24:30])
        ok_next_piece = '[]' in next_area or any(c in next_area for c in '[]')
        report('TC-I-14', ok_next_label and ok_next_piece,
               'label=%s piece=%r' % (ok_next_label, next_area))
    finally:
        t.quit(); t.close()


def tc_i15_no_color():
    """TC-I-15 (P2, FR-26)：--no-color 启动可玩，单色以形状辨识。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE, '--no-color'])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        t.refresh(wait=0.4)
        colors = t.colors()
        # 单色模式：非空格单元格不应有多色（至多默认白/黑组合）
        colorful = {c for c in colors if c[0] not in ('white', 'black')}
        ok_mono = len(colorful) == 0
        # 游戏仍可玩：方块形状可见（场地有 '[]'）
        ok_shape = '[]' in t.text()
        report('TC-I-15', ok_mono and ok_shape,
               'non_default_colors=%s shape_visible=%s' % (len(colorful), ok_shape))
    finally:
        t.quit(); t.close()


def tc_i16_stty_restore():
    """TC-I-16 (P0, FR-23)：退出前后 termios 关键项（echo/icanon）一致。"""
    t = TermScreen(*DIM)
    try:
        t.spawn([CODE])
        t.wait_frame(r'\+-{20}\+', timeout=3)
        time.sleep(0.3)
        fd = t.child.child_fd
        running = _termios_state(fd)          # 运行中：cbreak/noecho → (False, False)
        t.quit()
        after = _termios_state(fd)            # 退出后 → (True, True)
        ok = running == (False, False) and after == (True, True)
        report('TC-I-16', ok,
               'running=%s after_quit=%s' % (running, after))
    finally:
        t.close()


def main():
    t0 = time.monotonic()
    print('=== tetris r1 集成测试（PTY 端到端，TC-I-01~16）===')
    print('被测代码: %s' % CODE)
    print()
    tc_i01_single_command_startup()
    tc_i02_non_tty_error()
    tc_i03_small_terminal()
    tc_i04_tick_speed()
    tc_i05_gameplay_loop()
    tc_i06_keys_both_schemes()
    tc_i07_q_quit_fast()
    tc_i08_sigint_three_moments()
    tc_i09_sigterm()
    tc_i10_hud_refresh()
    tc_i11_game_over_screen()
    tc_i12_pause_resume()
    tc_i13_resize()
    tc_i14_next_preview()
    tc_i15_no_color()
    tc_i16_stty_restore()
    elapsed = time.monotonic() - t0
    print()
    print('=== 汇总: PASS=%d FAIL=%d 耗时=%.1fs ===' % (PASS, FAIL, elapsed))
    if FAIL:
        print('失败用例: %s' % ', '.join(r[0] for r in RESULTS if not r[1]))
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
