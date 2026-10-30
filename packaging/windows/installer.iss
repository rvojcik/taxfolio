; Inno Setup script – called by packaging/build.py with /D defines:
;   AppVersion, AppName, DisplayName, SourceDir (PyInstaller folder), OutputDir, IconFile
; Per-user install (no administrator rights needed); data stay in the user's profile.

[Setup]
AppId={{6F7E2C1A-3B9D-4E52-9A41-2C7D8B5E0F13}
AppName={#DisplayName}
AppVersion={#AppVersion}
AppVerName={#DisplayName} {#AppVersion}
AppPublisher=rvojcik
AppPublisherURL=https://github.com/rvojcik/taxfolio
AppSupportURL=https://github.com/rvojcik/taxfolio/issues
AppUpdatesURL=https://github.com/rvojcik/taxfolio/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#DisplayName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#DisplayName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#DisplayName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#DisplayName}}"; Flags: nowait postinstall skipifsilent
