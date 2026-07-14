@echo off
setlocal
cd /d "%~dp0"
title Hunter Duel - Build Windows

py -3 -m pip install --upgrade pip
if errorlevel 1 goto :failed
py -3 -m pip install -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :failed
py -3 tools\make_icon.py
if errorlevel 1 goto :failed
py -3 -m PyInstaller --noconfirm --clean HunterDuel.spec
if errorlevel 1 goto :failed

copy /y mods\README_MODY.txt dist\README_MODY.txt >nul
copy /y mods\Przykladowa_Technika.huntermod.json dist\Przykladowa_Technika.huntermod.json >nul
echo.
echo GOTOWE: dist\HunterDuel.exe
pause
exit /b 0

:failed
echo.
echo BUILD NIE POWIODL SIE.
pause
exit /b 1

