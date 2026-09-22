# zlog

极简多线程安全日志库。

## 设计原理

- **声明式配置**：所有 logger 在 `scripts/zlog/config/output_config.json` 一次性声明；运行时通过 `get_logger(name)` 取，禁止任何路径的隐式构造
- **懒加载**：首次 `get_logger` 未命中触发 JSON 加载并原子注册全部 logger；后续零 IO
- **严格模式**：未声明的 logger 名立即抛 `KeyError`，避免空 logger 静默丢日志
- **原子替换**：load 时先 build 后 register；任何 spec 校验失败时已构建的实例不会进入注册表
- **写前轮转**：`RotatingFileSink` 在写之前判断，单行永不丢

## 特性

- **多通道**：单个 logger 可同时挂多个 sink（stdout + 文件、stdout + stderr 等），按声明顺序独立过滤、独立写入
- **per-sink 格式**：每个 sink 可独立指定 `format` 模板，同一条记录可同时以管式分隔落到文件、以 JSON 落到控制台
- **per-sink 级别**：每个 sink 有独立 `level` 阈值；logger 级别先过滤，再按 sink 级别过滤
- **大小轮转**：`RotatingFileSink` 按字节阈值触发，保留 N 个文件总数（`app.log` + `app.log.1` ... `app.log.{N-1}`），超限丢最老
- **角色绑定**：`Logger.set_role(role)` 把 role 字符串写到每条记录上，便于下游按子系统分流
- **调用方定位**：通过 `sys._getframe(1)` 跳过 `info/warn/...` 便利方法，自动捕获真正的调用函数名和行号
- **caller-friendly 字段**：位置参数 `(k, v, k, v)` 和 `**kwargs` 都能传入记录字段
- **线程安全**：注册表锁保证并发 `get_logger` 一致；sink 操作各自加锁；慢 sink 不阻塞兄弟 sink（错误隔离到 stderr）
- **结构化解析**：管式分隔 + 字段统一对齐宽度，正则友好；kv 部分自动给含空格的值加引号

## 对外接口

```python
from zlog import get_logger, init_logging

log = get_logger("statectl")        # 懒加载，命中失败时抛 KeyError
init_logging("/path/to/config.json") # 显式预加载（可选）

log.info("worker finished", project="zteam", duration_s=2.3)
```

完整 API：`get_logger` / `init_logging` / `load_config` / `load_config_dict` / `registered_names` / `reset_registry`；类：`Logger` / `Record` / `Sink` / `StdoutSink` / `StderrSink` / `FileSink` / `MemorySink` / `RotatingFileSink`；工具：`template(fmt)` / `parse_level(name)`。

## 输出格式

管式分隔便于无歧义解析：

```
{ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}
```

`line.split("|", 5)` 得 6 段：`ts` / `level` / `func:lineno` / `role` / `message` / `kv`（`kv` 为 `k=v k="quoted value"` 空格连接）。

## 配置文件

位置：`scripts/zlog/config/output_config.json`。全量字段：

```json
{
  "default_level": "INFO",
  "base_dir": "/var/log/zteam",
  "loggers": {
    "<name>": {
      "channel": "stdout" | ["stderr", "logs/x.log"],
      "level": "DEBUG",
      "single_file_size": 10485760,
      "file_count": 5,
      "rotation": "delete_oldest",
      "format": "{ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}"
    }
  }
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `default_level` | str/int | 否 | `"INFO"` | logger 自身未指定 `level` 时的兜底 |
| `base_dir` | str (绝对路径) | 否 | — | 文件通道相对路径的基准目录；必须是绝对路径且非空。未声明时所有文件通道路径必须为绝对路径 |
| `loggers` | dict | 是 | — | 命名 logger 字典 |
| `channel` | str 或 list[str] | 是 | — | `"stdout"` / `"stderr"` / `"memory"` / 文件路径（绝对或相对）；列表挂多 sink。相对路径在 `base_dir` 下拼接 |
| `level` | str/int | 否 | `default_level` | logger 级别阈值；接受 `"DEBUG"/"INFO"/"WARN"/"ERROR"/"CRITICAL"` 或 `10/20/30/40/50` |
| `single_file_size` | int | 仅 delete_oldest 文件通道 | — | 单文件字节上限；正整数 |
| `file_count` | int | 同上 | — | 磁盘保留文件总数（含当前）；≥ 1 |
| `rotation` | str | 否 | `"no_rotate"` | `"delete_oldest"`（写前轮转） / `"no_rotate"`（不轮转，外部 logrotate 接管） |
| `format` | str | 否 | `DEFAULT_FORMAT` | per-sink formatter 模板；占位符同输出格式 |

### 文件路径解析

- `channel` 是绝对路径：原样使用
- `channel` 是相对路径 + 声明了 `base_dir`：拼到 `base_dir` 下
- `channel` 是相对路径 + 未声明 `base_dir`：拒绝（`ValueError`）—— 防止在 `cwd` 漂移的环境里把日志写到意外目录
- `base_dir` 本身必须是绝对路径，否则 `ValueError`

## 使用约束

- 生产代码：禁止直接 `Logger(...)`；禁止运行时 `add_sink()`；必须先在 `output_config.json` 声明再 `get_logger`
- 测试代码：用 `tests/_helpers.py` 的 `ZlogTestCase`（自动重置 `_loggers` 和 `_initialized`）和 `test_get_logger`（按需懒注册）
