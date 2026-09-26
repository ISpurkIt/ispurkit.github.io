@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение и ставлю yt-dlp...
  %PY% -m venv .venv || (echo Не найден Python 3.10+. Установите его с https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
)
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
