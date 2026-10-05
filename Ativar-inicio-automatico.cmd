@echo off
chcp 65001 >nul
setlocal
title CPreta - Inicio automatico
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 autostart.py enable
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -X utf8 autostart.py enable
    ) else (
        python -X utf8 autostart.py enable
    )
)
if errorlevel 1 (
    echo.
    echo Nao foi possivel ativar. Confira a mensagem acima.
) else (
    echo.
    echo Concluido. O CPreta iniciara ao entrar no Windows.
    echo Para desativar, desmarque Iniciar com o sistema no painel e salve.
)
echo.
pause
endlocal
