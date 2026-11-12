@echo off
chcp 65001 >nul
cd /d "%~dp0"
title InveNOIR Chorus Battle v16 - Group Finder + Member Profiles

echo ===========================================
echo InveNOIR v16 - folder: %CD%
echo ===========================================
if not exist ".env" (
  echo ERROR: .env not found.
  echo Copy your working .env from the bot version you currently use.
  pause
  exit /b 1
)
py -3 -m pip install -r "requirements.txt"
if errorlevel 1 (
  echo ERROR: Could not install packages
  pause
  exit /b 1
)
py -3 "TEST_V16_LOCAL.py"
if errorlevel 1 (
  echo ERROR: Local validation failed. Do not continue.
  pause
  exit /b 1
)
py -3 "InveNOIR_Chorus_Battle_Bot_v16.py" --check
if errorlevel 1 (
  echo ERROR: InveNOIR local validation failed.
  pause
  exit /b 1
)
py -3 "InveNOIR_Chorus_Battle_Bot_v16.py"
echo.
echo Bot stopped. Read any errors above.
pause
