# pacman test 阶段 r1 测试文件集

## 1. 范围与被测对象

- 被测代码：`workspace/pacman/code/pacman-r2/`（只读，测试阶段未修改）
- 依据：`analysis/pacman-r3.md`、`plans/pacman-r1.md`、`testplans/pacman-r1.md`
- 框架：Python 标准库 `unittest`，无第三方测试依赖
- 自动化：逻辑/集成/CLI/渲染桩 118 个测试；真实 PTY 启动退出冒烟；strace 网络调用检查
- 环境相关及视觉项：见 `manual_checklist.md`

## 2. 文件结构

```text
pacman-r1/
├── README.md
├── test-results.txt
├── manual_checklist.md
├── scripts/
│   ├── e2e_pty.py
│   └── network_strace.py
└── tests/
    ├── _path.py
    ├── fixtures.py
    ├── test_cli_contract.py
    ├── test_config.py
    ├── test_entities.py
    ├── test_game.py
    ├── test_ghost_ai.py
    ├── test_input.py
    ├── test_map.py
    └── test_renderer.py
```

## 3. 运行方式

在 zteam 根目录执行：

```bash
export PACMAN_CODE_DIR="$PWD/workspace/pacman/code/pacman-r2"
python3 -m unittest discover \
  -s workspace/pacman/tests/pacman-r1/tests \
  -t workspace/pacman/tests/pacman-r1 -v
python3 workspace/pacman/tests/pacman-r1/scripts/e2e_pty.py
python3 workspace/pacman/tests/pacman-r1/scripts/network_strace.py
```

判定：三个命令均退出 0 才算自动化通过。`network_strace.py` 若环境无 strace 会退出 77 并打印 SKIP，须在有 strace 环境补跑。

## 4. 结果

本轮实际执行：

- unittest：`Ran 118 tests in 0.680s`，`OK`，退出码 0。
- 网络检查：`rc=0 network_calls=0`，退出码 0。
- 真实 PTY 默认启动：**FAIL**，0.056s 后退出码 1，错误为：

```text
地图加载失败：地图文件不存在：data/map_classic.txt
```

结论：测试脚本自身可运行，逻辑/集成/渲染/CLI 合同测试全绿，但 S-01/FR-01 与 S-14/FR-18 的 README 默认启动命令失败。该失败来自被测代码 `Config.map_path` 默认值 `data/map_classic.txt` 与从产物根目录运行 `python3 -m pacman` 时的实际资源路径 `pacman/data/map_classic.txt` 不一致；测试阶段未越界修改被测代码。

完整逐项输出见 `test-results.txt`。

## 5. 测试方案映射

| 方案用例 | 实现位置 | 本轮结果 |
|---|---|---|
| U-01~U-05 / U-51 / E-04~E-05 | `test_map.py`、`test_cli_contract.py` | PASS |
| U-10~U-15 | `test_ghost_ai.py`（互异、公式、clamp、选路、纯函数） | PASS（日志随机复现仅手工观察） |
| U-20~U-23 | `test_ghost_ai.py`、`test_entities.py`、`test_game.py` | PASS |
| U-30~U-32 | `test_entities.py`、`test_game.py` | PASS |
| U-40~U-47 | `test_game.py`、`test_config.py` | PASS（视觉项见手工清单） |
| U-50 | `test_cli_contract.py`、`test_game.py` | PASS |
| E-01 / S-02 / S-03 / S-06 / S-08 / S-10 | `test_renderer.py` | PASS（桩/纯函数）；真实视觉待手工 |
| E-02 / E-03 | `test_cli_contract.py`、`test_input.py` | PASS |
| S-01 / S-14 | `scripts/e2e_pty.py` | **FAIL：默认地图路径错误** |
| S-11 / E-10 | `scripts/e2e_pty.py --repeat 10`、`manual_checklist.md` | 被默认启动缺陷阻塞 |
| N-03 / N-05 / N-06 / N-07 | `test_renderer.py`、`test_cli_contract.py` | 自动化合同 PASS；跨发行版待手工 |
| N-04 | `scripts/network_strace.py` | PASS（0 network calls） |
| N-01 / N-02 | `manual_checklist.md` | 待手工长时验证 |

P0/P1 覆盖原则：可由公开逻辑接口或稳定 CLI/渲染接口判定的项目均已自动化；颜色、闪烁肉眼效果、真实终端卫生、跨发行版与 5 分钟性能按测试方案保留人工验收，不以假测试冒充通过。

## 6. 已发现缺陷

### D-01（P0 / 阻塞）默认启动无法加载内置地图

复现：

```bash
cd workspace/pacman/code/pacman-r2
python3 -m pacman
```

实际：`地图加载失败：地图文件不存在：data/map_classic.txt`，退出码 1。

预期：README §2 所述默认命令直接启动，在 3 秒内渲染完整游戏。

影响：FR-01、FR-18、S-01、S-14；同时阻塞 q/Ctrl+C 连测与真实对局性能/视觉 E2E。

建议由 code 阶段修复：默认地图应基于包目录解析（例如 `Path(__file__).parent / "data/map_classic.txt"`），而不是依赖当前工作目录；修复后重新运行本目录全部命令。
