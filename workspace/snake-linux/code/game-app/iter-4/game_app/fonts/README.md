# 内置字体：SourceHanSansCN-Regular.otf

本目录包含游戏打包内置的中文字体文件，用于保证三平台中文显示一致
（规避 Linux 发行版字体版本差异导致的中文字形缺失）。

## 字体信息

- **文件名**：`SourceHanSansCN-Regular.otf`
- **字体**：思源黑体（Source Han Sans）简体中文 Regular 字重
- **协议**：SIL Open Font License 1.1（OFL-1.1）
- **上游**：Adobe Fonts / Google Fonts（Noto Sans CJK SC 同源）
- **来源**：https://github.com/adobe-fonts/source-han-sans （release 分支 SubsetOTF/CN/）

## 使用方式

- 源码运行：`game_app/fonts/SourceHanSansCN-Regular.otf` 由
  `_constants.get_bundled_font_path()` 通过 `__file__` 邻近路径发现；
- PyInstaller 打包：`spec/snake-gui.spec` 的 `datas` 列表将该文件注入
  `fonts/` 目录，运行时通过 `sys._MEIPASS` 定位。

## 回退链

若本文件缺失/损坏，`_load_cjk_font()` 依次回退：
1. `pygame.font.match_font` 系统字体链（notosanscjksc / wenquanyizenhei / ...）
2. `pygame.font.Font(None, size)` SDL 默认字体（中文显示为方框，仅 ASCII）

## OFL-1.1 许可摘要

- 允许自由使用、复制、修改、再分发（含商业用途）；
- 不得单独出售字体文件；
- 修改后的字体不得使用原字体名称；
- 再分发需保留本协议文本。

完整协议文本见：https://openfontlicense.org/ （OFL-1.1）
