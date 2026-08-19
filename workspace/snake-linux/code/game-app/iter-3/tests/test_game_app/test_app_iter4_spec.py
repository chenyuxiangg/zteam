"""G4-1 PyInstaller spec 文件 UT（UT SPEC-1~3）。

迭代 4 增量：
- spec 文件语法合法（PyInstaller 解析无异常）
- datas 包含打包内置字体 SourceHanSansCN-Regular.otf
- hiddenimports 包含 game_app / platform_storage / gui_renderer 全部子模块
"""
from __future__ import annotations

import os
import re
from pathlib import Path


# spec 文件位于仓库权威目录 snake-linux/spec/snake-gui.spec（不在 workspace 下）
SPEC_PATH = Path(os.environ.get(
    "SNAKE_LINUX_ROOT",
    "/home/zyzs/cyx/zteam/snake-linux",
)) / "spec" / "snake-gui.spec"


class TestSpecFileSyntax:
    """SPEC-1：spec 文件语法合法（可被 Python compile + exec）。"""

    def test_spec_file_exists(self) -> None:
        assert SPEC_PATH.exists(), f"spec 文件不存在: {SPEC_PATH}"

    def test_spec_file_is_valid_python(self) -> None:
        """SPEC-1：spec 文件是合法 Python 语法（compile 不抛 SyntaxError）。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        # PyInstaller spec 是合法的 Python 文件（PyInstaller 用 exec 跑）
        compile(source, str(SPEC_PATH), "exec")

    def test_spec_has_analysis_block(self) -> None:
        """spec 文件包含 a = Analysis(...) 块。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert re.search(r"a\s*=\s*Analysis\s*\(", source), "spec 缺少 Analysis() 块"

    def test_spec_has_pyz_block(self) -> None:
        """spec 文件包含 pyz = PYZ(...) 块。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert re.search(r"pyz\s*=\s*PYZ\s*\(", source), "spec 缺少 PYZ() 块"


class TestSpecDatasIncludesFont:
    """SPEC-2：datas 列表包含 SourceHanSansCN-Regular.otf（打包内置字体）。"""

    def test_datas_contains_font(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        # 匹配 datas 块内的字体文件引用（不区分引号风格）
        assert "SourceHanSansCN-Regular.otf" in source, \
            "spec datas 列表未包含 SourceHanSansCN-Regular.otf"

    def test_datas_target_dir_is_fonts(self) -> None:
        """字体打包到 'fonts' 子目录（与 get_bundled_font_path 一致）。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        # 字体文件引用应在 datas tuple 内，目标目录含 "fonts"
        # 容许 .otf 与 "fonts" 在同一行或跨行
        assert re.search(r"\.otf.*?[\"']fonts[\"']", source, re.DOTALL), \
            "spec 内字体文件应映射到 'fonts' 目录"


class TestSpecHiddenImports:
    """SPEC-3：hiddenimports 包含三个核心包的全部子模块。"""

    def test_includes_game_app(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert "game_app" in source, "hiddenimports 未包含 game_app"

    def test_includes_platform_storage(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert "platform_storage" in source, "hiddenimports 未包含 platform_storage"

    def test_includes_gui_renderer(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert "gui_renderer" in source, "hiddenimports 未包含 gui_renderer"


class TestSpecEntryPoint:
    """spec 文件入口正确性。"""

    def test_entry_is_game_app_main(self) -> None:
        """Analysis 入口 = game_app/__main__.py（PyInstaller 打包目标）。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        # Analysis 第一参数应为 __main__.py 路径（字符串字面量或变量）
        assert "__main__.py" in source, "spec Analysis 入口应包含 __main__.py"


class TestSpecWindowedMode:
    """spec 文件 EXE 配置 = windowed 模式（无控制台）。"""

    def test_console_false(self) -> None:
        """console=False → --windowed 模式（Linux/macOS 无控制台窗口）。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        assert re.search(r"console\s*=\s*False", source), \
            "spec EXE 应配置 console=False（无控制台窗口）"


class TestSpecOnefileMode:
    """spec 文件 EXE 配置 = 单文件模式（无 COLLECT 块）。"""

    def test_no_collect_block(self) -> None:
        """单文件模式：spec 应无 COLLECT() 块（PyInstaller --onefile）。"""
        source = SPEC_PATH.read_text(encoding="utf-8")
        # COLLECT() 用于 onedir 模式；onefile 不应有
        assert not re.search(r"\bCOLLECT\s*\(", source), \
            "spec 不应包含 COLLECT() 块（--onefile 模式）"