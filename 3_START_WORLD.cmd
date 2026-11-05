@echo off
title Olympus World - RUNNING (close this window to stop)
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% -m olympus_world.server
echo.
pause
