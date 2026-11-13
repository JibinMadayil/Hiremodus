@echo off
title HireModus server
cd /d "%~dp0backend"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import fastapi, sqlalchemy, openpyxl, bcrypt, jwt, PIL, msal, requests" >nul 2>nul
if errorlevel 1 (
  echo First run: installing HireModus server packages...
  %PY% -m pip install --user fastapi "uvicorn[standard]" sqlalchemy pydantic pyjwt bcrypt openpyxl python-multipart pillow msal requests
)
rem Address other people on the office network use to reach this PC
set HIREMODUS_PORTAL_URL=http://%COMPUTERNAME%:8000/portal
echo.
echo HireModus is running.
echo   On this PC:              http://localhost:8000
echo   Others on the network:   http://%COMPUTERNAME%:8000
echo   Candidate test portal:   http://%COMPUTERNAME%:8000/portal
echo.
echo If Windows asks whether to allow Python on networks, allow it on Private/Domain networks.
echo Close this window to stop the server.
echo.
start "" http://localhost:8000
%PY% -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
