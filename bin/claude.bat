@echo off
setlocal enabledelayedexpansion
for %%P in (py python python3) do (
  %%P -c "import sys; assert sys.version_info>=(3,8)" 2>nul
  if not errorlevel 1 (
    %%P "%~dp0claude.py" %*
    exit /b !errorlevel!
  )
)
echo [claude-box] Python 3.8+ not found. Install it and ensure 'py', 'python', or 'python3' is on your PATH.
exit /b 1
