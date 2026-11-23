; Inno Setup Script for Nova Console
#define MyAppName "Nova Console"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "Nova Console Team"
#define MyAppURL "https://github.com/ad4rshp/nova-console"
#define MyAppExeName "NovaConsole.exe"

[Setup]
AppId={{9F82A45C-3D24-4B2E-8E5A-7E2319047DE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=NovaConsole-Setup
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\app\templates\*"; DestDir: "{app}\app\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\app\templates\dashboard.html"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillNovaProcess"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\NovaConsole"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\config"
Type: files; Name: "{app}\*.db*"
Type: files; Name: "{userdesktop}\Nova Console.lnk"
Type: files; Name: "{userprograms}\Nova Console.lnk"

