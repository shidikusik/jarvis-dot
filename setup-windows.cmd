@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\download_model.py
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\download_voices.py
if errorlevel 1 goto fail
echo Ready. Run start-windows.cmd
pause
exit /b 0
:fail
echo Setup failed. See the error above. Python 3.11 or newer is required.
pause
exit /b 1
