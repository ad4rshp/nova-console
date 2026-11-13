@echo off
setlocal
cd /d "%~dp0.."

echo ========================================================
echo   Starting Nova Console...
echo ========================================================

:: Check if local backend (e.g. Ollama) is in PATH and launch if not listening
powershell -NoProfile -Command "$listen = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue; if (-not $listen -and (Get-Command 'ollama' -ErrorAction SilentlyContinue)) { Write-Host 'Detected Ollama in PATH. Launching service...'; Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden; Start-Sleep -Seconds 2 }"

:: Check for virtual environment
if exist .venv\Scripts\python.exe (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

:: Run Nova Console via universal launcher
"%PYTHON_EXE%" launch.py
pause

