#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "BŁĄD: Zainstaluj Python 3.10 lub nowszy."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Tworzenie lokalnego środowiska gry..."
  "$PYTHON" -m venv .venv
fi

echo "[2/3] Sprawdzanie Pygame..."
if ! .venv/bin/python -c "import pygame" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "[3/3] Uruchamianie gry..."
.venv/bin/python main.py
