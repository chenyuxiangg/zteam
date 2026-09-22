"""角色模型/文件/中文名 + *_MODEL 环境变量。

ROLE_MODELS / ROLE_FILES / ROLE_CN 由下半部 worker spawn 使用（hermes chat
的 -m/--provider 参数 + role 指令文件）。所有 *_MODEL/*_PROVIDER 都可用同名
环境变量覆盖（cron job 由 gateway 启动，交互 shell 里 export 的变量到不了
gateway 进程——见 README 关于 systemctl --user edit hermes-gateway Environment=）。

状态机配置（STAGES/GATES/RELEASE）见 pipeline.py；本模块不依赖它。
"""
from __future__ import annotations

import os

from .paths import WORKDIR

__all__ = [
    # 配置常量
    "STALE_AFTER_MIN", "MAX_FAILURES", "DEFAULT_MAX_ROUNDS",
    # 模型/provider（环境变量可覆盖）
    "ANALYST_MODEL", "ANALYST_PROVIDER",
    "REVIEWER_MODEL", "REVIEWER_PROVIDER",
    "PLAN_DESIGNER_MODEL", "PLAN_REVIEWER_MODEL",
    "TESTPLAN_DESIGNER_MODEL", "TESTPLAN_REVIEWER_MODEL",
    "CODE_DEVELOPER_MODEL", "CODE_REVIEWER_MODEL", "CODE_PROVIDER",
    "TEST_DEVELOPER_MODEL", "TEST_REVIEWER_MODEL", "TEST_PROVIDER",
    "QUALITY_REVIEWER_MODEL", "SECURITY_REVIEWER_MODEL", "RELEASER_MODEL",
    "PM_MODEL", "SE_MODEL", "TE_MODEL", "FO_MODEL", "FO_PROVIDER",
    "IT_DESIGNER_MODEL", "IT_REVIEWER_MODEL",
    "ST_TESTER_MODEL", "ST_REVIEWER_MODEL",
    # 角色映射
    "ROLE_MODELS", "ROLE_FILES", "ROLE_CN",
]


# ---- 配置常量 ----

STALE_AFTER_MIN = int(os.environ.get("STALE_AFTER_MIN", "20"))   # 中间态超时（分钟）
MAX_FAILURES = int(os.environ.get("MAX_FAILURES", "2"))          # 连续失败上限
DEFAULT_MAX_ROUNDS = int(os.environ.get("DEFAULT_MAX_ROUNDS", "3"))


# ---- 模型/provider（环境变量可覆盖）----

