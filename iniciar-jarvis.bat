@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title JARVIS
cd /d "%~dp0"

rem Procura o ambiente virtual na propria pasta ou na pasta de cima
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "..\.venv\Scripts\python.exe" (
    set "PY=..\.venv\Scripts\python.exe"
) else (
    echo Nao encontrei o ambiente .venv. Veja a secao Instalacao do README.
    pause
    exit /b 1
)

echo Iniciando o JARVIS. Para parar, aperte Ctrl+C ou feche esta janela.
rem Abre o navegador depois de alguns segundos, quando o servidor ja subiu
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8000"

rem Para desenvolver (recarrega ao salvar arquivos), acrescente --reload no fim da linha abaixo
"%PY%" -m uvicorn main:app
pause
