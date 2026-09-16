@echo off
REM TreeLabeler launcher - standalone (bez nutnosti aktivace venv)
setlocal
set PROJECT=D:\treelabeler
set PYTHONPATH=%PROJECT%\src

echo Spoustim TreeLabeler...
echo Prohlizec se otevre na http://127.0.0.1:8000/
echo.

"%PROJECT%\.venv\Scripts\python.exe" -m treelabeler "%PROJECT%\data\site_one" --port 8000
if errorlevel 1 (
  echo.
  echo Port 8000 je obsazen — zkousim port 8001...
  "%PROJECT%\.venv\Scripts\python.exe" -m treelabeler "%PROJECT%\data\site_one" --port 8001
)
pause
