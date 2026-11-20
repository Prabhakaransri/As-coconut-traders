#define AppName "AS Coconut Traders Billing & Inventory"
#define AppVersion "79.0"
#define AppExe "AS_Coconut_Traders_Billing.exe"
[Setup]
AppId={{A4F2B317-77CD-4F9D-8C7E-ACCC97A0B001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AS Coconut Traders
DefaultDirName={localappdata}\Programs\AS Coconut Traders Billing
DefaultGroupName=AS Coconut Traders
OutputDir=Installer_Output
OutputBaseFilename=AS_Coconut_Traders_Setup_V79
SetupIconFile=AS_Coconut_Traders.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes
[Files]
Source: "dist\AS_Coconut_Traders_Billing\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\AS Coconut Traders Billing"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\AS Coconut Traders Billing"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch AS Coconut Traders Billing"; Flags: nowait postinstall skipifsilent
