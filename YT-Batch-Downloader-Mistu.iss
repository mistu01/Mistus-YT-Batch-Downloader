; YT-Batch-Downloader-Mistu — Inno Setup script
; Compile:  ISCC.exe /DAppVersion=2.9.7 YT-Batch-Downloader-Mistu.iss
; Requires the staging folder build/installer/YT-Batch-Downloader-Mistu
; (created by build_installer.py).

#define AppName "Mistus Batch YT Downloader"

#ifndef AppVersion
  #define AppVersion "2.9.7"
#endif

[Setup]
AppId={{84752C1E-6D11-4C24-9A87-7F58124B9F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Mistu
; NOTE: The value of AppId is a random GUID; changing it de-installs previous copies.
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\assets\icon.ico
SetupIconFile=assets\icon.ico
WizardImageFile=assets\wizard_192.bmp,assets\wizard_164.bmp
WizardSmallImageFile=assets\wizsmall_55.bmp,assets\wizsmall_32.bmp
OutputDir=dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
Uninstallable=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "addpath"; Description: "Make the command-line tool available in PATH (yt_batch_downloader_mistu)"; \
    GroupDescription: "Options:"; Flags: checkedonce

[Files]
Source: "build\installer\YT-Batch-Downloader-Mistu\*"; DestDir: "{app}"; \
    Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\app\python\pythonw.exe"; \
    IconFilename: "{app}\assets\icon.ico"; \
    Parameters: """{app}\mistu_gui.py"""; WorkingDir: "{app}"; \
    Comment: "YouTube batch downloader & channel scanner"
Name: "{group}\{#AppName} (CLI)"; Filename: "{app}\YT-Batch-Downloader-Mistu-CLI.cmd"; \
    IconFilename: "{app}\assets\icon.ico"; \
    WorkingDir: "{app}"; Comment: "Command-line version"
Name: "{group}\{#AppName} (Uninstall)"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\app\python\pythonw.exe"; \
    IconFilename: "{app}\assets\icon.ico"; \
    Parameters: """{app}\mistu_gui.py"""; WorkingDir: "{app}"; \
    Tasks: desktopicon

[Registry]
; append install dir to the machine PATH (kept idempotent by NeedsAddPath)
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Tasks: addpath; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\app\python\pythonw.exe"; Parameters: """{app}\mistu_gui.py"""; \
    Description: "Launch {#AppName}"; \
    Flags: postinstall nowait

[Code]
function NeedsAddPath(AppDir: string): boolean;
var
  OrigPaths: string;
begin
  // returns True when AppDir is NOT yet in the machine PATH
  OrigPaths := '';
  RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPaths);
  Result := (Pos(';' + Uppercase(AppDir) + ';', ';' + Uppercase(OrigPaths) + ';') = 0);
end;

procedure RemovePathEntry(AppDir: string);
var
  EnvKey, OrigPaths, Orig, NewPaths, Entry: string;
  P: integer;
begin
  EnvKey := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvKey, 'Path', OrigPaths) then
    Exit;
  Orig := OrigPaths;
  AppDir := Lowercase(RemoveBackslashUnlessRoot(ExpandConstant(AppDir)));
  NewPaths := '';
  while Length(OrigPaths) > 0 do
  begin
    P := Pos(';', OrigPaths);
    if P = 0 then
    begin
      Entry := OrigPaths;
      OrigPaths := '';
    end
    else
    begin
      Entry := Copy(OrigPaths, 1, P - 1);
      OrigPaths := Copy(OrigPaths, P + 1, Length(OrigPaths) - P);
    end;
    Entry := Lowercase(Trim(Entry));
    if (Entry <> '') and (Entry <> AppDir) then
    begin
      if NewPaths = '' then
        NewPaths := Entry
      else
        NewPaths := NewPaths + ';' + Entry;
    end;
  end;
  if NewPaths <> Orig then
    RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvKey, 'Path', NewPaths);
  // broadcast WM_SETTINGCHANGE (HWND_BROADCAST=65535, WM_SETTINGCHANGE=26)
  SendMessage(65535, 26, 0, 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePathEntry(WizardDirValue);
end;

// ---- neo-brutalist wizard: cream surfaces, black text ----------------------
const
  NbCream = $00E4EDF2;   // #f2ede4 as TColor (BGR)

procedure ApplyNeoBrutalism;
var
  I: integer;
  C: TComponent;
begin
  for I := 0 to WizardForm.ComponentCount - 1 do
  begin
    C := WizardForm.Components[I];
    if C is TPanel then
      TPanel(C).Color := NbCream;
    if C is TLabel then
      TLabel(C).Font.Color := clBlack;
    if C is TNewStaticText then
      TNewStaticText(C).Font.Color := clBlack;
  end;
  WizardForm.Color := NbCream;
end;

procedure InitializeWizard;
begin
  ApplyNeoBrutalism;
end;
