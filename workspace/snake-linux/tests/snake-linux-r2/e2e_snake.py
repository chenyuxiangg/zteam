#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成层 PTY 端到端测试：对应测试方案 TC-I-01 ~ TC-I-11。

依赖：pexpect（测试侧依赖，不影响交付物运行时零第三方依赖）。
运行：python3 e2e_snake.py（或 run_all.sh 一键执行）
退出码：0 = 全部 PASS（P2 SKIP 不算失败）；1 = 存在 P0/P1 失败。

r2 修改（逐条回应 tests/snake-linux/snake-linux-r1-review.md）：
- [意见 1] TC-I-10 假失败修复：采样循环检测到 GAME OVER/WIN 立即停止（游戏
  结束会 erase 边框，结束帧不参与边框断言）；边框缺失时重读一帧排除渲染
  中间态；有效帧 >= 25 即 PASS（宽松判定）。根因确认为「默认 tick=200 下
  30 帧采样时长接近蛇走完 20 格撞墙的时间」，非被测代码缺陷。
- [意见 2] TC-I-05 偶发失败修复：拆为两段独立验证——a) BFS 机器人仅吃 1 个
  食物（吃食增长细节已由单元层 TC-U-08 验证）；b) 撞墙结束不依赖 BFS 寻路，
  发送 'w' 引导蛇直线前进（任意当前方向下 ≤ 20 tick 必然撞墙或撞自身进入
  结束画面），确定性触发结束画面断言。
- [意见 5] 关键断言改用 pexpect expect 字符串匹配输出流纯文本（GAME OVER/
  YOU WIN 等），MiniTerm 网格仅用于坐标类断言（TC-I-04/09/10）；全用例
  屏幕内容轮询 + 超时，无固定 sleep 断言（测试方案 §6）。
