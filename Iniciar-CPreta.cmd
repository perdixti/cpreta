@echo off
setlocal
title CPreta - Iniciar
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" start_background.py
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 start_background.py
    ) else (
        python start_background.py
    )
)
if errorlevel 1 (
    echo.
    echo Confira data\logs\startup.log ou a mensagem acima.
    pause
)
endlocal
