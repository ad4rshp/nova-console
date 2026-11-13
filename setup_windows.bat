@echo off
setlocal enabledelayedexpansion
title Nova Console Setup Wizard

echo ========================================================
echo         Nova Console - 1-Click Setup Wizard
echo ========================================================
echo.

:: 1. Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10 or higher is required.
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [*] Python detected. Checking environment...
set "SRC_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\NovaConsole"

echo [*] Target Directory: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo [*] Copying application files...
xcopy /E /I /Y /Q "%SRC_DIR%app" "%INSTALL_DIR%\app" >nul
xcopy /E /I /Y /Q "%SRC_DIR%static" "%INSTALL_DIR%\static" >nul
copy /Y "%SRC_DIR%dashboard.html" "%INSTALL_DIR%\" >nul
copy /Y "%SRC_DIR%launch.py" "%INSTALL_DIR%\" >nul
copy /Y "%SRC_DIR%requirements.txt" "%INSTALL_DIR%\" >nul
copy /Y "%SRC_DIR%.env.example" "%INSTALL_DIR%\.env.example" >nul
if exist "%SRC_DIR%Modelfile" copy /Y "%SRC_DIR%Modelfile" "%INSTALL_DIR%\" >nul

cd /d "%INSTALL_DIR%"

:: 2. Create isolated venv
if not exist "%INSTALL_DIR%\.venv" (
    echo [*] Creating isolated virtual environment...
    python -m venv .venv
)

echo [*] Installing requirements...
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

:: 3. Create Windows Launcher script in install directory
echo @echo off > "%INSTALL_DIR%\run.bat"
echo cd /d "%INSTALL_DIR%" >> "%INSTALL_DIR%\run.bat"
echo powershell -NoProfile -WindowStyle Hidden -Command "$eng = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue; if (-not $eng -and (Get-Command 'ollama' -ErrorAction SilentlyContinue)) { Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden }" >> "%INSTALL_DIR%\run.bat"
echo start "" "%INSTALL_DIR%\.venv\Scripts\python.exe" "%INSTALL_DIR%\launch.py" >> "%INSTALL_DIR%\run.bat"

:: 4. Create Desktop & Start Menu Shortcuts via PowerShell
echo [*] Creating Desktop and Start Menu shortcuts...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $desk = [Environment]::GetFolderPath('Desktop'); $sc = $ws.CreateShortcut(\"$desk\Nova Console.lnk\"); $sc.TargetPath = 'cmd.exe'; $sc.Arguments = '/c \"\"%INSTALL_DIR%\run.bat\"\"'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.WindowStyle = 7; $sc.Description = 'Nova Console - Local AI Workstation'; $sc.Save()"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $startmenu = [Environment]::GetFolderPath('StartMenu'); $sc = $ws.CreateShortcut(\"$startmenu\Programs\Nova Console.lnk\"); $sc.TargetPath = 'cmd.exe'; $sc.Arguments = '/c \"\"%INSTALL_DIR%\run.bat\"\"'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.WindowStyle = 7; $sc.Description = 'Nova Console - Local AI Workstation'; $sc.Save()"

echo.
echo ========================================================
echo   Installation Completed Successfully!
echo   Desktop shortcut 'Nova Console' has been created.
echo ========================================================
echo.
echo Launching Nova Console now...
call "%INSTALL_DIR%\run.bat"
timeout /t 3 >nul
exit /b 0

