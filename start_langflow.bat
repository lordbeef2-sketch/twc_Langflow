@echo off
setlocal
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0launcher.ps1" %*
exit /b %errorlevel%
