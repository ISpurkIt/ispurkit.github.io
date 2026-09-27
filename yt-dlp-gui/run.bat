@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение...
  %PY% -m venv .venv || (echo Не найден Python 3.10+. Установите его с https://www.python.org/downloads/ & pause & exit /b 1)
)
rem Зависимости ставятся заново, только если изменился requirements.txt
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Устанавливаю зависимости: yt-dlp, curl_cffi...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
)
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
