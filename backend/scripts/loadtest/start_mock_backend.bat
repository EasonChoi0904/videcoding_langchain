@echo off
rem Start the load-test backend in mock mode (temp DATA_DIR, zero real API calls).
call "%~dp0loadtest_env.bat"
if exist "%DATA_DIR%" rmdir /s /q "%DATA_DIR%"
mkdir "%DATA_DIR%"
start "loadtest-mock" /min cmd /c ""%PYTHON%" "%~dp0loadtest_server.py" > "%DATA_DIR%\server.log" 2>&1"
echo Mock backend starting on :8000 ... log: %DATA_DIR%\server.log
