@echo off
rem Stop any load-test backend started via loadtest_server.py (marker in command line).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'loadtest_server\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('stopped ' + $_.ProcessId) }"
echo Done.
