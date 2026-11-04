@echo off
rem Local PC demo only. Change this path if Anaconda is moved.
set "BY02_PYTHON=D:\Anaconda3\python.exe"
if not exist "%BY02_PYTHON%" (
  echo Python not found. Edit BY02_PYTHON in this file.
  pause
  exit /b 2
)
cd /d "%~dp0"
"%BY02_PYTHON%" run_vision.py
set "BY02_RESULT=%ERRORLEVEL%"
pause
exit /b %BY02_RESULT%
