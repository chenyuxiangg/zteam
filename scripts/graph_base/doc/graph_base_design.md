# 图模型框架

使用有向有环图/有向无环图描述一个任务的带状态的SOP，并通过提供调度与状态管理实现任务自动闭环的系统框架。

## 整体结构

框架分三层，最上层为配置层，该层提供用户图配置的接口，是图模型中唯一用户可见的部分；中间层为组件层，通过3个组件调度图模型、管理SOP状态，其中组件包括：调度器、状态管理器、监控器；最下层为内核层，提供图模型操作的所有功能。

### 配置层

每个配置对应一个SOP，配置参数分为四类：全局类、node类、门控类、边类，详解如下：

#### 全局类

定义整个SOP的属性，具体如下：
`name`: SOP的唯一身份标识，多个SOP间不可重复，用字符串表示
`graph_mode`: 图模型选择，支持 ["directed_cycle", "directed_nocycle"] 两个取值，即有向有环图和有向无环图
`pre_handle`: SOP运行的前置处理，是一个函数名，实际调度时反射成具体函数
`post_handle`: SOP运行的后置处理，是一个函数名，实际调度时反射成具体函数

#### node类

定义SOP中有哪些节点以及给节点绑定agent：
`nodes[i].name`: 节点名，唯一标识该节点，同一SOP内不可重复，用字符串表示
`nodes[i].iport`: 节点的输入端口，用于向节点输入数据，当前仅支持传入文件名，该字段是一个二维数组，iport[i]表示多组输入，只需要满足某一组输入有效时，节点就可以开始运行；iport[i][j]表示第i组输入的第j个文件，当且仅当iport[i]中的所有文件都有效时，才表示iport[i]这组输入有效；
`nodes[i].oport`: 节点的输出端口，用于节点处理完数据后对下一个节点/用户输出数据，当前仅支持输出文件名，该字段是一个二维数组，oport[i]表示多组输出，门控会根据输出是否有效放行某一条边，oport[i]之间也是或的关系，即只要任意一个oport[i]有效，门控就会放行
`nodes[i].attr.is_src`: 标识该节点是否时原节点（入口节点），一个图只能拥有一个src节点
`nodes[i].attr.is_sink`: 标识该节点是否时汇节点（出口节点），一个图只能拥有一个sink节点
`nodes[i].attr.role`: 该节点绑定的Agent，用文件路径表示，路径出存放的时Agent的自述文件
`nodes[i].proc`: 节点内部执行函数名，调度时反射为具体函数；空串表示无内部逻辑（由公共 `proc_bypass` 函数兜底）

#### 门控类

图是一个类似树的结构，或者称为一个状态机，每一时刻只能存在一种输出状态，因此通过门控决定当前状态应该向哪个状态进行迁移：
`gates[i].name`: 门的唯一标识，同一SOP内不可重复，用字符串表示
`gates[i].op`: 门控函数，用字符串表示，实际调度时反射成具体函数
`gates[i].enum_dir`: 门控的出口，用一维数组表示，每个出口关联一条边，关联在edges中绑定

#### 边类

节点与节点之间通过边进行通信，有状态转移关系/通信需求的节点才需要建立边：
`edges[i].name`: 边的唯一标识，同一SOP内不可重复，用字符串表示
`edges[i].inode`: 边的输入端，一条边只能有一个输入端，边的方向永远是从输入端指向输出端
`edges[i].onode`: 边的输出端，一条边只能有一个输出端
`edges[i].driver`: 边的驱动方式，有两种取值 ["tick", "manual"],即通过tick自动调度和手动触发，也就是说，当gate通过后可以通过sched自动将当前运行的节点从inode 转移到 onode，或者手动的方式
`edges[i].gate`: 边关联的门，即通过指定门的名字把边挂载到门上
`edges[i].gate_value`: 当门的判断结果为 gate_value 所定义的值时，启动这条边
`edges[i].cmd`: 节点从inode 转移到 onode的方式，当前通过调用命令的方式，该字段时一个字符串，调度时反射为具体函数

### 组件层

组件层由调度器、状态管理器、监控器、派发器、编排器五个模块组成。组件层上接配置层 JSON，下用内核层原语（loader / state / ports / traversal / registry），向调用方（hermes chat / 人工 / 测试）暴露统一 API。

#### 模块布局

