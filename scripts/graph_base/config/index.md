# graph 配置索引

约定：配置文件名、配置内 `name` 字段、`src/worker/<name>/` worker 包三者同名。
`name` 被用于两处解析——dispatcher 按 `src.worker.{name}.{node}_worker` 拉起子进程，
worker 再按 `config/{name}_graph.json` 回读本配置，改名时三处必须同步。

- `software_team_graph.json`: 软件开发流程SOP，支持需求分析、方案设计、V型开发、质量检查与发布的全过程。
- `test_for_e2e_graph.json`: e2e 测试图。harvester 自环 3 次（gate 按 exit_cnt 阈值翻转）后切到 qa_reviewer，
  qa → publisher 是 manual 边，需外部 trigger 才推进。覆盖自环阈值、manual trigger、多产物文件、跨实例并发隔离。
- `test_for_complex_graph.json`: 并行 fan-out 测试图。fetcher 经 3 条 parallel 边同时派发 worker_a/b/c，
  joiner 等三者产物齐全后推进，verifier 首轮 invalid 自环、次轮 valid 才放行到 publisher。
