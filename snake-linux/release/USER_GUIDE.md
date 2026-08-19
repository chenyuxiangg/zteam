# 用户指南：Snake GUI v2.0.0

> 跨平台贪吃蛇游戏 · 三平台免安装单文件可执行

---

## 1. 下载与运行

### 1.1 下载地址

- **Linux**：[snake-gui-linux-x86_64](https://example.com/snake-gui-linux-x86_64)（约 25MB）
- **Windows**：[snake-gui-windows-x86_64.exe](https://example.com/snake-gui-windows-x86_64.exe)（约 25MB）
- **macOS**：[snake-gui-macos-universal2.app](https://example.com/snake-gui-macos-universal2.app)（约 30MB，支持 Intel + Apple Silicon）

下载后请校验 SHA256 校验和（参见 `SHA256SUMS` 文件）。

### 1.2 运行方式

#### Linux

```bash
chmod +x snake-gui-linux-x86_64
./snake-gui-linux-x86_64
```

如提示缺少 SDL2 库：

```bash
# Ubuntu / Debian
sudo apt install libsdl2-2.0-0

# Fedora
sudo dnf install SDL2

# Arch
sudo pacman -S sdl2
```

#### Windows

双击 `snake-gui-windows-x86_64.exe` 即可运行。

如 Windows SmartScreen 提示"未知发布者"，点击"更多信息" → "仍要运行"。

#### macOS

双击 `snake-gui-macos-universal2.app` 即可运行。

如 macOS Gatekeeper 提示"无法打开，因为无法验证开发者"，在"系统设置" → "隐私与安全性"中点击"仍要打开"。

### 1.3 系统要求

| 平台 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Linux | Ubuntu 22.04+ / Fedora 36+ / Arch（最新） | 同左 |
| Windows | Windows 10 | Windows 10 / 11 |
| macOS | macOS 12 (Monterey) | macOS 13 (Ventura) 或更新 |

无需预装 Python / Node / Java 等任何运行时。

---

## 2. 键位表

| 键 | 功能 |
|----|------|
| W / ↑ | 向上转向 |
| S / ↓ | 向下转向 |
| A / ← | 向左转向 |
| D / → | 向右转向 |
| P | 暂停 / 继续 |
| 1 | 选择简单难度 |
| 2 | 选择普通难度 |
| 3 | 选择困难难度 |
| ← | 菜单态切换上一皮肤 |
| → | 菜单态切换下一皮肤 |
| R | 结束画面重新开始 |
| H | 重置最高分 |
| ESC | 返回菜单（在结束画面） |
| Q | 退出游戏（任意时刻） |
| 窗口关闭按钮 | 退出游戏 |

---

## 3. 难度

游戏提供三档难度（游戏中不可切换，需返回菜单重新选择）：

| 难度 | 节拍 | 说明 |
|------|------|------|
| 简单 | 250ms / 格 | 蛇速慢，适合新手 |
| 普通 | 160ms / 格 | 蛇速适中，标准体验 |
| 困难 | 100ms / 格 | 蛇速快，挑战极限 |

档位间节拍差异显著（困难 ≤ 简单 50%）。蛇身增长后会自动加速（加速曲线）。

---

## 4. 皮肤

游戏提供 3 套皮肤（在菜单界面用 ← / → 切换）：

| 皮肤 | 特点 |
|------|------|
| 经典 | 默认配色，白底深色蛇 |
| 深色 | 深色主题，适合夜间游戏 |
| 色盲友好 | 叠加形状/纹理辨识（不以颜色为唯一区分），适合色盲用户 |

皮肤切换即时生效，不中断当前对局。

---

## 5. 暂停

游戏中按 P 键暂停，再按 P 键继续。

暂停时画面定格，节拍停止。窗口失焦也会自动暂停。

---

## 6. 平台差异

| 平台 | 字体 | 数据目录 | 已知问题 |
|------|------|---------|---------|
| Linux | 打包内置字体优先，系统字体回退 | `~/.local/share/snake-gui/highscore.json` | 部分 Linux 发行版需手动安装 SDL2 库 |
| Windows | 打包内置字体 | `%APPDATA%\snake-gui\highscore.json` | SmartScreen 首次运行需手动确认 |
| macOS | 系统字体 | `~/Library/Application Support/snake-gui/highscore.json` | Gatekeeper 首次运行需手动确认；macOS <12 兼容性未充分测试 |

---

## 7. 已知限制

- **未签名 / 未公证**：Windows SmartScreen / macOS Gatekeeper 首次运行会触发警告（手动确认即可）
- **macOS <12**：未充分测试，可能存在兼容性问题
- **窗口缩放**：依赖 pygame VIDEORESIZE 事件流；若显卡驱动版本异常，可能无法拖拽窗口
- **中文显示**：依赖打包内置字体（SourceHanSansCN-Regular.otf，OFL 协议）；若字体文件损坏，将回退到系统字体或 SDL 默认字体（中文显示为方框）
- **HiDPI 缩放**：默认启用；若显卡驱动不支持，将自动降级到非缩放模式（可能略糊）
