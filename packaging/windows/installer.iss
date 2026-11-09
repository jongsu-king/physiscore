; Inno Setup script. Build: ISCC.exe /DAppVersion=2.1.0 packaging\windows\installer.iss
; Installs for the current user by default (no administrator rights), so the in-app
; updater can upgrade silently; "Install for all users" is offered on the first page.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Physiscore"
#define AppExe "Physiscore.exe"
#define Root SourcePath + "..\.."

[Setup]
AppId={{A3D1F0C4-58B2-4E7A-9C61-2F0E7B9D4C35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=H-MOL, Incheon National University
AppPublisherURL=https://github.com/jongsu-king/physiscore
AppSupportURL=https://github.com/jongsu-king/physiscore/issues
AppUpdatesURL=https://github.com/jongsu-king/physiscore/releases
DefaultDirName={autopf}\Physiscore
DefaultGroupName=Physiscore
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=Physiscore-{#AppVersion}-windows-x64-setup
SetupIconFile={#Root}\packaging\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile={#Root}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\dist\Physiscore\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
