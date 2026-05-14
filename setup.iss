; Inno Setup script for ebook-pdf-downloader
; Download Inno Setup from https://jrsoftware.org/isinfo.php
; Run: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss

[Setup]
AppName=ebook-pdf-downloader
AppVersion=1.3.1
AppPublisher=ebook-pdf-downloader
DefaultDirName={autopf}\ebook-pdf-downloader
DefaultGroupName=ebook-pdf-downloader
OutputBaseFilename=ebook-pdf-downloader-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=ebook-pdf-downloader
UninstallDisplayIcon={app}\ebook-pdf-downloader.exe
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icon.ico
OutputDir=.\dist

[Files]
Source: "backend\dist\ebook-pdf-downloader.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.default.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "local-llm-pdf-ocr\src\*"; DestDir: "{app}\local-llm-pdf-ocr\src"; Flags: ignoreversion recursesubdirs
Source: "local-llm-pdf-ocr\pyproject.toml"; DestDir: "{app}\local-llm-pdf-ocr"; Flags: ignoreversion

[Icons]
Name: "{group}\ebook-pdf-downloader"; Filename: "{app}\ebook-pdf-downloader.exe"
Name: "{group}\Uninstall ebook-pdf-downloader"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ebook-pdf-downloader"; Filename: "{app}\ebook-pdf-downloader.exe"

[Run]
Filename: "{app}\ebook-pdf-downloader.exe"; Description: "Launch ebook-pdf-downloader"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im ebook-pdf-downloader.exe"; Flags: runhidden
