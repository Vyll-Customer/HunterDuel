@echo off
setlocal
title Hunter Duel - Nen Protocol
cd /d "%~dp0"

echo ==========================================
echo   HUNTER DUEL - AUTOMATYCZNY START
echo ==========================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo BLAD: Python nie jest zainstalowany albo nie znajduje sie w PATH.
  echo Zainstaluj Python 3.10 lub nowszy i zaznacz opcje "Add Python to PATH".
  goto :failed
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 10) else 1)"
if errorlevel 1 (
  echo BLAD: Gra wymaga Python 3.10 lub nowszego.
  goto :failed
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Tworzenie lokalnego srodowiska gry...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo BLAD: Nie udalo sie utworzyc srodowiska Python.
    goto :failed
  )
)

echo [2/3] Sprawdzanie Pygame...
".venv\Scripts\python.exe" -c "import pygame" >nul 2>&1
if errorlevel 1 (
  echo Pierwsze uruchomienie - instalowanie Pygame. To moze chwile potrwac.
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo BLAD: Nie udalo sie pobrac Pygame. Sprawdz internet i antywirusa.
    goto :failed
  )
)

echo [3/3] Uruchamianie gry...
echo.
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Gra zakonczyla sie bledem. Zrob zdjecie tego okna i wyslij mi je.
  goto :failed
)
exit /b 0

:failed
echo.
pause
exit /b 1