```
scripts/graph_base/src/
├── components/
│   ├── orchestrator.py              # 顶层组装：create_instance / tick / run
│   ├── scheduler/
│   │   ├── core.py                  # Scheduler.tick / find_ready / claim / dispatch / trigger_edge
│   │   ├── evaluator.py             # gate.op 求值 / match_gate / should_run_cmd / select_next_edge / run_edge_cmd
│   │   └── cycle.py                 # cycle 模式阈值检测 / cycle_check
│   ├── state_manager/
│   │   ├── core.py                  # StateManager 公开方法
│   │   ├── schema.py                # State dataclass
│   │   ├── ports.py                 # iport / oport 二维 OR-of-AND 记录
│   │   └── terminal.py              # is_sop_done
│   ├── monitor/
│   │   ├── core.py                  # emit / reap_stale / detect_progress
│   │   ├── events.py                # 事件常量（SCH_EV_*）+ level 映射
│   │   └── logger.py                # zlog system logger 包装
│   └── dispatcher/
│       ├── base.py                  # Dispatcher Protocol + DispatchResult
│       └── process.py               # ProcessDispatcher（setsid 拉子进程）
└── worker/
    └── <sop_name>/
        └── <node_name>_worker.py    # 每个 node 一个 worker 模块，含 worker_run(args)
```

#### 核心概念

调度器对一条边的推进分三关：

1. **gate 求值**：调 `gate.op(base_dir, state)` 拿返回值，与 `edge.gate_value` 比较。不匹配则该边不放行，cmd 不执行（零副作用）。
2. **cmd 执行**：gate 通过后调 `cmd(args)` 跑副作用动作，写下一节点就绪态。
3. **driver 模式**：决定 cmd 何时被触发。`tick` = scheduler 在 gate 通过当 tick 调 cmd；`manual` = 必须外部调 `trigger_edge(edge_name, approver)` 写 `triggered_edges`，下次 tick 走 cmd。

**Node.proc** 是节点内部执行函数，注册到 kernel registry；空串表示无内部逻辑，由公共 `proc_bypass` 兜底。proc 与 `pre_handle / post_handle` 独立，三者不互相替代。

#### state_manager

`State` 是不可变 dataclass（`frozen=True`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `current_node` | `str \| None` | 当前正在执行的节点；`None` = 未启动 |
| `history` | `tuple[tuple[str, str], ...]` | 已完成节点轨迹，`[(node_name, iso8601_ts), ...]` |
| `triggered_edges` | `Mapping[str, str]` | manual 边外部 trigger 记录，`edge_name -> approver` |
| `cycle_counts` | `Mapping[str, int]` | cycle 节点走过次数（nocycle 恒为空） |
| `last_output` | `Mapping[str, tuple[str, ...]]` | 节点最近产出文件（debug 用） |

修改路径：`record_completion / transition / rollback / claim / clear_claim / record_cycle_step / record_input/output_satisfied / trigger_edge`。

`rollback` 规则：清 `triggered_edges`、清 claim、`os.unlink` 删除 `last_output[node_name]` 列出的文件、清 `last_output`、保留 `cycle_counts` 与 `history`。

`is_sop_done(graph, state)`：`state.current_node` 是 sink 节点（sink 一定不循环，无须检查产物）。

#### scheduler

`Scheduler.tick(sop_name, instance_id)` 单实例调度流程：

1. 持 `StateLock` 读 `state.json` → State
2. `find_ready` 找 iport 满足的当前节点
3. `evaluate_gates` 对出边涉及的 gate 求值
4. `match_gate` + `should_run_cmd` 命中边
5. `select_next_edge` 返回应推进边
6. `run_edge_cmd` 跑 cmd（副作用动作）
7. `dispatch` 拉 worker 跑 node.proc
8. `StateManager.write` 落盘

`trigger_edge(state_file, edge_name, approver)` 供外部触发 manual 边；approver 可省，省略时记 `"anonymous"`。调度器不提供 `tick_all`；多实例由上层循环 + 多 Orchestrator 实例负责。

#### monitor

事件常量统一 `SCH_EV_` 前缀（17 个），通过 zlog 单 `system` logger（`level=DEBUG`）输出；事件 tuple 第二位决定实际 level（info / warn / error / debug）。关键事件：

