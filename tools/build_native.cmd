@echo off
setlocal
chcp 65001 >nul
set "VSLANG=1033"
if not defined BUGG_QT_ROOT set "BUGG_QT_ROOT=%~dp0..\..\.tools\Qt\6.8.1\msvc2022_64"
if not defined VSCMD_VER call "D:\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
set "PATH=%BUGG_QT_ROOT%\bin;D:\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
cmake -S "%~dp0.." -B "%~dp0..\build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="%BUGG_QT_ROOT%" "-DCMAKE_CL_SHOWINCLUDES_PREFIX=Note: including file: "
if errorlevel 1 exit /b 1
cmake --build "%~dp0..\build" --parallel 6
exit /b %errorlevel%
