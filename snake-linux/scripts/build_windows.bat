@echo off
REM scripts/build_windows.bat — Windows .exe 构建脚本（iter-4 G4-1）
REM 用途：在 Windows 构建机上产出 dist\snake-gui.exe（单文件可执行）
REM 前置：Python 3.8+ / pip install pyinstaller==5.13+
REM
REM 使用：
REM   cd snake-linux\
REM   scripts\build_windows.bat

setlocal

cd /d "%~dp0.."

REM 清理
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 构建
pyinstaller --clean --noconfirm spec\snake-gui.spec
if errorlevel 1 (
    echo [build_windows] 失败: pyinstaller 构建错误
    exit /b 1
)

REM 重命名产物
if exist dist\snake-gui.exe (
    ren dist\snake-gui.exe snake-gui-windows-x86_64.exe
    echo [build_windows] 完成: dist\snake-gui-windows-x86_64.exe
) else (
    echo [build_windows] 失败: dist\snake-gui.exe 未生成
    exit /b 1
)

REM r2 P2-1/P2-2：构建脚本只产包，不生成 SHA256SUMS
REM （certutil 输出格式与标准 sha256sum 不一致；由 gen_sha256sums.sh 统一生成）

endlocal
