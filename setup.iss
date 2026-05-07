; Inno Setup script for Book Downloader
; Download Inno Setup from https://jrsoftware.org/isinfo.php
; Run: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss

[Setup]
AppName=Book Downloader
AppVersion=1.5.0
AppPublisher=Book Downloader
DefaultDirName={autopf}\BookDownloader
DefaultGroupName=Book Downloader
OutputBaseFilename=book-downloader-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Book Downloader
UninstallDisplayIcon={app}\BookDownloader.exe
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icon.ico
OutputDir=.\dist

[Files]
Source: "backend\dist\BookDownloader.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.default.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Book Downloader"; Filename: "{app}\BookDownloader.exe"
Name: "{group}\Uninstall Book Downloader"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Book Downloader"; Filename: "{app}\BookDownloader.exe"

[Run]
Filename: "{app}\BookDownloader.exe"; Description: "Launch Book Downloader"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im BookDownloader.exe"; Flags: runhidden
