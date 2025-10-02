@echo off
setlocal

REM 创建虚拟环境（如果不存在）
if not exist "packenv\" (
    python -m venv venv
)

REM 激活虚拟环境
call venv\Scripts\activate.bat
python .\src\buggcraft\main.py