| 事件 | 触发时机 | level |
|---|---|---|
| `SCH_EV_TICK` | tick 入口 + 出口（每次 tick 2 条） | debug |
| `SCH_EV_TIMEOUT` | StateLock / worker spawn / gate.op 超时 | error |
| `SCH_EV_ERROR` | gate.op / cmd / dispatcher / worker 异常 | error |
| `SCH_EV_EDGE_ADMITTED` | gate 通过，cmd 跑 | debug |
| `SCH_EV_EDGE_REJECTED` | gate_value 不匹配，cmd 不跑 | info |
| `SCH_EV_MANUAL_PENDING` | manual 边 gate 通过但长期未 trigger | warn |

#### dispatcher + worker

`Dispatcher` 是 Protocol；当前唯一实现 `ProcessDispatcher`，按 `worker_cmd` 模板拉子进程。`worker_cmd` 用 `str.format_map` 替换，支持 5 个占位符：`{sop_name} {instance_id} {node_name} {proc} {base_dir}`。

默认模板：
```python
DEFAULT_WORKER_CMD = (
    "{python} -m graph_base.worker.{sop_name}.{node_name}_worker "
    "--sop {sop_name} --instance {instance_id} "
    "--node {node_name} --proc {proc} --base-dir {base_dir}"
)
```

worker 集合目录 `src/worker/<sop_name>/` 下每个 node 一个 `<node_name>_worker.py`，内含 `worker_run(args) -> int`。worker 内部：解析 argv → 读 state → `resolve_op(args.proc or "proc_bypass")` → 跑 proc → `record_completion`。公共 `proc_bypass(args) -> tuple[str, ...]` 注册到 kernel registry；proc 字段空串时 worker 自动调它。

#### orchestrator + CLI

`Orchestrator(graph, root, dispatcher, monitor)` 封装四组件。方法：

- `create_instance(base_dir, input_files) -> InstanceId`
- `tick() -> list[Alarm]`
- `run(instance_id, max_ticks=1000) -> list[Alarm]`

CLI 子命令（`scripts/graph_base_cli.py`）：`tick / create / list / show / record-completion / trigger-edge / rollback / validate`。无 `tick-all`。

#### 非目标

- ❌ 不实现 InProcessDispatcher / QueueDispatcher（仅 ProcessDispatcher）
- ❌ 不支持热加载 Graph
- ❌ 不跨 SOP 编排
- ❌ 不持久化 validators.Issue（监控器自己 log）
- ❌ 不自动 trigger manual 边
- ❌ 不分 alarm / pipeline 两条 logger


### 内核层

内核层是图模型框架的最下层，对上层组件（调度器、状态管理器、监控器）提供图模型操作的全部原语。内核层不解释 SOP 业务语义，不调度、不发事件、不写日志。

#### 设计原则

1. **数据与逻辑解耦**：`graph.py / node.py / gate.py / edge.py` 是纯 dataclass（无方法），其余模块是对这些数据的纯函数 / 原语。
2. **薄内核**：所有"做决定"的逻辑上移到组件层。
3. **配置即真相**：JSON 配置是内核建模的唯一来源；任何 Python 对象都能反序列化回原 JSON。
4. **多实例支持**：同一个 SOP 配置可并行运行多个实例（多个并发需求、多个并发布版），每个实例有独立 state 文件、独立锁。
5. **原子与可重入**：所有写操作走锁，锁粒度 = 单个实例（一把锁 = 一个 state 文件 = 一个 SOP 实例）。
6. **可单测**：每个函数都自洽（参数是 dataclass，不依赖全局），pytest 用 fixture 喂数据。

#### 模块布局

```
scripts/graph_base/src/
├── __init__.py
└── kernel/
    ├── __init__.py        # 公共导出
    ├── graph.py           # Graph / GraphMode（数据 + 工厂方法 build）
    ├── node.py            # Node（数据）
    ├── gate.py            # Gate（数据）
    ├── edge.py            # Edge / Driver（数据）
    ├── loader.py          # load_graph(path) -> Graph；JSON → 对象 + 字段类型校验
    ├── validators.py      # validate(graph) -> list[Issue]；跨字段一致性
    ├── traversal.py       # 图遍历与查询：successors / predecessors / cycle_check / topo_sort ...
    ├── ports.py           # 文件端口语义：iport_or_of_and / oport_or / port_file_path
    ├── state.py           # StateLock / read_state / write_state / instance 路径生成
    └── registry.py        # 反射接口：register_op / resolve_op —— 只返回可调用对象
```

不引入数据库；不引入第三方库；`scripts/zlog/` 仅由组件层使用，内核层不依赖它。

#### 数据模型

四个 dataclass 文件构成纯数据层：

