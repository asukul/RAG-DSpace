@echo off
REM ---------------------------------------------------------------------------
REM quality/run_daily.bat
REM
REM Windows Task Scheduler wrapper for the local daily quality loop.
REM Cd's into the repo, runs quality/run_daily.py, captures output to a
REM dated log file under quality/_logs/.
REM
REM Schedule with:
REM   schtasks /create ^
REM     /tn "ISU RAG Daily Quality Loop" ^
REM     /tr "D:\Dropbox\RAG-DSpace\isu-research-search\quality\run_daily.bat" ^
REM     /sc daily ^
REM     /st 22:00 ^
REM     /ru %USERNAME%
REM
REM (10pm Chicago = 03:00 UTC daily.)
REM ---------------------------------------------------------------------------

set "REPO=D:\Dropbox\RAG-DSpace\isu-research-search"
cd /d "%REPO%"

if not exist "quality\_logs" mkdir "quality\_logs"

REM Build a YYYY-MM-DD date string regardless of Windows locale.
for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value ^| find "="') do set dt=%%I
set "DATESTAMP=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%"
set "LOGFILE=quality\_logs\daily_%DATESTAMP%.log"

echo.>> "%LOGFILE%"
echo === run_daily.bat %DATE% %TIME% ===>> "%LOGFILE%"

py -3 quality\run_daily.py 1>> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%

echo === exit %RC% ===>> "%LOGFILE%"
exit /b %RC%
