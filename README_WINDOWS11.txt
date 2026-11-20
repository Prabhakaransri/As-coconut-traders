AS Coconut Traders Windows 11 production BUILD KIT (V79)
======================================================
This is SOURCE + BUILD SCRIPTS, NOT a compiled Windows EXE.
On Windows 11:
1. Install Python 3 with Python Launcher (py).
2. Extract ZIP to a folder and run BUILD_WINDOWS11.bat.
3. EXE will be in dist\AS_Coconut_Traders_Billing\.
4. Optional: Install Inno Setup 6 and compile AS_Coconut_Traders_Setup.iss.
5. Before real transactions: test invoice PDF, WhatsApp sharing, printer, backup and restore on your actual PC.
Data is stored in %LOCALAPPDATA%\AS_Coconut_Traders_V72_Fresh_Start\billing.db
Back up that entire directory before updates. Never delete or overwrite billing.db.
Tests: 14/14 local automated tests passed in Linux Xvfb, not a Windows 11 certification.
No real customer data or operational database is included.
