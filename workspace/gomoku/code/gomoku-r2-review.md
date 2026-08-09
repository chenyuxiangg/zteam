# 代码评审：gomoku（r2）

## 0. 评审结论
- 结论：**FAIL**
- 一句话理由：r2 重写的 `_is_live_three` 在 `_X_XX_`/`_XX_X_` 形态当落子点位于"跳延伸外侧"时返回 False，导致 `check_forbidden` 漏判真实双三禁手，与 r1 同级 P0 缺陷。
- 评审轮次：r2

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 仅 `gomoku/board.py` `_is_live_three` / `_count_live_threes` 注释、README §11 修改轮回应表改动；其他文件与 r1 字节级一致（`diff -r` 仅 board.py + __pycache__），模块/接口/边界与 plan §3/§4/§5.2 一致 |
| 2 | 可运行 | PASS | `python3 -m py_compile gomoku/*.py` 全绿；`gomoku/board.py` 语法与导入路径未破坏 |
| 3 | 功能正确性 | **FAIL** | FR-07 禁手双三判定**仍漏判**：r1 复现 case `check_forbidden(8,7,B) == (True, 'double_three')` ✓（修复生效），但 `_X_XX_` 在落子点为最左 X / `_XX_X_` 在落子点为最右 X 时仍漏判，详见 §2 意见 1 |
| 4 | 边界与异常 | PASS | `_is_live_three` 内部 `0 <= nx < n` 边界检查完整；角落/出界返回 False（实测：顶边三连判定为非活三） |
| 5 | 安全与合规 | PASS | 无新依赖；无网络/系统写入；仅 board.py 内部算法修改 |
| 6 | 可读可维护 | PASS | 函数顶部有详细 docstring（含 r1→r2 算法对比、覆盖形态清单、不算形态清单）；命名清晰；其它可读性属性未变 |
| 7 | 错误处理 | PASS | `_is_live_three` 对非 B/W 颜色立即返回 False；`check_forbidden` 的 try/finally rollback 未改 |
| 8 | 性能与资源 | PASS | 4 方向 × 各一次方向扫描；无新增对象分配；算法复杂度仍为 O(方向×线长) |
| 9 | 不越界 | PASS | 仅修改代码 + README；未混入 tests/（test-developer 阶段产物）；未改方案/需求 |
| 10 | 可审计 | PASS | r2 新目录 `gomoku-r2/`；README §11 增列修改回应表；`git diff` 范围明确（仅 board.py） |

## 2. 评审意见列表

### **[严重] 意见 1：FR-07 双三禁手仍漏判，`_is_live_three` 算法修复不完整**
- 依据：plan §5.2（"双三 = 落子后该点在 4 方向上形成的'活三'计数 ≥ 2"）、FR-07、r1 评审意见 1、testplan UTB-15（`_X_XX_` 跳活三）
- 位置：`gomoku/board.py` `Board._is_live_three`（行 369–442）
- 缺陷：r2 新算法采用"连续 run + 单空延伸"语义，正确处理了 `_XXX_` 在任意落子点、以及 `_X_XX_` / `_XX_X_` 在**中间或远离缺口**位置的情况，但对以下两类形态仍然漏判：

  **形态 A**：`X . X X`（`_X_XX_`）当落子点位于**最左侧 X**（即缺口外侧）：
  ```
  row: . X . X X .    (B at col 7, gap 8, B at 9,10; checked at 7)
  ```
  算法对 `(7,7,1,0)` 的计算：
  - `forward_run=0`（`(8,7)` 是空），进入 `forward_ext` 分支：`(8,7).` + `(9,7).B` → `ext=1`，游标跳到 `(9,7)`；
  - `fwd_open` 检查 `(10,7)` —— 但 `(10,7)` 是 B，**不是空端** → `fwd_open=False`；
  - `backward_run=0`，`bwd_open=True`（`(4,7).`）；
  - `total = 1 + 0 + 0 + 1 + 0 = 2`，不满足 `total == 3`，返回 False。
  - 漏判：`_X_XX_` 是标准 Renju 活三（落子在缺口 `(8,7)` 处即升级为活四 `_X_XXX_`）。

  **形态 B**：`X X . X`（`_XX_X_`）当落子点位于**最右侧 X**（即缺口外侧）：对称问题。

  算法对 `(10,7,1,0)`（stones at `(7,7)(8,7)(10,7)`）：
  - `backward_run=0`（`(9,7).`），`backward_ext=1`（`(8,7).B`），游标跳到 `(8,7)`；
  - `bwd_open` 检查 `(7,7)` —— 是 B → `bwd_open=False`；
  - `total = 1 + 0 + 0 + 0 + 1 = 2`，返回 False。
  - 漏判同上。

  **根因**：`forward_ext` / `backward_ext` 命中后只前进 1 个 stone 后就检查"开放端"，而真实跳延伸可能跨缺口后**还有 1 个或多个 stone**（即 `_X_XX_` 中的 "XX"、`_XX_X_` 中的 "XX"）。算法对"延伸后立即检查开放"成立的情形（如 `_XXX_`）工作正常，但对"延伸后还接有 run"的情形错误地停止了搜索。

