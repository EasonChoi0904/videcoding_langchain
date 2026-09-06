@echo off
REM ============================================================
REM  RAG E-commerce KB QA System - one-click launcher
REM  Backend :8000 + Frontend :5173 (two console windows)
REM  Open http://localhost:5173 after ~10 seconds
REM  Stop: close the two service windows
REM ============================================================
cd /d %~dp0

start "RAG-Backend-8000" cmd /k ""%~dp0backend\start.bat""
start "RAG-Frontend-5173" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Two service windows have been opened.
echo The launcher window will close by itself - this is NORMAL.
echo Wait about 10 seconds, then open http://localhost:5173 in browser.
timeout /t 5 >nul
