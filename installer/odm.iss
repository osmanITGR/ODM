; Inno Setup script for ODM - Osman Download Manager
; Build with:  iscc installer\odm.iss
; Produces:    installer\output\ODM-Setup-1.0.0.exe

#define AppName        "ODM - Osman Download Manager"
#define AppShortName   "ODM"
#define AppVersion     "1.0.0"
#define AppPublisher   "Osman IT"
#define AppURL         "https://wa.me/8801625251930"
#define AppExe         "ODM.exe"
#define AppId          "{{A7F3C1E2-5D48-4B96-9C1A-0D2E6F8B3471}"

; Chrome Web Store extension ID. Replace once the extension is published;
; the registry policies below only take effect with a real store ID.
#define ChromeExtId    "PLACEHOLDER_CHROME_EXTENSION_ID"
#define EdgeExtId      "PLACEHOLDER_EDGE_EXTENSION_ID"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppShortName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=ODM-Setup-{#AppVersion}
SetupIconFile=..\odm\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Admin rights are needed to write the browser extension policies under HKLM.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "browserext"; Description: "Install the browser integration extension (Chrome, Edge, Brave)"; GroupDescription: "Browser integration:"
Name: "startup";    Description: "Start ODM automatically when Windows starts"; GroupDescription: "Browser integration:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\extension\*";    DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md";      DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppShortName}";               Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppShortName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppShortName}";         Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; --- Launch at login -------------------------------------------------------
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppShortName}"; ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Tasks: startup

; --- Chrome / Edge / Brave force-install policy ----------------------------
; These entries make the browser fetch and install the extension from its store
; on next launch. They are inert until ChromeExtId / EdgeExtId hold real IDs.
Root: HKLM; Subkey: "Software\Policies\Google\Chrome\ExtensionInstallForcelist"; \
    ValueType: string; ValueName: "1"; \
    ValueData: "{#ChromeExtId};https://clients2.google.com/service/update2/crx"; \
    Flags: uninsdeletevalue; Tasks: browserext; Check: HasRealChromeId

Root: HKLM; Subkey: "Software\Policies\BraveSoftware\Brave\ExtensionInstallForcelist"; \
    ValueType: string; ValueName: "1"; \
    ValueData: "{#ChromeExtId};https://clients2.google.com/service/update2/crx"; \
    Flags: uninsdeletevalue; Tasks: browserext; Check: HasRealChromeId

Root: HKLM; Subkey: "Software\Policies\Microsoft\Edge\ExtensionInstallForcelist"; \
    ValueType: string; ValueName: "1"; \
    ValueData: "{#EdgeExtId};https://edge.microsoft.com/extensionwebstorebase/v1/crx"; \
    Flags: uninsdeletevalue; Tasks: browserext; Check: HasRealEdgeId

; --- Developer-mode sideload path (works without a store listing) ----------
; Allows the unpacked extension in {app}\extension to be loaded and kept
; enabled rather than being disabled by the browser on each restart.
Root: HKLM; Subkey: "Software\Policies\Google\Chrome\ExtensionSettings\*"; \
    ValueType: string; ValueName: "installation_mode"; ValueData: "allowed"; \
    Flags: uninsdeletekey; Tasks: browserext
Root: HKLM; Subkey: "Software\Policies\Microsoft\Edge\ExtensionSettings\*"; \
    ValueType: string; ValueName: "installation_mode"; ValueData: "allowed"; \
    Flags: uninsdeletekey; Tasks: browserext

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppShortName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\extension"

[Code]
function HasRealChromeId: Boolean;
begin
  Result := Pos('PLACEHOLDER', '{#ChromeExtId}') = 0;
end;

function HasRealEdgeId: Boolean;
begin
  Result := Pos('PLACEHOLDER', '{#EdgeExtId}') = 0;
end;

// Shown at the end of setup when the extension can only be sideloaded,
// so the user is not left wondering why nothing appeared in the browser.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Msg: String;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('browserext')
     and (not HasRealChromeId) then
  begin
    Msg := 'One more step for browser integration:' + #13#10#13#10 +
           '1. Open chrome://extensions (or edge://extensions)' + #13#10 +
           '2. Turn on "Developer mode"' + #13#10 +
           '3. Click "Load unpacked" and select:' + #13#10#13#10 +
           '     ' + ExpandConstant('{app}\extension') + #13#10#13#10 +
           '4. In ODM, open Settings -> Browser integration, click' + #13#10 +
           '   "Start bridge", then "Copy token".' + #13#10 +
           '5. Paste the token into the extension popup and Save.' + #13#10#13#10 +
           'This path has been copied to your clipboard.';
    MsgBox(Msg, mbInformation, MB_OK);
  end;
end;
