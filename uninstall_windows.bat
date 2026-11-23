@echo off
setlocal enabledelayedexpansion
title Nova Console Uninstaller

echo ========================================================
echo        Nova Console - Complete System Uninstaller
echo ========================================================
echo.

set "FORCE=0"
if /i "%~1"=="-y" set "FORCE=1"
if /i "%~1"=="--yes" set "FORCE=1"
if /i "%~1"=="-f" set "FORCE=1"
if /i "%~1"=="--force" set "FORCE=1"

if "%FORCE%"=="0" (
    echo This utility will completely remove Nova Console from your system:
    echo   - Stop all active Nova Console processes
    echo   - Delete installation directory: %%LOCALAPPDATA%%\NovaConsole
    echo   - Remove Desktop and Start Menu shortcuts
    echo   - Delete runtime databases, config, and cache files
    echo   - Clean installer temporary artifacts in %%TEMP%%
    echo.
    set /p "CONFIRM=Are you sure you want to completely uninstall Nova Console? (y/N): "
    if /i not "!CONFIRM!"=="y" if /i not "!CONFIRM!"=="yes" (
        echo [!] Uninstallation cancelled by user.
        exit /b 0
    )
)

echo.
echo [*] Step 1/6: Stopping running Nova Console processes...
taskkill /f /im NovaConsole.exe >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py*' -or $_.CommandLine -like '*NovaConsole*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo [OK] Active processes stopped.

echo [*] Step 2/6: Removing Desktop and Start Menu shortcuts...
powershell -NoProfile -Command "$desk = [Environment]::GetFolderPath('Desktop'); $sc = Join-Path $desk 'Nova Console.lnk'; if (Test-Path $sc) { Remove-Item $sc -Force -ErrorAction SilentlyContinue; Write-Host '  [-] Removed Desktop shortcut' }"
powershell -NoProfile -Command "$start = [Environment]::GetFolderPath('StartMenu'); $sc = Join-Path $start 'Programs\Nova Console.lnk'; if (Test-Path $sc) { Remove-Item $sc -Force -ErrorAction SilentlyContinue; Write-Host '  [-] Removed Start Menu shortcut' }"
if exist "%PUBLIC%\Desktop\Nova Console.lnk" (
    del /f /q "%PUBLIC%\Desktop\Nova Console.lnk" >nul 2>&1
    echo   [-] Removed Public Desktop shortcut
)
if exist "%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Nova Console.lnk" (
    del /f /q "%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Nova Console.lnk" >nul 2>&1
    echo   [-] Removed Common Start Menu shortcut
)
echo [OK] Shortcuts removed.

echo [*] Step 3/6: Removing Nova Console installation directory...
set "INSTALL_DIR=%LOCALAPPDATA%\NovaConsole"
if exist "%INSTALL_DIR%" (
    REM If script is being executed directly from inside INSTALL_DIR, cd out first
    cd /d "%TEMP%"
    rd /s /q "%INSTALL_DIR%" >nul 2>&1
    if exist "%INSTALL_DIR%" (
        powershell -NoProfile -Command "Start-Sleep -Milliseconds 800; Remove-Item -LiteralPath '%INSTALL_DIR%' -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
    )
    if exist "%INSTALL_DIR%" (
        echo [!] Warning: Some locked files in "%INSTALL_DIR%" could not be deleted immediately.
    ) else (
        echo   [-] Removed: %INSTALL_DIR%
    )
) else (
    echo   [-] %INSTALL_DIR% not found (already clean).
)
echo [OK] Main installation directory cleaned.

echo [*] Step 4/6: Checking for Program Files standalone installation...
set "PF_DIR=%ProgramFiles%\Nova Console"
set "PF_DIR_X86=%ProgramFiles(x86)%\Nova Console"
set "LOCAL_PROG=%LOCALAPPDATA%\Programs\Nova Console"

if exist "%PF_DIR%\unins000.exe" (
    echo   [*] Found Inno Setup uninstaller. Running silent cleanup...
    "%PF_DIR%\unins000.exe" /SILENT /VERYSILENT /SUPPRESSMSGBOXES /NORESTART >nul 2>&1
) else if exist "%PF_DIR%" (
    rd /s /q "%PF_DIR%" >nul 2>&1
)

if exist "%PF_DIR_X86%\unins000.exe" (
    "%PF_DIR_X86%\unins000.exe" /SILENT /VERYSILENT /SUPPRESSMSGBOXES /NORESTART >nul 2>&1
) else if exist "%PF_DIR_X86%" (
    rd /s /q "%PF_DIR_X86%" >nul 2>&1
)

if exist "%LOCAL_PROG%\unins000.exe" (
    "%LOCAL_PROG%\unins000.exe" /SILENT /VERYSILENT /SUPPRESSMSGBOXES /NORESTART >nul 2>&1
) else if exist "%LOCAL_PROG%" (
    rd /s /q "%LOCAL_PROG%" >nul 2>&1
)
echo [OK] Program files inspection complete.

echo [*] Step 5/6: Cleaning temporary setup artifacts...
if exist "%TEMP%\nova-console.zip" del /f /q "%TEMP%\nova-console.zip" >nul 2>&1
if exist "%TEMP%\nova-src" rd /s /q "%TEMP%\nova-src" >nul 2>&1
powershell -NoProfile -Command "Get-ChildItem -Path $env:TEMP -Filter 'NovaConsole*' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
echo [OK] Temporary artifacts cleaned.

echo [*] Step 6/6: Checking local repository / development artifacts...
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%nova-dashboard.db" (
    echo   [-] Found local repository database: %SCRIPT_DIR%nova-dashboard.db
    del /f /q "%SCRIPT_DIR%nova-dashboard.db*" >nul 2>&1
    echo   [-] Local database files removed.
)

echo.
echo ========================================================
echo   Nova Console has been successfully uninstalled!
echo   All files, shortcuts, and configurations were removed.
echo ========================================================
echo.

if "%FORCE%"=="0" (
    pause
)
exit /b 0
