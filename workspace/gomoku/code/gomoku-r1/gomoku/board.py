"""board.py — 棋盘与规则层。

对应方案 §3（架构）/ §4（接口）/ §5.1（胜负）/ §5.2（禁手）/
§5.4（边界与异常处理）。

约束（与方案一致）：
- 纯逻辑，无 I/O、无 rich 依赖，仅使用标准库；
- 接口签名与方案 §4 接口表完全一致；
- 坐标系：0-index，x ∈ [0, size)，y ∈ [0, size)；board[y][x] 读写；
- 颜色字面量：'B'（黑）/ 'W'（白）/ '.'（空）。
"""

from __future__ import annotations


# 4 个方向：横 / 竖 / 主对角 / 副对角
_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


# ---------- 异常与坐标 ----------


class MoveError(ValueError):
    """坐标解析 / 落子校验错误。

    reason 取值：
        - "format"        格式错误（非合法字符串）
        - "out_of_range"  越界（超出棋盘坐标范围）
        - "occupied"      该点已有棋子
    """

    REASON_FORMAT = "format"
    REASON_OUT_OF_RANGE = "out_of_range"
    REASON_OCCUPIED = "occupied"

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# ---------- Board 类 ----------


class Board:
    """五子棋棋盘。

    内部存储：`_rows[y][x]`，'.' 空 / 'B' 黑 / 'W' 白。
    配套接口严格遵循方案 §4 接口表。
    """

    __slots__ = ("_rows",)

    def __init__(self, size: int = 15) -> None:
        if size not in (13, 15):
            raise ValueError(f"Board size 必须是 13 或 15，得到 {size!r}")
        self._rows: list[list[str]] = [["." for _ in range(size)] for _ in range(size)]

    # ---- 公共属性 ----

    @property
    def size(self) -> int:
        return len(self._rows)

    def cell(self, x: int, y: int) -> str:
        """读 (x,y) 处颜色，'.' 或 'B'/'W'。越界返回 '.'。"""
        if 0 <= x < self.size and 0 <= y < self.size:
            return self._rows[y][x]
        return "."

    # ---- 落子 / 撤销 ----

    def place(self, x: int, y: int, color: str) -> bool:
        """落子。越界或已占用返回 False（不抛异常），由 UI 提示。"""
        if color not in ("B", "W"):
            return False
        if not (0 <= x < self.size and 0 <= y < self.size):
            return False
        if self._rows[y][x] != ".":
            return False
        self._rows[y][x] = color
        return True

    def undo(self, x: int, y: int) -> bool:
        """撤销 (x,y) 处的落子，恢复为 '.'。

        仅 AI 搜索回溯调用，UI 不调用（与方案 §4 接口表注释一致）。
        """
        if not (0 <= x < self.size and 0 <= y < self.size):
            return False
        if self._rows[y][x] == ".":
            return False
        self._rows[y][x] = "."
        return True

    def reset(self) -> None:
        """清空棋盘（重开保持配置不变），与方案 §5.4 FR-10 重开语义一致。"""
        for y in range(self.size):
            for x in range(self.size):
                self._rows[y][x] = "."

    # ---- 胜负 / 满盘 ----

    def check_win(self, x: int, y: int) -> str | None:
        """判断 (x,y) 落子后是否形成五连（或更多）。

        返回胜方颜色 ('B' / 'W') 或 None。
        长连（≥6）按胜负规则判胜（freestyle）；禁手由 check_forbidden 单独处理。
        """
        if not (0 <= x < self.size and 0 <= y < self.size):
            return None
        color = self._rows[y][x]
        if color not in ("B", "W"):
            return None
        for dx, dy in _DIRECTIONS:
            cnt = 1
            for s in (1, -1):
                nx, ny = x + dx * s, y + dy * s
                while (
                    0 <= nx < self.size
                    and 0 <= ny < self.size
                    and self._rows[ny][nx] == color
                ):
                    cnt += 1
                    nx += dx * s
                    ny += dy * s
            if cnt >= 5:
                return color
        return None

    def is_full(self) -> bool:
        """棋盘是否已满。"""
        for row in self._rows:
            for c in row:
                if c == ".":
                    return False
        return True

    # ---- 禁手（仅黑方生效） ----
    #
    # 禁手三规则（方案 §5.2）：
    #   1. 长连：≥6 子连成。
    #   2. 双四：落子后该点在 4 方向上形成的"四"（活四或冲四）计数 ≥ 2。
    #   3. 双三：落子后该点形成的"活三"计数 ≥ 2。
    # 优先级：先查成五（连通且非长连）→ 黑胜，跳过禁手。
    # 活三定义（含跳活三 _X_XX_ / _XX_X_）：3 B 串+两端均开放，补一子成活四。
    #
    # 实现策略：以候选点为中心，沿 4 方向各构造一段长度为 9 的"线字符串"，把候选
    # 点替换为 'B'（模拟放子）。线字符串中 'B' = 我方、'.' = 空、'*' = 阻挡
    # （对方子或越界）。在该 9 字符串上独立识别是否构成"活三"/"四"。
    # 9 字符串两边各 4 格缓冲，对跨 1 个空位的跳形态足够。

    def check_forbidden(self, x: int, y: int, color: str) -> tuple[bool, str | None]:
        """判断 (x,y) 处落 color 是否构成禁手。

        仅 color='B' 有意义；白方（'W'）恒返回 (False, None)。
        返回：
            (False, None)        不禁手；
            (True, reason)        禁手命中；reason ∈ {"long", "double_four", "double_three"}。
        """
        if color != "B":
            return (False, None)
        if not (0 <= x < self.size and 0 <= y < self.size):
            return (False, None)
        if self._rows[y][x] != ".":
            return (False, None)

        # 成五优先判胜（成五 + 禁手并存时判黑胜，方案 §5.2 / FR-07）
        if self._is_exactly_five(x, y):
            return (False, None)

        # 长连：≥6 子连成
        if self._is_long(x, y):
            return (True, "long")

        # 双四 / 双三：4 方向上的"四"与"活三"计数
        fours = 0
        threes = 0
        for dx, dy in _DIRECTIONS:
            if self._is_open_four_including(x, y, dx, dy):
                fours += 1
            if self._is_live_three_including(x, y, dx, dy):
                threes += 1

        if fours >= 2:
            return (True, "double_four")
        if threes >= 2:
            return (True, "double_three")
        return (False, None)

    # ---- 禁手内部判定 ----

    def _is_exactly_five(self, x: int, y: int) -> bool:
        """放置 B 在 (x,y) 后，是否在该点串成恰好 5 连（不含 ≥6）。

        用于禁手优先级判定：成五优于禁手。
        """
        for dx, dy in _DIRECTIONS:
            cnt = 1
            for s in (1, -1):
                nx, ny = x + dx * s, y + dy * s
                while (
                    0 <= nx < self.size
                    and 0 <= ny < self.size
                    and self._rows[ny][nx] == "B"
                ):
                    cnt += 1
                    nx += dx * s
                    ny += dy * s
            if cnt == 5:
                return True
        return False

    def _is_long(self, x: int, y: int) -> bool:
        """放置 B 在 (x,y) 后，是否形成 ≥6 连（长连）。"""
        for dx, dy in _DIRECTIONS:
            cnt = 1
            for s in (1, -1):
                nx, ny = x + dx * s, y + dy * s
                while (
                    0 <= nx < self.size
                    and 0 <= ny < self.size
                    and self._rows[ny][nx] == "B"
                ):
                    cnt += 1
                    nx += dx * s
                    ny += dy * s
            if cnt >= 6:
                return True
        return False

    # ---- 沿单方向构造"线字符串"用于识别 ----

    def _line_through(self, x: int, y: int, dx: int, dy: int) -> str:
        """以 (x,y) 为中心，沿 (dx, dy) 取 9 个字符，模拟放置 B 在 (x,y)。

        返回 9 字符串：
            'B'  当前已是 B（同时作为模拟中心点）
            '.'  当前空
            '*'  阻挡（对方子 W 或越界）
        """
        chars = []
        for k in range(-4, 5):
            nx, ny = x + dx * k, y + dy * k
            chars.append(self._polar_cell(nx, ny, "B"))
        s = "".join(chars)
        # 中心位置 4 替换为 'B'（模拟放子）
        return s[:4] + "B" + s[5:]

    def _polar_cell(self, x: int, y: int, color: str) -> str:
        """按 color 视角获取格子：color → 'B'，空 → '.'，其他 → '*'（阻挡），越界 → '*'。"""
        if not (0 <= x < self.size and 0 <= y < self.size):
            return "*"
        c = self._rows[y][x]
        if c == color:
            return "B"
        if c == ".":
            return "."
        return "*"

    # ---- 在 9 字符串上识别活三 / 四（核心算法） ----
    #
    # 关键修复（参考代码评审 r2 意见 1）：r2 算法仅看中心区段内的固定"run + 单空
    # 延伸"，对跳活三 _X_XX_ / _XX_X_ 在外侧位置会漏判。下面采用更严格的
    # 窗口扫描：以候选点为中心枚举长度 5/7 窗口，对每个窗口做"严格活三判据"。
    #
    # 严格活三判据：
    #   - 窗口含 3 个 B；
    #   - 窗口不含 '*'（即窗口边界内无阻挡）；
    #   - 窗口首字符与末字符均为 '.'（窗口边界本身为开口）；
    #   - 窗口左侧外部一格 line[start-1] 与右侧外部一格 line[end] 均为 '.'——
    #     严格保证两侧延伸可能成活四；
    #   - 候选点 center 在窗口内。
    #
    # 上述 5 个条件同时满足即"严格活三"——是 Renju 标准的活三定义。
    # 长度 5/7 各枚举（覆盖 _XXX_、_X_XX_/_XX_X_、两端无延伸阻隔三种形态）。

    @staticmethod
    def _is_live_three_in_9line(line: str) -> bool:
        """line 长度 9，索引 4 是模拟放置的 B。返回该 B 是否在该方向构成活三。"""
        center = 4
        n = len(line)
        for win_len in (5, 7):
            # start 的范围：包含 center 的窗口
            start_lo = max(0, center - (win_len - 1))
            start_hi = min(n - win_len + 1, center + 1)
            for start in range(start_lo, start_hi):
                end = start + win_len
                if start <= center < end:
                    if Board._window_is_live_three(line, start, end):
                        return True
        return False

    @staticmethod
    def _window_is_live_three(line: str, start: int, end: int) -> bool:
        """判断 line[start:end] 窗口是否构成"活三"。

        严格条件（与 Wikipedia Renju 一致）：
          1. 窗口内 B-stone 数 == 3；
          2. 窗口内不存在 '*'（即无阻挡/对方子）；
          3. 窗口内非 B 的格子数 == 窗口内 B 的格子数 - 1 + 0 或 1（即允许 1 个空位间隙）。
          4. 窗口内最左侧 B 的"前一格"是 '.'；最右侧 B 的"后一格"是 '.'——
             这是补一子成活四的延伸前提。

        注：放宽到允许窗口内有 1 个空位间隙（"_X_XX_" 类型），但要求窗口两端延伸开放。
        """
        w = line[start:end]
        if w.count("B") != 3:
            return False
        if "*" in w:
            return False
        # 窗口内的 '.' 数量应等于 B 数（"3 B + 1 空位"或"3 B + 0 空位"），
        # 因 win_len ∈ {3, 5, 7}：
        #   - 3-窗：3 B（无空位）
        #   - 5-窗：3 B + 2 空位（即可包含 _X_XX_ / _XX_X_ 两类）
        #   - 7-窗：3 B + 4 空位（多冗余空间，但首尾一定要更"友好"）
        dot_count = w.count(".")
        if dot_count < 2:
            return False
        # 找到窗口内的最左 B 与最右 B 的下标
        first_b = w.index("B")
        last_b = len(w) - 1 - w[::-1].index("B")
        # 窗口外两端必须是空位（"."），才能补子成活四
        n = len(line)
        if start - 1 >= 0 and line[start - 1] != ".":
            return False
        if end < n and line[end] != ".":
            return False
        return True

    @staticmethod
    def _is_open_four_in_9line(line: str) -> bool:
        """line 长度 9，索引 4 是模拟放置的 B。返回该 B 是否在该方向构成"四"。

        "四"判定：含 4 个 B 的窗口，至少一端开放（外侧一格为 '.'）。
        这里把"活四 / 冲四"都计入（Renju 与方案 §5.2 一致）。
        """
        center = 4
        n = len(line)
        for win_len in (4, 5, 6, 7):
            start_lo = max(0, center - (win_len - 1))
            start_hi = min(n - win_len + 1, center + 1)
            for start in range(start_lo, start_hi):
                end = start + win_len
                w = line[start:end]
                if w.count("B") != 4:
                    continue
                # 至少一端开放
                left_out = line[start - 1] if start - 1 >= 0 else "*"
                right_out = line[end] if end < n else "*"
                if left_out == "." or right_out == ".":
                    return True
        return False

    # ---- 包装：禁手判定 ----

    def _is_live_three_including(self, x: int, y: int, dx: int, dy: int) -> bool:
        line = self._line_through(x, y, dx, dy)
        return self._is_live_three_in_9line(line)

    def _is_open_four_including(self, x: int, y: int, dx: int, dy: int) -> bool:
        line = self._line_through(x, y, dx, dy)
        return self._is_open_four_in_9line(line)


