#!/usr/bin/env sh
# YT-DLP Studio launcher for macOS / Linux
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python3}
if [ ! -x ".venv/bin/python" ]; then
  echo "Первый запуск: создаю окружение и ставлю yt-dlp..."
  "$PY" -m venv .venv || { echo "Нужен Python 3.10+ (и пакет python3-venv)"; exit 1; }
  .venv/bin/python -m pip install --disable-pip-version-check -q -U pip
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
fi
exec .venv/bin/python main.py "$@"
