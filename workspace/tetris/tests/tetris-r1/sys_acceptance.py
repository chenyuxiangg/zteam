# -*- coding: utf-8 -*-
"""tetris 系统层半自动验收脚本——TC-S-01~06 中可脚本化部分。

依据测试方案 workspace/testplans/tetris/tetris-r2.md §3.2 用例表：
    TC-S-01 (P0) 干净环境按 README 跑通（子场景：启动命令可执行、可退出）
    TC-S-02 (P1) README 五节齐全 + r2 增量核对（curses vs ANSI 选型结论 /
                 42×26 推导 / 单文件分层声明）
    TC-S-04 (P1) 非 TTY + 过小终端 + 非法参数三场景无裸 traceback
    TC-S-05 (P2) 代码职责分离走查（结构检查：类/函数分层存在）
    TC-S-06 (P2) Python 版本矩阵冒烟（py_compile + 当前版本启动冒烟）

人工清单项（TC-S-01 完整跑通一局、TC-S-03 终端矩阵、TC-S-05 代码可读性、
TC-S-06 3.6/3.8/3.12 实机）见同目录 system_checklist.md，由验收人在真实终端逐项勾选。

运行：python3 sys_acceptance.py   （半自动：脚本 + 人工清单）
"""
import os
import re
import subprocess
import sys

CODE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..', '..', 'code', 'tetris', 'tetris-r2',
                                     'tetris.py'))
README = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       '..', '..', '..', 'code', 'tetris', 'tetris-r2',
                                       'README.md'))
ENV = dict(os.environ, TERM='xterm-256color')

PASS = 0
FAIL = 0