ANALYST_MODEL = os.environ.get("ANALYST_MODEL", "deepseek-v4-flash")
ANALYST_PROVIDER = os.environ.get("ANALYST_PROVIDER", "deepseek")
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "deepseek-v4-pro")
REVIEWER_PROVIDER = os.environ.get("REVIEWER_PROVIDER", "deepseek")
# 阶段角色（设计/产出 = flash 快；评审/门禁 = pro 把关）
PLAN_DESIGNER_MODEL = os.environ.get("PLAN_DESIGNER_MODEL", "deepseek-v4-flash")
PLAN_REVIEWER_MODEL = os.environ.get("PLAN_REVIEWER_MODEL", "deepseek-v4-pro")
TESTPLAN_DESIGNER_MODEL = os.environ.get("TESTPLAN_DESIGNER_MODEL", "deepseek-v4-flash")
TESTPLAN_REVIEWER_MODEL = os.environ.get("TESTPLAN_REVIEWER_MODEL", "deepseek-v4-pro")
CODE_DEVELOPER_MODEL = os.environ.get("CODE_DEVELOPER_MODEL", "deepseek-v4-flash")
CODE_REVIEWER_MODEL = os.environ.get("CODE_REVIEWER_MODEL", "deepseek-v4-flash")
CODE_PROVIDER = os.environ.get("CODE_PROVIDER", "deepseek")  # 2026-08-15 临时切 DeepSeek
TEST_DEVELOPER_MODEL = os.environ.get("TEST_DEVELOPER_MODEL", "deepseek-v4-flash")
TEST_REVIEWER_MODEL = os.environ.get("TEST_REVIEWER_MODEL", "deepseek-v4-flash")
TEST_PROVIDER = os.environ.get("TEST_PROVIDER", "deepseek")  # 2026-08-15 临时切 DeepSeek
QUALITY_REVIEWER_MODEL = os.environ.get("QUALITY_REVIEWER_MODEL", "deepseek-v4-pro")
SECURITY_REVIEWER_MODEL = os.environ.get("SECURITY_REVIEWER_MODEL", "deepseek-v4-pro")
RELEASER_MODEL = os.environ.get("RELEASER_MODEL", "deepseek-v4-flash")
# v2 八角色独立模型（2026-08-13 用户调整：PM/SE/TE 用 pro 强推理；FO 用 MiniMax-M3）
PM_MODEL = os.environ.get("PM_MODEL", "deepseek-v4-pro")
SE_MODEL = os.environ.get("SE_MODEL", "deepseek-v4-pro")
TE_MODEL = os.environ.get("TE_MODEL", "deepseek-v4-pro")
FO_MODEL = os.environ.get("FO_MODEL", "MiniMax-M3")
FO_PROVIDER = os.environ.get("FO_PROVIDER", "minimax-cn")
IT_DESIGNER_MODEL = os.environ.get("IT_DESIGNER_MODEL", "deepseek-v4-flash")
IT_REVIEWER_MODEL = os.environ.get("IT_REVIEWER_MODEL", "deepseek-v4-pro")
ST_TESTER_MODEL = os.environ.get("ST_TESTER_MODEL", "deepseek-v4-flash")
ST_REVIEWER_MODEL = os.environ.get("ST_REVIEWER_MODEL", "deepseek-v4-pro")


# ---- 角色映射 ----