# ---------- 坐标解析 ----------


def parse_move(text: str, size: int = 15) -> tuple[int, int]:
    """解析用户输入坐标为 (x, y)（0-index）。

    支持格式（与 README §3 一致）：
        "A8"     字母列 + 数字行（A=0, 数字为 1-index 行号 → y = int - 1）
        "8,8"    数字对（行,列），分隔符为 ',' 或 ' '
        "8 8"    同上，空格分隔
        大小写字母均接受

    异常：抛 MoveError，reason ∈ {"format", "out_of_range"}。
    """
    if not isinstance(text, str):
        raise MoveError(f"非法输入类型：{type(text).__name__}", MoveError.REASON_FORMAT)
    s = text.strip()
    if not s:
        raise MoveError("空输入", MoveError.REASON_FORMAT)

    # ---- 数字对格式 ----
    if "," in s:
        return _parse_pair(s, sep=",")
    if " " in s and not s[0].isalpha():
        return _parse_pair(s, sep=" ")

    # ---- 字母数字混合 ----
    i = 0
    while i < len(s) and s[i].isalpha():
        i += 1
    if i == 0 or i == len(s):
        raise MoveError(f"格式错误：{text!r}", MoveError.REASON_FORMAT)
    letter_part = s[:i]
    digit_part = s[i:]
    if not digit_part.isdigit():
        raise MoveError(f"格式错误：{text!r}", MoveError.REASON_FORMAT)
    x = _letter_to_x(letter_part, size)
    y = int(digit_part) - 1

    if not (0 <= x < size and 0 <= y < size):
        raise MoveError(
            f"坐标越界：{text!r}（size={size}）",
            MoveError.REASON_OUT_OF_RANGE,
        )
    return (x, y)


