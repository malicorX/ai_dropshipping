@echo off
REM Dropship Desk — Windows starter (venv + deps + launcher).
REM   start.bat             production UI (builds ui\dist if missing)
REM   start.bat rebuild     wipe ui\dist, reinstall npm deps, rebuild UI, then start
REM   start.bat rebuild headless   same rebuild, then API-only
REM   start.bat dev         API + PyWebView against Vite :5173 (run npm run dev in ui\)
REM   start.bat headless    API only — open http://127.0.0.1:8770 in a browser

setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo [start] Creating .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [start] Python venv failed. Is python on PATH?
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
echo [start] Installing Python deps ...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [start] pip install failed.
    exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo [start] Created .env from .env.example
)

REM ---- Optional: force frontend rebuild (same idea as ai_nvidiaTool) ----
if /i "%~1"=="rebuild" (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [start] npm not found. Install Node.js, then retry.
        exit /b 1
    )
    if exist "ui\dist" (
        echo [start] Deleting old UI build ...
        rmdir /s /q "ui\dist"
    )
    echo [start] rebuild: reinstalling frontend deps ...
    pushd ui
    if exist package-lock.json (
        call npm ci
    ) else (
        call npm install
    )
    if errorlevel 1 (
        popd
        echo [start] npm install failed.
        exit /b 1
    )
    echo [start] Building UI ...
    call npm run build
    if errorlevel 1 (
        popd
        echo [start] UI build failed.
        exit /b 1
    )
    popd
    shift
)

if /i "%~1"=="dev" (
    echo [start] Dev mode — start Vite in another terminal: cd ui ^&^& npm run dev
    python launcher.py --dev
    exit /b %errorlevel%
)

if /i "%~1"=="headless" (
    python launcher.py --headless
    exit /b %errorlevel%
)

if not exist "ui\dist\index.html" (
    if exist "ui\package.json" (
        where npm >nul 2>nul
        if errorlevel 1 (
            echo [start] npm not found. Install Node.js, then retry.
            exit /b 1
        )
        echo [start] Building UI ...
        pushd ui
        if not exist "node_modules" (
            if exist package-lock.json (
                call npm ci
            ) else (
                call npm install
            )
            if errorlevel 1 (
                popd
                echo [start] npm install failed.
                exit /b 1
            )
        )
        call npm run build
        if errorlevel 1 (
            popd
            echo [start] UI build failed.
            exit /b 1
        )
        popd
    )
)

python launcher.py
exit /b %errorlevel%
