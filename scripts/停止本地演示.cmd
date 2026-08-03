@echo off
setlocal
pushd "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\stop_local_demo.ps1"
if errorlevel 1 (
  echo.
  echo Stop failed. Read the message above, then press any key to close.
  pause >nul
)
popd
endlocal
