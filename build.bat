@echo off
setlocal
cd /d "%~dp0"
set "BUILD_PYTHON=%~dp0.build-venv\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
    py -3.11 -m venv "%~dp0.build-venv"
    if errorlevel 1 exit /b 1
)
"%BUILD_PYTHON%" -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1
"%BUILD_PYTHON%" -m pip check
if errorlevel 1 exit /b 1
"%BUILD_PYTHON%" build.py %*
exit /b %errorlevel%
