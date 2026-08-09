# -*- coding: utf-8 -*-
"""迷你终端模拟器（共享模块）：把 curses 输出字节流还原为屏幕字符网格。

供 e2e_snake.py（集成层）与 perf_snake.py（性能层）共用。

r2 修复（回应评审意见 1/5）：
- `ESC[J` 系列清屏序列按真实终端语义处理：清空可视区域并将光标归位到
  左上角（`ESC[2J`）；`ESC[3J` 额外清滚动缓冲（本模拟器无滚动缓冲，等同 2J）。
- 不再区分「清屏」与「重置 grid」——清屏后 curses 会立即全量重绘（被测代码
  Renderer 每帧 erase + 全量重绘），网格由后续字节流重建；上一轮 TC-I-10 的
  假失败根因是「游戏自然结束（撞墙）后边框消失被计入采样帧」，已在 e2e_snake.py
  的采样循环中修复（结束即停止采样 + 宽松帧数判定），而非靠本模拟器。
- 保留备用屏幕（?1049h/l）切换的屏幕重建，与真实终端行为一致。
"""


class MiniTerm(object):
    def __init__(self, cols=80, lines=30):
        self.cols = cols
        self.lines = lines
        self.grid = [[' '] * cols for _ in range(lines)]
        self.x = 0
        self.y = 0

    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            c = data[i]
            if c == '\x1b':
                i += 1
                if i >= n:
                    break
                c2 = data[i]
                if c2 == '[':
                    i += 1
                    params = ''
                    while i < n and not ('\x40' <= data[i] <= '\x7e'):
                        params += data[i]
                        i += 1
                    if i >= n:
                        break
                    final = data[i]
                    i += 1
                    self._csi(params, final)
                elif c2 == ']':
                    while i < n and data[i] != '\x07':
                        i += 1
                    if i < n:
                        i += 1
                else:
                    i += 1
            elif c == '\n':
                self.y = min(self.y + 1, self.lines - 1)
                i += 1
            elif c == '\r':
                self.x = 0
                i += 1
            elif c == '\b':
                self.x = max(0, self.x - 1)
                i += 1
            else:
                if 0 <= self.y < self.lines and 0 <= self.x < self.cols:
                    self.grid[self.y][self.x] = c
                self.x += 1
                if self.x >= self.cols:
                    self.x = 0
                    self.y = min(self.y + 1, self.lines - 1)
                i += 1

    def _csi(self, params, final):
        parts = params.split(';') if params else ['']

        def num(p, default):
            try:
                return int(p)
            except ValueError:
                return default

        # 备用屏幕：进入时清屏（模拟真实终端缓冲切换）；离开时恢复主屏内容
        if params.startswith('?1049') and final == 'h':
            self.grid = [[' '] * self.cols for _ in range(self.lines)]
            self.x = self.y = 0
            return
        if params.startswith('?1049') and final == 'l':
            self.grid = [[' '] * self.cols for _ in range(self.lines)]
            self.x = self.y = 0
            return
        if final in ('H', 'f'):
            row = num(parts[0], 1)
            col = num(parts[1], 1) if len(parts) > 1 else 1
            self.y = max(0, min(row - 1, self.lines - 1))
            self.x = max(0, min(col - 1, self.cols - 1))
        elif final == 'd':                    # VPA：行定位，列不变
            row = num(parts[0], 1)
            self.y = max(0, min(row - 1, self.lines - 1))
        elif final == 'G':                    # CHA：列定位，行不变
            col = num(parts[0], 1)
            self.x = max(0, min(col - 1, self.cols - 1))
        elif final == 'K':                    # EL：清行（0=光标到行尾，2=整行）
            mode = num(parts[0], 0)
            if mode == 2:
                for x in range(self.cols):
                    self.grid[self.y][x] = ' '
            else:
                for x in range(self.x, self.cols):
                    self.grid[self.y][x] = ' '
        elif final == 'J':                    # ED：清屏（2=全屏；3=含滚动缓冲）
            self.grid = [[' '] * self.cols for _ in range(self.lines)]
            self.x = 0
            self.y = 0
        elif final == 'A':
            self.y = max(0, self.y - num(parts[0], 1))
        elif final == 'B':
            self.y = min(self.lines - 1, self.y + num(parts[0], 1))
        elif final == 'C':
            self.x = min(self.cols - 1, self.x + num(parts[0], 1))
        elif final == 'D':
            self.x = max(0, self.x - num(parts[0], 1))
        # 'm'/'l'/'h'/'r'/'g'/'t' 等属性/模式/滚动区/窗口操作序列忽略

    def text(self):
        return '\n'.join(''.join(row).rstrip() for row in self.grid)

    def find(self, ch):
        for y in range(self.lines):
            for x in range(self.cols):
                if self.grid[y][x] == ch:
                    return (x, y)
        return None

    def find_all(self, ch):
        return [(x, y) for y in range(self.lines)
                for x in range(self.cols) if self.grid[y][x] == ch]
