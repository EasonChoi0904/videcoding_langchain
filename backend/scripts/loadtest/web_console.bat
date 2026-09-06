@echo off
rem Double-click entry: local web console for load-testing (ASCII only).
rem Opens http://127.0.0.1:9100 in the default browser.
call "%~dp0loadtest_env.bat"
cd /d "%~dp0..\.."
start "" "http://127.0.0.1:9100"
"%PYTHON%" scripts\loadtest\web_console.py --no-browser
pause
