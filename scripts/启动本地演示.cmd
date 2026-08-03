@echo off
setlocal
pushd "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_local_demo.ps1" -SkipInstall -OpenBrowser
if errorlevel 1 (
  echo.
  echo Startup failed. Read the message above, then press any key to close.
  pause >nul
)
popd
endlocal