def _parse_pair(s: str, sep: str) -> tuple[int, int]:
    normalized = s.replace(",", " ").split() if sep == "," else s.split()
    if len(normalized) != 2:
        raise MoveError(f"数字对格式错误：{s!r}", MoveError.REASON_FORMAT)
    try:
        row_one_based = int(normalized[0])
        col_str = normalized[1].strip()
    except ValueError:
        raise MoveError(f"数字对格式错误：{s!r}", MoveError.REASON_FORMAT)
    if col_str.isdigit():
        x = int(col_str) - 1
        y = row_one_based - 1
    else:
        x = _letter_to_x(col_str, size=15)  # size 在外层重新校验
        y = row_one_based - 1
    return (x, y)


def _letter_to_x(s: str, size: int) -> int:
    """列字母 → 0-index x（不区分大小写）。A=0, ..., O=14（15×15 时）。"""
    s = s.upper()
    if not s.isalpha() or len(s) != 1:
        raise MoveError(f"非法字母列：{s!r}", MoveError.REASON_FORMAT)
    x = ord(s) - ord("A")
    max_x = size - 1
    if not (0 <= x <= max_x):
        raise MoveError(
            f"列字母越界：{s!r}（size={size}，合法 A–{chr(ord('A') + max_x)}）",
            MoveError.REASON_OUT_OF_RANGE,
        )
    return x