`graph.py` 定义 `GraphMode` 枚举（`DIRECTED_CYCLE` / `DIRECTED_NOCYCLE`）与 `Graph` 聚合根。`Graph` 用 `frozen=True`，字段为 `name / graph_mode / pre_handle / post_handle / nodes / gates / edges`。`Graph.build()` 静态工厂方法是唯一公开的构造路径，负责类型校验与跨字段一致性校验（调用 `validators.validate`）。四个派生索引（`node_index / gate_index / edge_by_inode / edge_by_gate`）以 `@cached_property` 实现：首次访问时按 `nodes / gates / edges` 即时计算并缓存，从根本上不可能出现陈旧值。`Graph` 不暴露任何运行时修改入口。

`node.py` 定义两个 dataclass：`NodeAttr`（`is_src / is_sink / role`，对应 JSON `attr` 子对象）与 `Node`（`name / iport / oport / attr: NodeAttr / proc`，顶层 `proc` 字段允许空串）。iport / oport 都是二维 tuple（元组的元组），语义见下表：

| 字段 | 组内 | 组间 |
|---|---|---|
| `iport[i][j]` | AND：组内所有文件必须都存在，组才"满足" | OR：任一组满足，节点即可开始 |
| `oport[i][j]` | AND：组内所有文件都存在，组才"产出" | OR：任一组产出，门控即可放行 |

> 注：src 节点也允许有 iport（如 planer 需读入 `input.md`）。

`gate.py` 定义 `Gate`：`name / op / enum_dir`。`op` 是函数名，由 `registry.resolve_op` 解析；`enum_dir` 是一维 tuple，与 `edge.gate_value` 对应。

`edge.py` 定义 `Driver` 枚举（`TICK` / `MANUAL`）与 `Edge`：`name / inode / onode / driver / gate / gate_value / cmd`。`gate` 引用 `gates[].name`；`gate_value` 命中值；`cmd` 是函数名。

#### loader 与 validators

`loader.py` 负责 `load_graph(path) -> Graph`：读 JSON、字段类型校验、调 `Graph.build()`。失败抛 `GraphLoadError(message, path_in_json)`，`path_in_json` 是字符串如 `"nodes[2].name"`。loader 不接收 `base_dir`（运行时概念，挂在 `ports.py` 求值时注入）；不做跨字段一致性（那是 `validators.py`）。

`validators.py` 负责跨字段一致性，返回 `list[Issue]`。`Issue` 是 dataclass，字段为 `code / level / message / path`，`level` 取 `Literal["debug", "info", "warning", "error"]` 四级（当前主要使用 warning / error）。校验项：

- `E_DUP_NODE_NAME` / `E_DUP_GATE_NAME` / `E_DUP_EDGE_NAME`（error）
- `E_DUP_GLOBAL`：SOP `name` 跨图唯一（error）
- `E_NO_SRC`：必须有且仅有一个 `is_src=true` 的节点（error）
- `E_MULTI_SINK`：必须有且仅有一个 `is_sink=true` 的节点（error）
- `E_BAD_EDGE_ENDPOINT`：edge.inode / onode 必须指向存在的 node（error）
- `E_BAD_GATE_REF`：edge.gate 必须指向存在的 gate（error）
- `E_GATE_VALUE_NOT_IN_ENUM`：edge.gate_value 必须在 gate.enum_dir 中（error）
- `E_MULTI_MATCH_GATE`：同一 gate 同 gate_value 不能挂 ≥2 条边（error）
- `W_CYCLE_ON_NOCYCLE`：`graph_mode=directed_nocycle` 时发现环（warning）

`validators.py` 不抛异常，只返回列表；由组件层决定是否阻断加载。error 阻断，warning 仅记录。`directed_cycle` 模式下检测到的环不进入 Issue 列表——由 `cycle_check` 直接返回给调用者，监控器组件决定是否记录。

#### traversal

`traversal.py` 是纯函数集：

| 函数 | 用途 |
|---|---|
| `successors(graph, node_name) -> tuple[str, ...]` | 出边终点（去重、保序） |
| `predecessors(graph, node_name) -> tuple[str, ...]` | 入边起点 |
| `edges_from(graph, node_name) -> tuple[Edge, ...]` | 指定节点的所有出边 |
| `edges_via_gate(graph, gate_name) -> tuple[Edge, ...]` | 挂载在某门上的边 |
| `match_gate(graph, gate_name, enum_value) -> Edge \| None` | enum 命中后应该触发的边（0 或 1）；≥2 抛 `AmbiguousMatchError` |
| `cycle_check(graph) -> tuple[tuple[str, ...], ...]` | 返回**所有**环（节点名列表的元组），DFS 标记法；返回空 tuple 表示无环 |
| `topo_sort(graph) -> tuple[str, ...]` | 无环模式下的节点顺序；环存在时抛 `CyclicGraphError` |