def report(tc_id, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1
        print('[PASS] %s %s' % (tc_id, detail))
    else:
        FAIL += 1
        print('[FAIL] %s %s' % (tc_id, detail))


def tc_s01_clean_env_smoke():
    """TC-S-01 (P0, FR-01/25)：README 启动命令可执行、可正常退出（子场景）。

    完整「玩一局至结束」由人工清单在真实终端完成。
    """
    # 启动命令存在性：README 中「运行方式」的命令与交付物一致
    with open(README, encoding='utf-8') as f:
        readme = f.read()
    ok_cmd = 'python3 tetris.py' in readme
    # 冒烟：--help 可执行且 exit 0（证明入口可用、无 import 错误）
    r = subprocess.run(['python3', CODE, '--help'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=10, env=ENV)
    ok_help = r.returncode == 0 and b'--tick' in r.stdout and b'--no-color' in r.stdout
    report('TC-S-01', ok_cmd and ok_help,
           'readme_cmd=%s help_exit=%s' % (ok_cmd, r.returncode))


def tc_s02_readme_sections():
    """TC-S-01/25 附属 (P1, FR-25)：README 五节齐全 + r2 增量核对。

    r2 增量（方案 §3.2 TC-S-02）：README「已知限制」含 curses vs ANSI 选型
    取舍结论（分析 §2.2/Q-09 路径①）、42×26 尺寸推导说明、单文件分层声明。
    """
    with open(README, encoding='utf-8') as f:
        readme = f.read()
    sections = {
        '运行方式': '## 一、运行方式' in readme,
        '依赖': '## 二、依赖' in readme,
        '键位表': '## 三、键位表' in readme,
        '配置项': '## 四、配置项' in readme,
        '已知限制': '## 五、已知限制' in readme,
    }
    # r2 增量核对（TC-S-02 新增核对项）
    r2_checks = {
        '选型结论(curses)': 'curses' in readme and ('ANSI' in readme or '裸 ANSI' in readme),
        '42x26推导': ('42×26' in readme or '42x26' in readme) and '推导' in readme,
        '单文件分层声明': '单文件' in readme and '分层' in readme,
    }
    ok_all = all(sections.values()) and all(r2_checks.values())
    report('TC-S-02', ok_all,
           'sections=%s r2增量=%s' % (sections, r2_checks))


def tc_s04_no_traceback_scenarios():
    """TC-S-04 (P1, NFR-04)：非 TTY/过小终端/非法参数三场景 stderr 无 traceback。"""
    results = []
    # 场景 1：非 TTY
    r1 = subprocess.run(['python3', CODE], stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, env=ENV)
    results.append(('non-tty', r1.returncode, r1.stderr))
    # 场景 2：非法参数（tick 越界）
    r2 = subprocess.run(['python3', CODE, '--tick', '9999'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, env=ENV)
    results.append(('bad-tick', r2.returncode, r2.stderr))
    # 场景 3：非数字参数
    r3 = subprocess.run(['python3', CODE, '--tick', 'abc'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, env=ENV)
    results.append(('bad-arg', r3.returncode, r3.stderr))
    ok = True
    detail = []
    for name, code, err in results:
        text = err.decode('utf-8', 'replace')
        no_tb = 'Traceback' not in text
        readable = len(text.strip()) > 0
        nonzero = code != 0
        ok = ok and no_tb and readable and nonzero
        detail.append('%s:exit=%d tb=%s' % (name, code, (not no_tb)))
    report('TC-S-04', ok, '; '.join(detail))


def tc_s05_code_structure():
    """TC-S-05 (P2, NFR-05)：代码职责分离结构检查（可脚本化部分）。

    人工走查（可读性/注释/无全局可变状态）见 system_checklist.md TC-S-05。
    """
    with open(CODE, encoding='utf-8') as f:
        src = f.read()
    has_config = 'def parse_args' in src
    has_model = 'class GameState' in src
    has_input = 'class InputHandler' in src
    has_render = 'class Renderer' in src
    has_main = 'def main(' in src
    has_wrapper = 'curses.wrapper' in src
    has_tetrominoes = 'TETROMINOES' in src and 'def rotate_cw' in src
    has_collides = 'def collides' in src
    has_clearlines = 'def clear_lines' in src
    ok = all([has_config, has_model, has_input, has_render, has_main,
              has_wrapper, has_tetrominoes, has_collides, has_clearlines])
    report('TC-S-05', ok,
           'config=%s model=%s input=%s render=%s main=%s wrapper=%s shapes=%s'
           % (has_config, has_model, has_input, has_render, has_main,
              has_wrapper, has_tetrominoes))


def tc_s06_py_compile_matrix():
    """TC-S-06 (P2, Q-05)：py_compile 通过（语法兼容性冒烟）。

    本机仅 Python 3.11；3.6/3.8/3.12 实机冒烟见 system_checklist.md TC-S-06。
    """
    r = subprocess.run([sys.executable, '-m', 'py_compile', CODE],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    ok_compile = r.returncode == 0
    # 3.7+ 专属语法检查（dataclass/海象/f-string 调试格式）——源码不应出现
    with open(CODE, encoding='utf-8') as f:
        src = f.read()
    no_walrus = re.search(r'[a-zA-Z_]\s*:=', src) is None
    no_dataclass = 'from dataclasses' not in src and 'import dataclass' not in src
    no_removeprefix = '.removeprefix(' not in src
    ok = ok_compile and no_walrus and no_dataclass and no_removeprefix
    report('TC-S-06', ok,
           'compile=%s walrus_absent=%s dataclass_absent=%s removeprefix_absent=%s'
           % (ok_compile, no_walrus, no_dataclass, no_removeprefix))


def main():
    print('=== tetris r1 系统验收（半自动，TC-S-01~06 脚本部分）===')
    print('被测代码: %s' % CODE)
    print()
    tc_s01_clean_env_smoke()
    tc_s02_readme_sections()
    tc_s04_no_traceback_scenarios()
    tc_s05_code_structure()
    tc_s06_py_compile_matrix()
    print()
    print('=== 汇总: PASS=%d FAIL=%d ===' % (PASS, FAIL))
    print('注意：人工清单项（TC-S-01 完整一局 / TC-S-03 终端矩阵 /')
    print('      TC-S-05 可读性走查 / TC-S-06 多版本实机）见 system_checklist.md')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
