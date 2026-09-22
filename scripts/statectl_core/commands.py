"""人工/调试命令（CLI 子命令）。

暂留说明：当前 commands.py 为占位。cmd_* 函数（cmd_register / cmd_stale / cmd_next /
cmd_claim / cmd_setpid / cmd_rollback / cmd_record_product / cmd_requeue /
cmd_set_status / cmd_resume / cmd_list / cmd_get / cmd_halt / cmd_unhalt /
cmd_notify / cmd_project / cmd_assign / cmd_change_request）仍保留在
scripts/statectl.py 里（约 1000 行）——这些函数大量依赖模块级常量与
按需 import 的小工具，分散拆出风险高、收益低（仅 CLI 入口）。

下一阶段（commit 6+）拆分计划：
  1) 提取辅助：STAGES / GATES / RELEASE / STAGE_FOUR_STATES 到 pipeline.py
  2) 抽 cmd_* 入 commands.py，统一 import 自 statectl_core.{paths,status,pipeline,...}
  3) main() 由 commands.main() 提供（取代 statectl.py 末端的 main）
  4) statectl.py 退化为 5 行 thin shim：from statectl_core import main; sys.exit(main(...))
"""

__all__: list[str] = []