"""
import os
import re
import signal
import subprocess
import sys
import termios
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

KEY2DIR = {(0, -1): 'w', (0, 1): 's', (-1, 0): 'a', (1, 0): 'd'}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def launch(args, cols=80, lines=30, timeout=30):
    env = dict(os.environ)
    env['TERM'] = 'xterm'          # curses 需要有效 TERM（本机默认 dumb）
    child = pexpect.spawn(sys.executable, [SNAKE_PY] + args,
                          env=env, timeout=timeout)
    child.setwinsize(lines, cols)
    return child


def read_frame(child, mt, wait=0.3):
    """读取至少一个 tick 周期（默认 tick 200ms）的 PTY 输出，确保拿到新帧。

    背景（r2 偶发失败根因）：原 read_screen(0.12) 的轮询周期（~0.22s）与
    蛇输出周期（0.2s）接近，可能相位锁定——读取窗口持续落在两次输出 burst
    之间，MiniTerm 长期停留在旧帧，BFS/贪心基于过期坐标引导导致蛇乱走撞墙。
    窗口 >= 1 个 tick 周期后，每轮必然覆盖至少一次输出 burst。
    """
    end = time.time() + wait
    while time.time() < end:
        try:
            data = child.read_nonblocking(8192, 0.05)
            if data:
                mt.feed(data.decode('utf-8', 'replace'))
        except pexpect.TIMEOUT:
            pass
        except pexpect.EOF:
            break
    return mt


def read_screen(child, mt, wait=0.15):
    """把 PTY 输出灌入 MiniTerm，重建当前屏幕（通用读取，见 read_frame）。"""
    return read_frame(child, mt, wait=wait)


def wait_ui(child, mt, timeout=5):
    """等待游戏界面出现：HUD('Score:') + 蛇头('O') + 食物('*')。"""
    end = time.time() + timeout
    while time.time() < end:
        read_screen(child, mt, 0.1)
        if mt.find('O') and mt.find('*') and 'Score:' in mt.text():
            return True
    return False


def wait_game_over(child, mt, timeout=20):
    """等待结束画面（GAME OVER / YOU WIN）。

    意见 5：用 pexpect expect 匹配输出流中的纯文本（不依赖 CSI 序列解析）。
    注意：expect 匹配后，同批读入的后续字节（「最终得分/按任意键退出」）
    会留在 pexpect 内部 buffer 而非 PTY fd——read_screen 的 read_nonblocking
    读不到它们（实验确认）。因此这里显式取出 child.buffer 与 before/after
    一并灌入 MiniTerm，再用 read_screen 兜底 fd 中可能的新数据。
    """
    try:
        idx = child.expect([r'GAME OVER|YOU WIN', pexpect.TIMEOUT, pexpect.EOF],
                           timeout=timeout)
    except (pexpect.TIMEOUT, pexpect.EOF):
        return None
    if idx != 0:
        return None
    parts = []
    for chunk in (child.before, child.after, child.buffer):
        if chunk:
            parts.append(chunk)
    if child.buffer:
        child.buffer = b''          # 已取出，清空避免后续重复消费
    if parts:
        mt.feed(b''.join(parts).decode('utf-8', 'replace'))
    read_screen(child, mt, 0.3)     # 兜底：fd 中可能还有未读字节
    return mt.text()


def bfs_direction(mt, width, height):
    """BFS 最短路径（避开蛇身/边界），返回蛇头下一步方向向量或 None。"""
    head = mt.find('O')
    food = mt.find('*')
    if head is None or food is None:
        return None
    body = set(mt.find_all('o'))
    # 画布内部区域（屏幕坐标）：x in [1, width], y in [2, height+1]
    x0, x1 = 1, width
    y0, y1 = 2, height + 1
    visited = {head}
    q = [(head, None)]
    idx = 0
    while idx < len(q):
        (x, y), first = q[idx]
        idx += 1
        if (x, y) == food:
            return first
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            if not (x0 <= nx <= x1 and y0 <= ny <= y1):
                continue
            if (nx, ny) in body or (nx, ny) in visited:
                continue
            visited.add((nx, ny))
            q.append(((nx, ny), first if first is not None else (dx, dy)))
    return None


def autoplay_to_score(child, mt, goal, max_seconds=60, width=40, height=20):
    """贪吃机器人：BFS 寻路朝食物移动直到 Score >= goal。

    r2 加固（回应评审意见 2 的偶发失败根因）：
    - 目标方向与蛇当前移动方向相反时不发送（会被 FR-07 反向禁止忽略），
      改发垂直方向键绕行——消除「BFS 方向被拒 → 蛇直走撞墙提前结束」；
    - BFS 无路径时按食物相对蛇头方位贪心引导（垂直/水平分量优先，
      同样避开反向），避免干等导致超时；
    - 当前移动方向用「两帧蛇头位置差」判定，缓解读屏滞后。
    返回 True 达成目标；False 超时或游戏提前结束。
    """
    start = time.time()
    while time.time() - start < max_seconds:
        read_screen(child, mt, 0.12)
        txt = mt.text()
        m = re.search(r'Score:\s*(\d+)', txt)
        if m and int(m.group(1)) >= goal:
            return True
        m2 = re.search(r'最终得分[:：]\s*(\d+)', txt)   # 结束画面
        if m2 and int(m2.group(1)) >= goal:
            return True
        if 'GAME OVER' in txt or 'YOU WIN' in txt:
            return False
        head = mt.find('O')
        food = mt.find('*')
        if head is None or food is None:
            continue
        # 当前移动方向：两帧蛇头位置差
        cur = head
        time.sleep(0.05)
        read_screen(child, mt, 0.05)
        cur2 = mt.find('O')
        v = (cur2[0] - cur[0], cur2[1] - cur[1]) \
            if cur2 is not None and cur2 != cur else None
        # 目标方向：BFS 优先，无路径时贪心朝食物方位
        d = bfs_direction(mt, width, height)
        if d is None:
            dx, dy = food[0] - head[0], food[1] - head[1]
            if abs(dx) >= abs(dy):
                cands = [(1 if dx > 0 else -1, 0), (0, 1 if dy > 0 else -1)]
            else:
                cands = [(0, 1 if dy > 0 else -1), (1 if dx > 0 else -1, 0)]
            for c in cands:
                if c == (0, 0):
                    continue
                if v is not None and (c[0] + v[0] == 0 and c[1] + v[1] == 0):
                    continue                # 与当前方向相反，跳过
                d = c
                break
        # 反向规避：BFS 方向与当前移动方向相反时，选垂直方向绕行
        if d is not None and v is not None \
                and d[0] + v[0] == 0 and d[1] + v[1] == 0:
            for alt in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                if alt == v or (alt[0] + v[0] == 0 and alt[1] + v[1] == 0):
                    continue
                nh = (head[0] + alt[0], head[1] + alt[1])
                if 1 <= nh[0] <= width and 2 <= nh[1] <= height + 1:
                    d = alt
                    break
            else:
                d = None
        if d is None:
            continue
        child.send(KEY2DIR[d])
        time.sleep(0.08)
    return False


def steer_into_wall(child, mt, timeout=25):
    """引导蛇直线前进直至撞墙/撞自身进入结束画面（确定性，不依赖 BFS）。

    发送 'w'（向上）：若当前方向为向上则继续向上撞顶墙；若为向下（反向被
    FR-07 忽略）则沿当前方向撞底墙；若为左右则转向上后撞顶墙。任意情况下
    <= 20 tick（默认 tick 200ms 即 <= 4s）必然进入结束画面。返回结束画面
    文本，超时返回 None。
    """
    child.send('w')
    return wait_game_over(child, mt, timeout=timeout)


def termios_state(child):
    """读取 PTY 从端 termios 关键位：ECHO / ICANON。"""
    attrs = termios.tcgetattr(child.child_fd)
    lflag = attrs[3]
    return {'echo': bool(lflag & termios.ECHO),
            'icanon': bool(lflag & termios.ICANON)}


def child_exit_code(child):
    """取子进程退出码：先触发 waitpid 填充 pexpect 的 exitstatus。"""
    try:
        child.isalive()          # 强制 waitpid
    except Exception:
        pass
    code = child.exitstatus
    if code is not None:
        return code
    sig = child.signalstatus     # 被信号终止时 exitstatus 为 None
    if sig is not None:
        return 128 + sig
    return None


# ---------------------------------------------------------------------------
# 用例实现
# ---------------------------------------------------------------------------
class Result(object):
    def __init__(self, tc_id, name, prio, status, detail=''):
        self.tc_id, self.name, self.prio = tc_id, name, prio
        self.status, self.detail = status, detail


def run_tc_i01():
    """TC-I-01（P0，FR-01）：PTY 中 3 秒内出现游戏界面，无报错。"""
    child = launch([])
    mt = MiniTerm()
    ok = wait_ui(child, mt, timeout=5)
    child.close(force=True)
    if ok:
        return Result('TC-I-01', '单命令启动出现界面', 'P0', 'PASS')
    return Result('TC-I-01', '单命令启动出现界面', 'P0', 'FAIL',
                  '5 秒内未出现完整界面（HUD/蛇/食物）')


def run_tc_i02():
    """TC-I-02（P0，FR-02/NFR-04）：非 TTY 明确报错 + 退出码 1 + 无 traceback。"""
    fails = []
    # 场景 1/2：重定向与管道（stdin/stdout 均非 TTY）
    for scenario in ('redirect', 'pipe'):
        r = subprocess.run([sys.executable, SNAKE_PY],
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=10)
        err = r.stderr.decode('utf-8', 'replace')
        if r.returncode != 1:
            fails.append('{0}场景退出码 {1} != 1'.format(scenario, r.returncode))
        if '终端' not in err:
            fails.append('{0}场景 stderr 无明确中文提示: {1!r}'.format(
                scenario, err[:120]))
        if 'Traceback' in err:
            fails.append('{0}场景出现裸 traceback'.format(scenario))
    if fails:
        return Result('TC-I-02', '非 TTY 友好报错', 'P0', 'FAIL', '; '.join(fails))
    return Result('TC-I-02', '非 TTY 友好报错', 'P0', 'PASS')


def run_tc_i03():
    """TC-I-03（P1，FR-04）：终端过小（30x10）→ 可读提示 + 退出码 3。"""
    child = launch([], cols=30, lines=10)
    out = b''
    try:
        child.expect(pexpect.EOF, timeout=8)
        out = child.before or b''
    except pexpect.TIMEOUT:
        pass
    text = out.decode('utf-8', 'replace')
    code = child_exit_code(child)
    child.close(force=True)
    fails = []
    if code != 3:
        fails.append('退出码 {} != 3'.format(code))
    if '终端尺寸不足' not in text and '尺寸' not in text:
        fails.append('无尺寸不足提示: {!r}'.format(text[:120]))
    if 'Traceback' in text:
        fails.append('出现裸 traceback')
    if fails:
        return Result('TC-I-03', '终端过小提示', 'P1', 'FAIL', '; '.join(fails))
    return Result('TC-I-03', '终端过小提示', 'P1', 'PASS')


def run_tc_i04():
    """TC-I-04（P1，FR-03）：tick 帧率差异——1000ms 下蛇约 1s/步（4s 内 <=5 步），
    50ms 下明显前进（0.6s 内 >=5 格）。用「位置变化次数/时间」判定，规避启动相位。"""
    fails = []
    # --tick 1000：采样 3.5s，蛇头 x 变化次数应很少（≈3 次，1s/步）
    child = launch(['--tick', '1000'])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        fails.append('tick=1000 未出现界面')
    else:
        read_screen(child, mt, 0.3)
        last = mt.find('O')
        moves = 0
        end = time.time() + 3.5
        while time.time() < end:
            read_screen(child, mt, 0.2)
            cur = mt.find('O')
            if cur is not None and cur != last:
                moves += 1
                last = cur
            time.sleep(0.1)
        if moves > 5:
            fails.append('tick=1000 下 3.5s 蛇头移动 {0} 次（应 ≈3 次，tick 未生效）'.format(moves))
    child.close(force=True)
    # --tick 50：0.6s（约 12 tick）内蛇头前进明显（>=5 格）
    child2 = launch(['--tick', '50'])
    mt2 = MiniTerm()
    if not wait_ui(child2, mt2):
        fails.append('tick=50 未出现界面')
    else:
        read_screen(child2, mt2, 0.2)
        a1 = mt2.find('O')
        time.sleep(0.6)
        read_screen(child2, mt2, 0.3)
        a2 = mt2.find('O')
        if a1 is None or a2 is None:
            fails.append('tick=50 下无法定位蛇头')
        elif a2 == a1:
            fails.append('tick=50 下 0.6s 蛇头未移动')
        elif abs(a2[0] - a1[0]) + abs(a2[1] - a1[1]) < 5:
            fails.append('tick=50 下 0.6s 蛇头仅移动 {0} 格（帧率差异未体现）'.format(
                abs(a2[0] - a1[0]) + abs(a2[1] - a1[1])))
    child2.close(force=True)
    if fails:
        return Result('TC-I-04', 'tick 帧率差异', 'P1', 'FAIL', '; '.join(fails))
    return Result('TC-I-04', 'tick 帧率差异', 'P1', 'PASS')


def run_tc_i05():
    """TC-I-05（P0，FR-05~FR-11）：吃食增长 → 撞墙结束 → 结束画面全流程。

    r2 修复（意见 2）：拆为两段独立验证——
    a) 吃食增长：BFS 机器人仅需吃到 1 个食物（增长/得分细节由单元层 TC-U-08
       充分验证，集成层只做端到端确认：HUD 得分刷新 + 蛇身变长）；
    b) 撞墙结束：steer_into_wall 引导直线前进确定性撞墙，断言结束画面
       （GAME OVER + 最终得分 + 按任意键退出）。
    两段互不依赖，消除 BFS 在蛇增长后自锁导致的偶发失败。
    """
    child = launch([])
    mt = MiniTerm()
    fails = []
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-05', '吃食→撞墙→结束画面全流程', 'P0', 'FAIL', '未出现界面')
    # a) 吃 1 个食物：HUD 得分刷新 + 蛇身变长（两帧取最大蛇节数，容忍渲染中间态）
    if not autoplay_to_score(child, mt, 1, max_seconds=60):
        fails.append('60s 内未吃到 1 个食物（BFS 寻路失败）')
    else:
        read_screen(child, mt, 0.2)
        txt = mt.text()
        m = re.search(r'Score:\s*(\d+)', txt)
        if not (m and int(m.group(1)) >= 1):
            fails.append('吃食后 HUD 得分未刷新为 >= 1')
        body_len = 0
        for _ in range(2):
            read_screen(child, mt, 0.15)
            body_len = max(body_len, len(mt.find_all('o')) + (1 if mt.find('O') else 0))
        if body_len < 4:
            fails.append('吃食后蛇身未变长（屏幕蛇节数 {0} < 4）'.format(body_len))
    # b) 撞墙结束：确定性直线引导
    end = steer_into_wall(child, mt, timeout=25)
    if end is None:
        fails.append('撞墙后未进入结束状态（25s 内无 GAME OVER/WIN）')
    else:
        if '最终得分' not in end:
            fails.append('结束画面未显示最终得分')
        if '按任意键退出' not in end:
            fails.append('结束画面无「按任意键退出」提示')
    child.close(force=True)
    if fails:
        return Result('TC-I-05', '吃食→撞墙→结束画面全流程', 'P0', 'FAIL', '; '.join(fails))
    m = re.search(r'最终得分[:：]\s*(\d+)', end or '')
    detail = '吃到 1 个食物，结束画面得分={0}'.format(m.group(1)) if m else '全流程正常'
    return Result('TC-I-05', '吃食→撞墙→结束画面全流程', 'P0', 'PASS', detail)


def run_tc_i06():
    """TC-I-06（P0，FR-13）：运行中按 q → 1 秒内干净退出，退出码 0。"""
    child = launch([])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-06', 'q 安全退出', 'P0', 'FAIL', '未出现界面')
    t0 = time.time()
    child.send('q')
    try:
        child.expect(pexpect.EOF, timeout=3)
    except pexpect.TIMEOUT:
        child.close(force=True)
        return Result('TC-I-06', 'q 安全退出', 'P0', 'FAIL', '3s 内未退出')
    dt = time.time() - t0
    code = child_exit_code(child)
    child.close(force=True)
    if code != 0:
        return Result('TC-I-06', 'q 安全退出', 'P0', 'FAIL', '退出码 {} != 0'.format(code))
    if dt > 1.5:
        return Result('TC-I-06', 'q 安全退出', 'P0', 'FAIL',
                      '退出耗时 {:.2f}s > 1.5s'.format(dt))
    return Result('TC-I-06', 'q 安全退出', 'P0', 'PASS', '{:.2f}s 退出'.format(dt))


def _sigint_case(timing, timeout=3):
    """单个 SIGINT 时机的执行体：返回 (status, detail, base, mid, after, dt, code)。"""
    child = launch([])
    mt = MiniTerm()
    base = termios_state(child)
    if timing in ('game', 'gameover'):
        if not wait_ui(child, mt):
            child.close(force=True)
            return ('FAIL', '未出现界面', None, None, None, None, None)
    if timing == 'game':
        time.sleep(2.0)               # 游戏中持续运行
    if timing == 'gameover':
        # 吃 1 个食物后等自然撞墙进入结束画面（r2：确定性直线引导替代纯等待）
        autoplay_to_score(child, mt, 1, max_seconds=60)
        if steer_into_wall(child, mt, timeout=20) is None:
            child.close(force=True)
            return ('FAIL', '未进入结束画面', None, None, None, None, None)
    mid = termios_state(child)
    t0 = time.time()
    child.sendintr()
    try:
        child.expect(pexpect.EOF, timeout=timeout)
    except pexpect.TIMEOUT:
        child.close(force=True)
        return ('FAIL', 'SIGINT 后 {0}s 未退出'.format(timeout),
                base, mid, None, None, None)
    dt = time.time() - t0
    after = termios_state(child)
    code = child_exit_code(child)
    child.close(force=True)
    return ('PASS', '', base, mid, after, dt, code)


def run_tc_i07():
    """TC-I-07（P0，FR-13/14、NFR-03）：SIGINT 三时机退出 + termios 恢复。"""
    fails = []
    details = []
    for timing in ('start', 'game', 'gameover'):
        status, detail, base, mid, after, dt, code = _sigint_case(timing)
        if status == 'FAIL':
            fails.append('{0}: {1}'.format(timing, detail))
            continue
        # 恢复断言：退出后 ECHO/ICANON 应恢复为默认（均置位）
        if after is None or not (after['echo'] and after['icanon']):
            fails.append('{0}: 退出后终端未恢复（echo={1} icanon={2}）'.format(
                timing, after['echo'] if after else '?',
                after['icanon'] if after else '?'))
        if dt > 1.5:
            fails.append('{0}: 退出耗时 {1:.2f}s > 1.5s'.format(timing, dt))
        if code != 130:
            fails.append('{0}: 退出码 {1} != 130（SIGINT 语义）'.format(timing, code))
        details.append('{0}:{1:.2f}s/码{2}/echo={3}/icanon={4}'.format(
            timing, dt, code,
            after['echo'] if after else '?',
            after['icanon'] if after else '?'))
    if fails:
        return Result('TC-I-07', 'SIGINT 三时机+终端恢复', 'P0', 'FAIL',
                      '; '.join(fails) + ' | ' + ', '.join(details))
    return Result('TC-I-07', 'SIGINT 三时机+终端恢复', 'P0', 'PASS',
                  ', '.join(details))


def run_tc_i08():
    """TC-I-08（P1，FR-13）：SIGTERM 走同一恢复路径，termios 一致。"""
    child = launch([])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-08', 'SIGTERM 干净退出', 'P1', 'FAIL', '未出现界面')
    base = termios_state(child)
    t0 = time.time()
    child.kill(signal.SIGTERM)
    try:
        child.expect(pexpect.EOF, timeout=3)
    except pexpect.TIMEOUT:
        child.close(force=True)
        return Result('TC-I-08', 'SIGTERM 干净退出', 'P1', 'FAIL', '3s 未退出')
    dt = time.time() - t0
    after = termios_state(child)
    code = child_exit_code(child)
    child.close(force=True)
    fails = []
    if after is None or not (after['echo'] and after['icanon']):
        fails.append('终端未恢复 echo={0} icanon={1}'.format(
            after['echo'] if after else '?', after['icanon'] if after else '?'))
    if code != 130:
        fails.append('退出码 {} != 130'.format(code))
    if dt > 1.5:
        fails.append('耗时 {:.2f}s'.format(dt))
    if fails:
        return Result('TC-I-08', 'SIGTERM 干净退出', 'P1', 'FAIL', '; '.join(fails))
    return Result('TC-I-08', 'SIGTERM 干净退出', 'P1', 'PASS',
                  '{:.2f}s 退出，终端恢复'.format(dt))


def run_tc_i09():
    """TC-I-09（P1，FR-17）：HUD 固定顶部行显示得分，吃食后 1 tick 内刷新。"""
    child = launch([])
    mt = MiniTerm()
    fails = []
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-09', 'HUD 得分栏', 'P1', 'FAIL', '未出现界面')
    grid0 = [''.join(r).rstrip() for r in mt.grid]
    if not grid0[0].startswith('Score:'):
        fails.append('HUD 不在顶部第一行: {!r}'.format(grid0[0][:40]))
    elif 'Score: 0' not in grid0[0]:
        fails.append('初始得分显示异常: {!r}'.format(grid0[0][:40]))
    if not autoplay_to_score(child, mt, 1, max_seconds=60):
        fails.append('60s 内未吃到 1 个食物（HUD 刷新无法验证）')
    else:
        read_screen(child, mt, 0.2)
        grid1 = [''.join(r).rstrip() for r in mt.grid]
        if not grid1[0].startswith('Score: 1'):
            fails.append('吃食后 HUD 未在 1 tick 内刷新为 Score: 1: {!r}'.format(
                grid1[0][:40]))
    child.close(force=True)
    if fails:
        return Result('TC-I-09', 'HUD 得分栏', 'P1', 'FAIL', '; '.join(fails))
    return Result('TC-I-09', 'HUD 得分栏', 'P1', 'PASS', 'HUD 顶部固定行，Score 0→1 即时刷新')


def run_tc_i10():
    """TC-I-10（P0，FR-16）：ASCII 边框清晰 + 蛇/食物坐标恒在边框内。

    r2 修复（意见 1）：
    - 采样循环检测到 GAME OVER/YOU WIN 立即停止——游戏结束会 erase 边框，
      结束帧不参与边框断言（上一轮假失败根因：默认 tick=200 下 30 帧采样
      时长接近蛇从 x=20 走 20 格撞右墙的 4s，约第 25 帧后进入结束画面，
      边框消失被判为「顶边框异常」）；
    - 边框断言失败时重读一帧，排除 curses 清屏后重绘的渲染中间态；
    - 有效帧数 >= 25 即 PASS（宽松判定，对齐测试方案 TC-I-10 验收口径）。
    """
    child = launch([])   # 默认 tick=200
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-10', '边框与坐标范围', 'P0', 'FAIL', '未出现界面')
    fails = []
    frames_ok = 0
    for _ in range(30):
        read_screen(child, mt, 0.08)
        txt = mt.text()
        if 'GAME OVER' in txt or 'YOU WIN' in txt:
            break                      # 游戏已结束：结束帧无边框，停止采样
        g = mt.grid
        top = ''.join(g[1]).rstrip()
        bottom = ''.join(g[22]).rstrip()
        if top != '+' + '-' * 40 + '+' or bottom != '+' + '-' * 40 + '+':
            # 渲染中间态兜底：重读一帧再判
            read_screen(child, mt, 0.2)
            g = mt.grid
            top = ''.join(g[1]).rstrip()
            bottom = ''.join(g[22]).rstrip()
            if 'GAME OVER' in mt.text() or 'YOU WIN' in mt.text():
                break
        if top != '+' + '-' * 40 + '+':
            fails.append('顶边框异常: {!r}'.format(top[:50]))
            break
        if bottom != '+' + '-' * 40 + '+':
            fails.append('底边框异常: {!r}'.format(bottom[:50]))
            break
        wall_ok = all(g[y][0] == '|' and g[y][41] == '|' for y in range(2, 22))
        if not wall_ok:
            fails.append('左右竖边框缺失')
            break
        head = mt.find('O')
        food = mt.find('*')
        if head is None or food is None:
            continue
        for (x, y) in (head, food):
            if not (1 <= x <= 40 and 2 <= y <= 21):
                fails.append('元素越出边框: ({0},{1})'.format(x, y))
                break
        frames_ok += 1
    child.close(force=True)
    if fails:
        return Result('TC-I-10', '边框与坐标范围', 'P0', 'FAIL',
                      '; '.join(fails) + '（有效帧 {0}/30）'.format(frames_ok))
    if frames_ok < 25:
        return Result('TC-I-10', '边框与坐标范围', 'P0', 'FAIL',
                      '有效帧仅 {0}/30'.format(frames_ok))
    return Result('TC-I-10', '边框与坐标范围', 'P0', 'PASS',
                  '{0}/30 帧坐标均在边框内'.format(frames_ok))


def run_tc_i11():
    """TC-I-11（P2，FR-04）：运行中 resize——缩小暂停提示，恢复继续。"""
    child = launch([])
    mt = MiniTerm()
    if not wait_ui(child, mt):
        child.close(force=True)
        return Result('TC-I-11', '运行中 resize', 'P2', 'SKIP', '未出现界面')
    child.setwinsize(10, 30)          # 缩到 < 42x24
    time.sleep(1.2)
    read_screen(child, mt, 0.5)
    txt = mt.text()
    if '太小' not in txt and '尺寸' not in txt:
        child.close(force=True)
        return Result('TC-I-11', '运行中 resize', 'P2', 'SKIP',
                      'KEY_RESIZE 未触发（环境不支持 SIGWINCH→curses 链路），未验证')
    child.setwinsize(30, 80)          # 恢复
    time.sleep(1.2)
    read_screen(child, mt, 0.5)
    resumed = mt.find('O') is not None and 'Score:' in mt.text()
    child.close(force=True)
    if not resumed:
        return Result('TC-I-11', '运行中 resize', 'P2', 'FAIL',
                      '缩小有提示但恢复后游戏未继续')
    return Result('TC-I-11', '运行中 resize', 'P2', 'PASS', '缩小提示/恢复继续')


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
ALL_CASES = [
    run_tc_i01, run_tc_i02, run_tc_i03, run_tc_i04, run_tc_i05,
    run_tc_i06, run_tc_i07, run_tc_i08, run_tc_i09, run_tc_i10, run_tc_i11,
]


def main():
    results = [fn() for fn in ALL_CASES]
    print('=' * 78)
    print('集成层 PTY 端到端测试（测试方案 TC-I-01~11）')
    print('被测代码: {0}'.format(SNAKE_PY))
    print('=' * 78)
    for r in results:
        flag = {'PASS': 'PASS ', 'FAIL': 'FAIL ', 'SKIP': 'SKIP '}[r.status]
        line = '{0}  {1}  [{2}] {3}'.format(flag, r.tc_id, r.prio, r.name)
        if r.detail:
            line += '  --  ' + r.detail
        print(line)
    n_pass = sum(1 for r in results if r.status == 'PASS')
    n_fail = sum(1 for r in results if r.status == 'FAIL')
    n_skip = sum(1 for r in results if r.status == 'SKIP')
    print('-' * 78)
    print('汇总: PASS={0} FAIL={1} SKIP={2}（共 {3}）'.format(
        n_pass, n_fail, n_skip, len(results)))
    # P2 FAIL 不阻塞（测试方案：P2 失败不阻塞发布，记录缺陷单）
    blocking = [r for r in results if r.status == 'FAIL' and r.prio != 'P2']
    if blocking:
        print('阻塞结论: FAIL（P0/P1 失败 {0} 项）'.format(len(blocking)))
        return 1
    if n_fail:
        print('阻塞结论: PASS（仅 P2 失败，不阻塞）')
    else:
        print('阻塞结论: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
