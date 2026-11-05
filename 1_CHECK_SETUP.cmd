@echo off
title Olympus World - setup check
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% tools\check.py
echo.
pause
