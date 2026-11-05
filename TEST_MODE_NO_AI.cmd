@echo off
title Olympus World - TEST MODE (no AI)
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
echo Test mode: the gods act randomly. Uses a separate test world, not your real one.
%PY% -m olympus_world.server --fake
echo.
pause
