@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYEXE=.venv\Scripts\python.exe
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist "%PYEXE%" (
  echo Первый запуск: создаю окружение...
  %PY% -m venv .venv || (echo Не найден Python 3.10+. Установите его с https://www.python.org/downloads/ & pause & exit /b 1)
)
rem Зависимости ставятся заново, только если изменился requirements.txt
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Устанавливаю зависимости: yt-dlp, curl_cffi...
  "%PYEXE%" -m pip install --disable-pip-version-check -q -U pip
  "%PYEXE%" -m pip install --disable-pip-version-check -q -U -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
)

rem Как открывать приложение: "run.bat window" / "run.bat browser", иначе — спросить один раз
set UI=
if /i "%~1"=="window" set UI=window
if /i "%~1"=="browser" set UI=browser
if not defined UI if not exist ".venv\ui-asked" (
  echo.
  echo Как открывать YT-DLP Studio?
  echo   1 - в отдельном окне, как обычную программу. Будет доустановлен pywebview
  echo   2 - во вкладке браузера
  echo Потом это можно поменять в приложении: Настройки - Окно приложения.
  choice /c 12 /n /m "Ваш выбор [1/2]: "
  if errorlevel 2 (set UI=browser) else (set UI=window)
  type nul > ".venv\ui-asked"
)
if "%UI%"=="window" call :webview
if defined UI (
  "%PYEXE%" main.py --%UI%
) else (
  "%PYEXE%" main.py %*
)
if errorlevel 1 pause
exit /b

:webview
"%PYEXE%" -c "import webview" >nul 2>nul && exit /b 0
echo Устанавливаю pywebview для отдельного окна...
"%PYEXE%" -m pip install --disable-pip-version-check -q -U pywebview && exit /b 0
echo Не удалось установить pywebview - приложение откроется в браузере.
set UI=browser
exit /b 0
