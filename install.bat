@echo off
setlocal
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0installer.ps1" %*
exit /b %errorlevel%
