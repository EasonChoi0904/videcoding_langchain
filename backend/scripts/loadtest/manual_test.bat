@echo off
rem Double-click entry for the interactive load-test wizard (ASCII only on purpose).
call "%~dp0loadtest_env.bat"
cd /d "%~dp0..\.."
"%PYTHON%" -m scripts.loadtest.main --manual
echo.
pause
