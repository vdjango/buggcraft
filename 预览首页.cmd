@echo off
setlocal
set "BUGG_PREVIEW_EXE=%~dp0build\bugg.exe"
if not exist "%BUGG_PREVIEW_EXE%" (
  echo Build the native Qt preview first: tools\build_native.cmd
  pause
  exit /b 1
)
if not defined BUGG_QT_ROOT set "BUGG_QT_ROOT=%~dp0..\.tools\Qt\6.8.1\msvc2022_64"
set "PATH=%BUGG_QT_ROOT%\bin;%PATH%"
start "" "%BUGG_PREVIEW_EXE%" --theme classic
