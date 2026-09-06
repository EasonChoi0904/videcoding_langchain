@echo off
rem Run the load-test CLI from anywhere (cwd switches to backend/).
call "%~dp0loadtest_env.bat"
cd /d "%~dp0..\.."
"%PYTHON%" -m scripts.loadtest.main %*
