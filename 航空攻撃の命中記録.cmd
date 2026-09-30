@echo off
setlocal
cd /d "%~dp0"
set "recorder_python=.venv\Scripts\python.exe"
if not exist "%recorder_python%" set "recorder_python=..\combat-recorder\.venv\Scripts\python.exe"
if not exist "%recorder_python%" (
  echo Run setup.cmd first. See README.md.
  pause
  exit /b 1
)
"%recorder_python%" navalhitrecorder.py --mode air %*
if errorlevel 1 (
  pause
  exit /b 1
)