ROLE_MODELS: dict[str, tuple[str, str]] = {
    "req-analyst": (ANALYST_MODEL, ANALYST_PROVIDER),
    "pm": (PM_MODEL, ANALYST_PROVIDER),  # v2 PM（需求导入细化，麦肯锡+联网）— pro
    "se": (SE_MODEL, ANALYST_PROVIDER),  # v2 SE（架构设计，全量需求）— pro
    "te": (TE_MODEL, ANALYST_PROVIDER),  # v2 TE（整体测试方案）— pro
    "mde": (CODE_DEVELOPER_MODEL, CODE_PROVIDER),  # v2 MDE（模块设计，代码检视）
    "fo": (FO_MODEL, FO_PROVIDER),  # v2 FO（TDD 开发）— MiniMax-M3
    "mto": (TEST_DEVELOPER_MODEL, TEST_PROVIDER),  # v2 MTO（模块 IT）
    "sto": (ST_TESTER_MODEL, ANALYST_PROVIDER),  # v2 STO（版本系统测试）
    "qa": (QUALITY_REVIEWER_MODEL, ANALYST_PROVIDER),  # v2 QA（质量专员，发布）
    "req-reviewer": (REVIEWER_MODEL, REVIEWER_PROVIDER),
    "dev-plan-designer": (PLAN_DESIGNER_MODEL, ANALYST_PROVIDER),
    "dev-plan-reviewer": (PLAN_REVIEWER_MODEL, ANALYST_PROVIDER),
    "test-plan-designer": (TESTPLAN_DESIGNER_MODEL, ANALYST_PROVIDER),
    "test-plan-reviewer": (TESTPLAN_REVIEWER_MODEL, ANALYST_PROVIDER),
    "code-developer": (CODE_DEVELOPER_MODEL, CODE_PROVIDER),
    "code-reviewer": (CODE_REVIEWER_MODEL, CODE_PROVIDER),
    "test-developer": (TEST_DEVELOPER_MODEL, TEST_PROVIDER),
    "test-reviewer": (TEST_REVIEWER_MODEL, TEST_PROVIDER),
    "quality-reviewer": (QUALITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "security-reviewer": (SECURITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "releaser": (RELEASER_MODEL, ANALYST_PROVIDER),
    "it-designer": (IT_DESIGNER_MODEL, ANALYST_PROVIDER),
    "it-reviewer": (IT_REVIEWER_MODEL, ANALYST_PROVIDER),
    "st-tester": (ST_TESTER_MODEL, ANALYST_PROVIDER),
    "st-reviewer": (ST_REVIEWER_MODEL, ANALYST_PROVIDER),
}

ROLE_FILES: dict[str, str] = {
    "req-analyst": f"{WORKDIR}/roles/req-analyst.md",
    "pm": f"{WORKDIR}/roles/pm.md",  # v2 PM
    "se": f"{WORKDIR}/roles/se.md",  # v2 SE（架构师）
    "te": f"{WORKDIR}/roles/te.md",  # v2 TE（测试方案）
    "mde": f"{WORKDIR}/roles/mde.md",  # v2 MDE（模块设计）
    "fo": f"{WORKDIR}/roles/fo.md",  # v2 FO（TDD 开发）
    "mto": f"{WORKDIR}/roles/mto.md",  # v2 MTO（模块 IT）
    "sto": f"{WORKDIR}/roles/sto.md",  # v2 STO（系统测试）
    "qa": f"{WORKDIR}/roles/qa.md",  # v2 QA（质量专员）
    "req-reviewer": f"{WORKDIR}/roles/req-reviewer.md",
    "dev-plan-designer": f"{WORKDIR}/roles/dev-plan-designer.md",
    "dev-plan-reviewer": f"{WORKDIR}/roles/dev-plan-reviewer.md",
    "test-plan-designer": f"{WORKDIR}/roles/test-plan-designer.md",
    "test-plan-reviewer": f"{WORKDIR}/roles/test-plan-reviewer.md",
    "code-developer": f"{WORKDIR}/roles/code-developer.md",
    "code-reviewer": f"{WORKDIR}/roles/code-reviewer.md",
    "test-developer": f"{WORKDIR}/roles/test-developer.md",
    "test-reviewer": f"{WORKDIR}/roles/test-reviewer.md",
    "quality-reviewer": f"{WORKDIR}/roles/quality-reviewer.md",
    "security-reviewer": f"{WORKDIR}/roles/security-reviewer.md",
    "releaser": "roles/releaser.md",
    "it-designer": "roles/it-designer.md",
    "it-reviewer": "roles/it-reviewer.md",
    "st-tester": "roles/st-tester.md",
    "st-reviewer": "roles/st-reviewer.md",
}

ROLE_CN: dict[str, str] = {
    "req-analyst": "需求分析师", "req-reviewer": "需求评审师",
    "pm": "PM（需求导入与细化）",
    "se": "SE（架构设计）",
    "te": "TE（整体测试方案）",
    "mde": "MDE（模块设计）",
    "fo": "FO（开发者，TDD）",
    "mto": "MTO（模块测试者，IT）",
    "sto": "STO（系统测试者，ST）",
    "qa": "QA（质量专员）",
    "dev-plan-designer": "开发方案设计者", "dev-plan-reviewer": "开发方案评审者",
    "test-plan-designer": "测试方案设计者", "test-plan-reviewer": "测试方案评审者",
    "code-developer": "代码开发者", "code-reviewer": "代码评审者",
    "test-developer": "测试开发者", "test-reviewer": "测试评审者",
    "quality-reviewer": "质量评审者", "security-reviewer": "安全红线评审者",
    "releaser": "发布者",
    "it-designer": "集成测试设计执行者", "it-reviewer": "集成测试评审者",
    "st-tester": "系统测试执行者", "st-reviewer": "系统测试评审者",
}