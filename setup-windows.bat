@echo off
echo ============================================================
echo ISU Research Search - Setup Script for Windows
echo ============================================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker Desktop is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo Docker Desktop is running. Good!
echo.

REM Check for .env file
if not exist .env (
    echo Creating .env file from template...
    copy .env.template .env
    echo.
    echo IMPORTANT: Please edit .env and add your GEMINI_API_KEY
    echo You can get one at: https://aistudio.google.com/app/apikey
    echo.
    notepad .env
    pause
)

echo.
echo Starting services with Docker Compose...
echo This may take a few minutes on first run...
echo.

docker-compose up -d --build

echo.
echo ============================================================
echo Setup Complete!
echo ============================================================
echo.
echo Services are starting. Wait about 30 seconds, then visit:
echo.
echo   Main App:  http://localhost:3000
echo   API Docs:  http://localhost:8000/docs
echo.
echo To view logs:
echo   docker-compose logs -f
echo.
echo To stop:
echo   docker-compose down
echo.
echo ============================================================
pause
