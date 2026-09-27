#!/usr/bin/env sh
# YT-DLP Studio launcher for macOS / Linux
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python3}
if [ ! -x ".venv/bin/python" ]; then
  echo "Первый запуск: создаю окружение..."
  "$PY" -m venv .venv || { echo "Нужен Python 3.10+ (и пакет python3-venv)"; exit 1; }
fi
# dependencies are (re)installed only when requirements.txt changed
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Устанавливаю зависимости: yt-dlp, curl_cffi..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -U pip
  .venv/bin/python -m pip install --disable-pip-version-check -q -U -r requirements.txt \
    && cp requirements.txt .venv/requirements.installed
fi
exec .venv/bin/python main.py "$@"
