@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 || (echo Python 3 is required from python.org & pause & exit /b 1)
py -3 -m pip install --upgrade pip pyinstaller pillow reportlab
if errorlevel 1 goto failed
py -3 -m compileall -q AS_Coconut_Traders_Billing.py RUN_AUTOMATED_TESTS.py
if errorlevel 1 goto failed
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name AS_Coconut_Traders_Billing --icon AS_Coconut_Traders.ico --add-data "AS_Coconut_Traders_Logo.png;." --add-data "AS_Coconut_Traders_Header_Logo.png;." --add-data "Coconut_Banner.png;." --collect-all reportlab AS_Coconut_Traders_Billing.py
if errorlevel 1 goto failed
echo SUCCESS: dist\AS_Coconut_Traders_Billing\AS_Coconut_Traders_Billing.exe
pause
exit /b 0
:failed
echo BUILD FAILED. Review the error above.
pause
exit /b 1
