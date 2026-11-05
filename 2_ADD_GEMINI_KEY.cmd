@echo off
title Olympus World - add Gemini key
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% tools\set_gemini_key.py
echo.
pause
