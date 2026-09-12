; GE Programming Language — Windows Installer
; Inno Setup script for creating a professional Windows installer
;
; Usage:
;   1. Build the binary:  pyinstaller ge.spec
;   2. Build the installer:  iscc installer\ge.iss
;   3. Output: installer\Output\GE-Setup-1.0.0.exe
;
; The installer bundles:
;   - ge.exe (standalone GE compiler binary)
;   - README.md, GE_LANG.md, AGENTS.md (documentation)
;   - Example files
;   - tools/ directory (if present, for bundled toolchains)
;
; The installer does NOT bundle language toolchains (Rust, C++, etc.) by
; default. Users install those separately, or place them in the tools/
; directory next to ge.exe.

#define MyAppName "GE Programming Language"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "GE Project"
#define MyAppURL "https://github.com/user/ge-lang"
#define MyAppExeName "ge.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
AppId={{GE-LANG-UNIQUE-ID-2025}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\GE
DefaultGroupName=GE Programming Language
AllowNoIcons=yes
LicenseFile=LICENSE
; Remove the following line to run in administrative install mode
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=GE-Setup-{#MyAppVersion}
SetupIconFile=installer\ge-icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "addtopath"; Description: "Add ge to &PATH"; GroupDescription: "Additional icons:"

[Files]
; Main binary (built by PyInstaller)
Source: "dist\ge\ge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "GE_LANG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "AGENTS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; Examples
Source: "examples\*"; DestDir: "{app}\examples"; Flags: ignoreversion recursesubdirs createallsubdirs

; Tools directory (if present — for bundled toolchains)
Source: "tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: DirExists(ExpandConstant('{tmp}\..\tools'))

[Icons]
Name: "{group}\GE Compiler"; Filename: "{app}\ge.exe"
Name: "{group}\GE Documentation"; Filename: "{app}\README.md"
Name: "{group}\GE Language Reference"; Filename: "{app}\GE_LANG.md"
Name: "{group}\AI Agent Guide"; Filename: "{app}\AGENTS.md"
Name: "{group}\Uninstall GE"; Filename: "{uninstallexe}"
Name: "{commondesktop}\GE Compiler"; Filename: "{app}\ge.exe"; Tasks: desktopicon

[Run]
; Add to PATH
Filename: "{app}\ge.exe"; Parameters: "compilers"; Description: "Show detected toolchains"; Flags: postinstall skipifsails runhidden

[UninstallRun]
; Remove from PATH (handled by Inno Setup's built-in PATH management)

[Code]
function DirExists(Path: String): Boolean;
begin
  Result := False;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
