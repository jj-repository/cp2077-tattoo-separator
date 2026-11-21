@echo off
rem Starts the Tattoo Switchers GUI. Needs Python 3.8+ and Pillow (pip install pillow).
cd /d "%~dp0"
where python >nul 2>nul || (echo Python was not found. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
python tattoo_switcher_gui.py
if errorlevel 1 pause
