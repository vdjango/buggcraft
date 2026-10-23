@echo off
setlocal

REM 创建虚拟环境（如果不存在）
if not exist ".venv\Scripts\pythonw.exe" if not exist "venv\Scripts\pythonw.exe" (
    python -m venv venv
)

REM 使用无控制台入口，启动后不保留 CMD 窗口
start "" wscript.exe "%~dp0launch-hidden.vbs"
