@echo off
REM launch.bat - installer web locale di vps1777 (Windows nativo, senza WSL).
REM Doppio-click su questo file.
REM
REM Avvia un mini-server su http://127.0.0.1:8777 e apre il browser.
REM Deploy via SSH in Python puro (paramiko): niente bash, niente sshpass.
REM Requisiti: Python 3 (python.org). paramiko installato qui sotto se manca.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python non trovato. Installa Python 3 da python.org ^(spunta "Add to PATH"^) e riprova.
  pause
  exit /b 1
)

python -c "import paramiko" 2>nul
if errorlevel 1 (
  echo   Installo paramiko ^(dipendenza SSH^)...
  python -m pip install --quiet paramiko
  if errorlevel 1 (
    echo   pip non disponibile, provo ensurepip...
    python -m ensurepip
    python -m pip install --quiet paramiko
  )
  python -c "import paramiko" 2>nul
  if errorlevel 1 (
    echo Impossibile installare paramiko. Prova a mano:  python -m pip install paramiko
    pause
    exit /b 1
  )
)

echo.
echo   vps1777 installer
echo   Se il browser non si apre da solo, vai su:  http://127.0.0.1:8777
echo.

python installer.py
pause
