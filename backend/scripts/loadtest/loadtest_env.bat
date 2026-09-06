@echo off
rem Shared load-test environment (pure ASCII on purpose: cmd parses .bat as GBK).
rem DATA_DIR is derived from this file's own location, so the Chinese repo
rem path never appears in the batch source.
set "DATA_DIR=%~dp0..\..\data\_loadtest"
set "PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
set "LOADTEST_MOCK_PROVIDER=true"
set "STREAM_CONCURRENCY=100"
set "RATE_REGISTER_PER_HOUR=100000"
set "RATE_LOGIN_PER_MINUTE=100000"
rem keep product ask rate limit (20/min per user) to validate throttling:
set "RATE_ASK_PER_MINUTE=20"
rem mock LLM pacing (light default; heavy scenario: set 45 and 520):
set "LOADTEST_MOCK_LLM_FIRST_DELAY_MS=250"
set "LOADTEST_MOCK_LLM_CHUNK_DELAY_MS=15"
set "LOADTEST_MOCK_LLM_CHUNK_SIZE=8"
set "LOADTEST_MOCK_LLM_TOTAL_CHARS=320"
