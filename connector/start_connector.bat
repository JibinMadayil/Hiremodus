@echo off
title HireModus Outlook Connector
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import win32com.client, requests" >nul 2>nul
if errorlevel 1 (
  echo First run: installing the two packages the connector needs...
  %PY% -m pip install --user -r requirements.txt
)
%PY% hiremodus_connector.py
pause
