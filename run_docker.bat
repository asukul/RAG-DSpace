@echo off
echo ===================================================
echo 🌪️ Starting ISU Research Search (Docker)
echo ===================================================

cd /d "%~dp0"

echo.
echo [1/3] Checking Docker...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker is not installed or not running!
    echo    Please install Docker Desktop and try again.
    pause
    exit /b
)

echo.
echo [2/3] Building and Starting Containers...
echo    This may take a few minutes for the first run...
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo ❌ Failed to start Docker containers.
    pause
    exit /b
)

echo.
echo [3/3] Success! 🚀
echo.
echo    Frontend: http://localhost:3000
echo    Backend:  http://localhost:8000/docs
echo.
echo    Logs are streaming below. Press Ctrl+C to stop.
echo ===================================================
docker-compose logs -f
