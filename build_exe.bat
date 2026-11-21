@echo off
rem Builds the one-folder Windows version in dist\TattooSwitcher\ (users then need no Python).
rem Run from this folder with Python 3.8+ installed. Uses a local .venv so nothing else is changed.
rem Optional: set VENV / DIST / WORK to other folders before running.
cd /d "%~dp0"
if "%VENV%"=="" set "VENV=%~dp0.venv"
if "%DIST%"=="" set "DIST=%~dp0dist"
if "%WORK%"=="" set "WORK=%~dp0pyi_build"
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%" || exit /b 1
"%VENV%\Scripts\python" -m pip install --upgrade pillow pyinstaller || exit /b 1
rem tools\ on the search path so split_overlay is bundled; unused stdlib parts left out to keep it small
"%VENV%\Scripts\python" -m PyInstaller --noconfirm --clean --onedir --windowed --name TattooSwitcher ^
  --distpath "%DIST%" --workpath "%WORK%" --specpath "%WORK%" ^
  --paths "%~dp0tools" --add-data "%~dp0options.example.json;." ^
  --exclude-module numpy --exclude-module unittest --exclude-module pydoc --exclude-module doctest ^
  --exclude-module xmlrpc --exclude-module pdb --exclude-module lib2to3 --exclude-module sqlite3 ^
  --exclude-module setuptools --exclude-module pkg_resources --exclude-module PIL.ImageQt ^
  --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib --exclude-module ftplib ^
  --exclude-module http --exclude-module urllib.request ^
  --exclude-module PIL._avif --exclude-module PIL._webp --exclude-module PIL._imagingft --exclude-module PIL._imagingcms ^
  "%~dp0tattoo_switcher_gui.py" || exit /b 1
copy /y README.md "%DIST%\TattooSwitcher\" >nul
copy /y LICENSE "%DIST%\TattooSwitcher\LICENSE.txt" >nul
echo.
echo Done: %DIST%\TattooSwitcher\TattooSwitcher.exe
