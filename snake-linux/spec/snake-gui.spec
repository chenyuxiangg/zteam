# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for snake-gui v2.0.0（iter-4 G4-1）。

使用方法：
  cd snake-linux/
  pyinstaller --clean --noconfirm spec/snake-gui.spec

或在 scripts/build_*.{sh,bat} 中调用：
  pyinstaller --clean --noconfirm spec/snake-gui.spec

迭代 4 增量（G4-1 + G4-5，检视 F-1 修订）：
- datas：打包内置字体 SourceHanSansCN-Regular.otf（OFL 协议开源中文字体）
- hiddenimports：全量收集 game_app / platform_storage / gui_renderer 子模块
- EXE：--onefile --windowed --name snake-gui + console=False
- 排除：tkinter / unittest / pydoc / doctest（避免无关模块打入）
- pathex：含三依赖包源码目录（r2 P0-1）
- GAME_APP_DIR：候选探测（检视 F-1 修订）——代码可能位于资产层
  （snake-linux/code/）或数据层（workspace/snake-linux/code/），且迭代
  目录为 iter-4 或 iter-3（iter-4 不新建目录，同 v2.0.0 一个发布单元）。
  候选顺序：资产层 iter-4 → 资产层 iter-3 → 数据层 iter-4 → 数据层 iter-3，
  与 scripts/bench_fps.py 的 _CANDIDATES 一致；三依赖包在同 code_root 下
  按已知迭代目录探测。
"""

import os

from PyInstaller.utils.hooks import collect_submodules


def _first_existing(candidates, marker_file):
    """返回第一个包含 marker 文件的目录（归一化为绝对路径）。

    检视 F-1 修订：必须用文件存在性（marker_file）判定而非 os.path.isdir——
    资产层可能存在空壳目录（如 code/game-app/iter-3/game_app/ 仅含空 fonts/），
    isdir 会误命中导致入口指向空目录、构建必败。

    全部候选均无 marker 时返回第一个（让 PyInstaller Analysis 报错保持可读）。
    """
    for c in candidates:
        if os.path.isfile(os.path.join(c, marker_file)):
            return os.path.abspath(c)
    return os.path.abspath(candidates[0])


# ---- 候选探测（检视 F-1 修订：spec 不再硬编码资产层 iter-3） ----
# SPECPATH = snake-linux/spec/（PyInstaller 注入）；数据层根 = SPECPATH/../../workspace/snake-linux
GAME_APP_CANDIDATES = [
    os.path.join(SPECPATH, "..", "code", "game-app", "iter-4", "game_app"),   # 资产层 iter-4
    os.path.join(SPECPATH, "..", "code", "game-app", "iter-3", "game_app"),   # 资产层 iter-3
    os.path.join(SPECPATH, "..", "..", "workspace", "snake-linux", "code", "game-app", "iter-4", "game_app"),  # 数据层 iter-4
    os.path.join(SPECPATH, "..", "..", "workspace", "snake-linux", "code", "game-app", "iter-3", "game_app"),  # 数据层 iter-3
]
GAME_APP_DIR = _first_existing(GAME_APP_CANDIDATES, "__main__.py")

# 三依赖包与 game_app 同 code_root（GAME_APP_DIR = <code_root>/game-app/<iter>/game_app，
# dirname 三次：game_app → <iter> → game-app → code_root）
_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(GAME_APP_DIR)))

GAME_CORE_DIR = _first_existing([
    os.path.join(_CODE_ROOT, "game-core", "iter-2"),
    os.path.join(_CODE_ROOT, "game-core", "iter-1"),
], os.path.join("game_core", "__init__.py"))
GUI_RENDERER_DIR = _first_existing([
    os.path.join(_CODE_ROOT, "gui-renderer", "iter-3"),
    os.path.join(_CODE_ROOT, "gui-renderer", "iter-1"),
], os.path.join("gui_renderer", "__init__.py"))
PLATFORM_STORAGE_DIR = _first_existing([
    os.path.join(_CODE_ROOT, "platform-storage", "iter-2"),
], os.path.join("platform_storage", "__init__.py"))


block_cipher = None


# iter-4 G4-5：打包内置字体文件（OFL 协议；r2 修订：目标子目录 fonts/ 与
# _constants.get_bundled_font_path 一致）
datas = [
    (os.path.join(GAME_APP_DIR, "fonts", "SourceHanSansCN-Regular.otf"), "fonts"),
]


# iter-4 G4-1：全量收集子模块（game_app + platform_storage + gui_renderer）
hiddenimports = []
hiddenimports.extend(collect_submodules("game_app"))
hiddenimports.extend(collect_submodules("platform_storage"))
hiddenimports.extend(collect_submodules("gui_renderer"))


a = Analysis(
    [os.path.join(GAME_APP_DIR, "__main__.py")],
    # r2 P0-1 + 检视 F-1：pathex 必须含解析后的 GAME_APP_DIR 与三依赖包目录
    pathex=[GAME_APP_DIR, GAME_CORE_DIR, GUI_RENDERER_DIR, PLATFORM_STORAGE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",  # 移除不需要的 tkinter
        "unittest",  # 移除测试模块
        "pydoc",    # 移除文档模块
        "doctest",  # 移除 doctest
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="snake-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 禁用 UPX 压缩（避免杀毒软件误报）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --windowed：无控制台窗口（Windows / macOS）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # macOS 由 --target-arch 参数决定
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可选：添加 .ico 文件路径
)
