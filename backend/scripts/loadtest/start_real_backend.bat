@echo off
rem Start the load-test backend in REAL API mode against a snapshot copy of the
rem dev database. Create the snapshot first while the dev backend is stopped:
rem   robocopy ..\..\data\app.db* ... (see README)
rem Prereq: a snapshot dir data\_loadtest_snapshot containing app.db/qdrant/uploads.
call "%~dp0loadtest_env.bat"
if not exist "%DATA_DIR%\..\_loadtest_snapshot\app.db" (
  echo ERROR: snapshot not found. Create data\_loadtest_snapshot first (see README.md).
  exit /b 1
)
set "DATA_DIR=%~dp0..\..\data\_loadtest_snapshot"
set "LOADTEST_MOCK_PROVIDER="
set "STREAM_CONCURRENCY=4"
set "RATE_REGISTER_PER_HOUR="
set "RATE_LOGIN_PER_MINUTE="
set "RATE_ASK_PER_MINUTE="
mkdir "%DATA_DIR%" 2>nul
start "loadtest-real" /min cmd /c ""%PYTHON%" "%~dp0loadtest_server.py" > "%DATA_DIR%\server.log" 2>&1"
echo Real-mode backend starting on :8000 (snapshot DB, real DashScope API) ...
echo IMPORTANT: stop the dev/mock backend first; watch DashScope quota.
