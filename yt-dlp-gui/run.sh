#!/usr/bin/env sh
# YT-DLP Studio launcher for macOS / Linux.  ./run.sh window | ./run.sh browser
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python3}
VPY=.venv/bin/python
if [ ! -x "$VPY" ]; then
  echo "Первый запуск: создаю окружение..."
  "$PY" -m venv .venv || { echo "Нужен Python 3.10+ (и пакет python3-venv)"; exit 1; }
fi
# dependencies are (re)installed only when requirements.txt changed
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Устанавливаю зависимости: yt-dlp, curl_cffi..."
  "$VPY" -m pip install --disable-pip-version-check -q -U pip
  "$VPY" -m pip install --disable-pip-version-check -q -U -r requirements.txt \
    && cp requirements.txt .venv/requirements.installed
fi

UI=""
case "$1" in
  window|browser) UI=$1; shift ;;
esac
if [ -z "$UI" ] && [ ! -f .venv/ui-asked ] && [ -t 0 ]; then
  echo
  echo "Как открывать YT-DLP Studio?"
  echo "  1 - в отдельном окне, как обычную программу (будет доустановлен pywebview)"
  echo "  2 - во вкладке браузера"
  echo "Потом это можно поменять в приложении: Настройки → Окно приложения."
  printf "Ваш выбор [1/2]: "
  read -r answer
  if [ "$answer" = "1" ]; then UI=window; else UI=browser; fi
  touch .venv/ui-asked
fi
if [ "$UI" = "window" ] && ! "$VPY" -c "import webview" 2>/dev/null; then
  echo "Устанавливаю pywebview для отдельного окна..."
  case "$(uname -s)" in
    Linux) PKG="pywebview[qt]" ;;  # Linux has no built-in web view: Qt WebEngine is pulled in
    *) PKG="pywebview" ;;
  esac
  "$VPY" -m pip install --disable-pip-version-check -q -U "$PKG" \
    || { echo "Не удалось установить pywebview — приложение откроется в браузере."; UI=browser; }
fi
if [ -n "$UI" ]; then
  exec "$VPY" main.py "--$UI" "$@"
fi
exec "$VPY" main.py "$@"
