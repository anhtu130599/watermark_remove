@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0.."

echo ==================================================
echo   AI Watermark Studio - 1-Click Windows Setup
echo ==================================================

set "UV_LINK_MODE=copy"
if exist "C:\Program Files\nodejs" set "PATH=C:\Program Files\nodejs;%PATH%"
if exist "%USERPROFILE%\.local\bin" set "PATH=%USERPROFILE%\.local\bin;%PATH%"

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [Setup] Da tao .env tu .env.example
    )
)

where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if not exist ".venv\Scripts\python.exe" (
        echo [Setup] Tao moi truong Python bang uv...
        uv venv .venv --python 3.11
        if errorlevel 1 exit /b 1
    )
    echo [Setup] Cai dat thu vien Backend Python...
    uv pip install --python ".venv\Scripts\python.exe" --link-mode=copy -r backend\requirements.txt
    if errorlevel 1 exit /b 1
) else (
    if not exist ".venv\Scripts\python.exe" (
        echo [Setup] Tao moi truong Python bang venv...
        python -m venv .venv
        if errorlevel 1 exit /b 1
    )
    echo [Setup] Cai dat thu vien Backend Python...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
    if errorlevel 1 exit /b 1
)

where npm >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [Setup] Build giao dien Frontend React + Vite...
    pushd frontend
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        popd
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
) else (
    if exist "frontend\dist\index.html" (
        echo [Setup] Khong tim thay npm, su dung frontend\dist da build san.
    ) else (
        echo [Canh bao] Chua co Node.js/npm va chua co frontend\dist\index.html.
    )
)

echo [Setup] Kiem tra & tai trong so AI (Big-LaMa + Florence-2)...
".venv\Scripts\python.exe" scripts\download_models.py
if errorlevel 1 exit /b 1

echo.
echo [Hoan tat] Hay chay scripts\start_app.bat de mo AI Watermark Studio!
exit /b 0
