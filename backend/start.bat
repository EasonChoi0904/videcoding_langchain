@echo off
REM ============================================================
REM  RAG KB QA System - backend on port 8000
REM  First run: creates .venv and installs deps (a few minutes)
REM  API docs: http://localhost:8000/docs
REM ============================================================
cd /d %~dp0

if not exist .venv (
    echo [INFO] First run: creating venv and installing dependencies...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [START] Backend: http://localhost:8000  docs: /docs
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
