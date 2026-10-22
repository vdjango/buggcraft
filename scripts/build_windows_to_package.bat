@echo off
setlocal
call "%~dp0..\build.bat" %*
exit /b %errorlevel%
