@echo off
chcp 936 >nul
cd /d "%~dp0"
echo H3VR2 Save Editor - starting...
py -3.10 h3vr2_save_editor.py
if errorlevel 1 (
  echo.
  echo [ERROR] Python 3.10 with tkinter is required.
  echo Try: py -3.10 h3vr2_save_editor.py
  pause
)