- 复现（独立验证，非依赖 r2 自带测试脚本）：
  ```python
  b = Board(15)
  # 水平 _X_XX_：(5,7)B (7,7)B (8,7)B
  # 垂直 _XX_：(5,5)B (5,6)B
  b.place(5, 7, 'B'); b.place(7, 7, 'B'); b.place(8, 7, 'B')
  b.place(5, 5, 'B'); b.place(5, 6, 'B')
  fb, reason = b.check_forbidden(5, 7, 'B')
  # fb == False, reason is None   ← 期望 (True, 'double_three')
  ```
  实际跑出 `(False, None)` —— 与 r1 漏判同性质。

  第二组（`_XX_X_` 右侧外延）：
  ```python
  b = Board(15)
  # 水平 _XX_X_：(5,7)B (6,7)B (8,7)B
  # 垂直 _X_X_：(8,6)B (8,8)B
  b.place(5, 7, 'B'); b.place(6, 7, 'B'); b.place(8, 7, 'B')
  b.place(8, 6, 'B'); b.place(8, 8, 'B')
  fb, reason = b.check_forbidden(8, 7, 'B')
  # fb == False, reason is None   ← 期望 (True, 'double_three')
  ```
  同样返回 `(False, None)`。

- 影响：
  1. **核心功能错误**：黑棋在形成 `_X_XX_` 缺口外侧 / `_XX_X_` 缺口外侧的双三局面时，会被错误判为合法；
  2. 与 r1 评审意见 1 同级 P0 缺陷（"FR-07 双三漏判，核心规则失效"）；
  3. testplan UTB-15（跳活三 `_X_XX_`）在 r1 即声明覆盖，但 r2 自测仅通过 25 个禁手 case（README §11.3），**实际并未覆盖到落子点位于跳延伸外侧的位置**——README §11.2 表中"`_X_XX_`（跳活三）| ✅ 活三"列声称覆盖，但所引用的 case 默认从中间 X 检查，并未触及外侧。

- 修复方向（任选其一）：
  1. **改造为完整 run+gap 扫描**：沿方向延伸，识别"连续段-单空-连续段"形式，统计总 stone 数（含跨缺口的连续段），两端开放即活三；
  2. **复用 `_line_open_ends` 思路**：将候选落子点 (x, y) 视为 run 的成员，调用 `_line_open_ends` 但增加"允许跨 1 个空位"的扩展版；
  3. **枚举所有 5 窗位置**：滑动窗口扫过 (x±2, y±2) 起始的所有 5 窗口，对窗口内任意"3 子 + 2 空（两端）"形态返回 True（窗口中心需包含 (x, y)）。
- 优先级：**P0**，必须修复后重提评审。

### **[一般] 意见 2：README §11.2 / docstring 形态清单存在事实错误**
- 依据：README §11.2 行 `XX.X（落 X 处，前方延伸）| ✅ 活三 | r2 新覆盖`；board.py 行 386 同名条目 "`XX.X`（落 X 处，run=1+2 含单空延伸）—— r1 漏判"
- 缺陷：`XX.X` 含 4 个 X（位置 3,4,6，落子 5），总 stone 数 = 4，对应 `_line_open_ends` 返回 `run=4`，按 plan §5.2 应判为**活四**而非**活三**，归 `_count_open_fours` 处理而非 `_is_live_three`。README / docstring 误把它列为活三。
- 实测：`Board(15)` 落 `(3,3)(4,3)(6,3)B` 后 `_is_live_three(5,3,1,0) == False`、`_line_open_ends(5,3,1,0) == (4, 1, 0)`（活四被正确归入双四路径）。
- 影响：自测清单的可信度下降；评审 §2 意见 1 复现的 case 与 §11.2 表不对应，无法仅靠 README 自证覆盖率。
- 修复方向：把 `XX.X（落 X 处）` 从"活三覆盖"行改为"活四覆盖"行，并在 `§11.2` 加注"`_X_XX_` 在落子点为最左 X / `_XX_X_` 在落子点为最右 X"这一**真正的** r1 漏算场景，作为 r3 必补的目标形态。
- 优先级：一般（不影响代码功能，但 r3 评审无法再依赖该清单做交叉验证）。

## 3. 遗留事项（仅 PASS 时）
（本轮 FAIL，无此节）

## 4. 修改回应表（仅修改轮）

| 评审编号 | 严重度 | 意见摘要（r1） | 修复方案 | 修复位置 | 验证方式 | 评审结论 |
|----------|--------|----------------|----------|----------|----------|----------|
| 1 | P0 | FR-07 双三漏判：固定 5 窗策略漏算"前方已延伸"活三（`.XXX_`、`XX.X` 落 X 处等） | 重写 `_is_live_three`：从固定 5 窗模式匹配改为沿方向识别"连续 run + 单空延伸"，总 stone == 3 且两端开放即活三 | `gomoku/board.py` `_is_live_three`（行 369–442）+ `_count_live_threes` 注释 | r1 复现 `check_forbidden(8,7,B)==(True,'double_three')` ✓；开发者自测 25/25、33/33 ✓ | **部分修复**：r1 复现 case 通过，但 `_X_XX_` 在最左 X / `_XX_X_` 在最右 X 仍漏判（见 r2 意见 1）；README 误把 `XX.X` 列为活三（见 r2 意见 2） |

**r2 综合判定**：r1 意见 1 的核心算法已重写，但重写后的算法对跳活三 `_X_XX_` / `_XX_X_` 在缺口外侧落子点的检测仍存在盲区，与原 P0 缺陷同性质，故本轮仍判 FAIL，需重提 r3。