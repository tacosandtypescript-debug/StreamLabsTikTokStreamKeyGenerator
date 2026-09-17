; Inno Setup script for the Windows installer.
;
; Build it with the compiler that ships on the GitHub runners:
;
;   iscc.exe /DMyAppVersion=2.2.0 installer.iss
;
; The version is injected from the release workflow, so the file name of the
; installer, the entry in "Apps and features" and the version reported by the
; application can never drift apart.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

; Where the application is installed. It can be overridden on the compiler command
; line so that a build under test can be installed somewhere harmless instead of
; next to a real installation.
#ifndef MyAppDirName
  #define MyAppDirName "{localappdata}\Programs\StreamLabsTikTokStreamKeyGenerator"
#endif

#define MyAppName "StreamLabsTikTokStreamKeyGenerator"
#define MyAppPublisher "tacosandtypescript-debug"
#define MyAppURL "https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
#define MyAppExeName "StreamLabsTikTokStreamKeyGenerator.exe"

[Setup]
; AppId is the immutable identity of the product: with the same value Inno
; updates an existing installation instead of stacking a second one. Never
; change it, not even if the application is renamed.
AppId={{8F1E5C0A-2B47-4E9D-9A31-6C5B7D2E4F18}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}

; Per-user installation without ever asking for elevation. The 64-bit Windows
; build is x64 only, and Windows 10 is the oldest supported system.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; The same folder the PowerShell installer uses, so both routes converge.
DefaultDirName={#MyAppDirName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
AllowNoIcons=yes
LicenseFile=LICENSE.txt

SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern

OutputDir=Output
OutputBaseFilename=Setup-{#MyAppName}-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes

; Inno asks the Windows Restart Manager to close whatever is using the files it
; has to replace, which is how the running application is closed during an
; update. RestartApplications is off because the update helper starts the
; application again on purpose, and a silent install must stay silent.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The build is a whole folder: the executable plus the Qt and Python libraries.
Source: "StreamLabsTikTokStreamKeyGenerator.dist\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; skipifsilent keeps a winget or helper-driven installation from opening the
; application on its own; the update helper relaunches it instead.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
