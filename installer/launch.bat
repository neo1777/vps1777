@echo off
REM launch.bat - avvia l'installer web locale di vps1777 (Windows).
REM Doppio-click su questo file.
REM
REM Avvia un mini-server su http://127.0.0.1:8777 e apre il browser.
REM Requisiti: Python 3 (python.org), ssh nel PATH (OpenSSH client di Windows).

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python non trovato. Installa Python 3 da python.org e riprova.
  pause
  exit /b 1
)

echo.
echo   vps1777 installer
echo   Se il browser non si apre da solo, vai su:  http://127.0.0.1:8777
echo.

python installer.py
pause