#### ports

`ports.py` 是文件端口语义的具象。设计原则：**只判断文件是否存在，不解析内容**。

- `iport_satisfied(node, base_dir) -> tuple[int, ...]`：返回当前满足条件的 iport 组索引（OR-of-AND）。空 tuple 表示无输入就绪。
- `oport_produced(node, base_dir) -> tuple[int, ...]`：返回已产出的 oport 组索引（OR）。
- `port_file_path(spec, base_dir) -> Path`：解析 `"doc/spec.md"` → `<base_dir>/doc/spec.md`，并校验路径不会逃出 base_dir（防御 `../` 越界）。
- `expand_iport_paths(node, base_dir)` / `expand_oport_paths(node, base_dir)`：展开所有路径，便于监控器列出节点在等哪些 / 会产生哪些文件。

`base_dir` 在这里注入，不在 loader。同一份 graph 对象可被不同实例用不同 base_dir 跑——多实例支持的具体落地。

#### state

`state.py` 提供状态原子读写 + 多实例路径生成：

- `state_dir(root, sop_name)` / `state_path(root, sop_name, instance_id)`：路径生成。`root` 缺省时读 `GRAPH_BASE_STATE_ROOT` 环境变量，默认 `/var/lib/graph_base`；`state_dir` 自动 `mkdir(parents=True, exist_ok=True)`。
- `new_instance_id() -> str`：`uuid.uuid4().hex[:12]`，12 字符 hex。
- `StateLock(state_file, timeout=5.0, stale_after=300.0)`：基于 `fcntl.flock` 的互斥锁，with 语法使用。
- `read_state(state_file) -> dict` / `write_state(state_file, payload)`：原子读写（临时文件 + `os.replace`）。
- `claim(state_file, pid, owner) -> bool` / `clear_claim(state_file)` / `pid_alive(pid)`：认领与回收。

**多实例关键点**：state 路径 = `<root>/<sop_name>/<instance_id>.json`，每个实例独占；锁粒度 = 单实例（不是单 SOP），所以两个并发实例互不阻塞。

**state schema**：内核不定义 schema。`write_state` 接 `dict`，由状态管理器组件决定字段含义（例如 `{"claim_pid": ..., "current_node": ..., "history": [...]}`）。内核只保证：原子写入、并发互斥、stale 回收。

**claim stale 策略**：claim 无效 = `pid_alive(pid) is False` **或** `(now - claim.ts) > stale_after`（任一条件满足即无效）。进程崩了立即可被接管（不依赖 stale_after 到期）；进程还在但卡了超过 stale_after 也可被接管。`stale_after` 是保险阀：正常情况下进程退出时会调 `clear_claim`，但万一没调（比如 kill -9），stale_after 保证不会永远卡死。

#### registry

`registry.py` 提供反射接口：

- `_OP_REGISTRY: dict[str, Callable]` / `_CMD_REGISTRY: dict[str, Callable]`：进程内单例。
- `_LOCK = threading.Lock()`：守护所有读（resolve）/ 写（register）/ 清（reset）操作。普通 Lock 而非 RLock，避免重入死锁。
- `register_op(name, fn)` / `resolve_op(name)` / `register_cmd(name, fn)` / `resolve_cmd(name)` / `reset_registry()`。

注册在进程启动期完成；运行时主要走 resolve，锁竞争极少。内核层只维护名字 → 可调用对象的映射；不调用这些函数。组件层（调度器）拿到函数后再传 ctx 执行。

#### 非目标

- ❌ 不调度（那是 调度器 组件）
- ❌ 不解释门控返回值（那是组件调用 `resolve_op` 后做的事）
- ❌ 不写日志、不告警（那是 监控器 组件，本框架通过 zlog）
- ❌ 不读 pre_handle / post_handle / cmd 的实际函数体
- ❌ 不维护历史轨迹、tick 计数、SOP 完成判定（属于状态管理器关心的字段，但写什么由组件决定）
- ❌ 不跨 SOP 实例共享锁——一把锁 = 一个 state 文件 = 一个实例
- ❌ 不定义 state file schema——内核只管原子性，不管字段含义