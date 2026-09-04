; 四象 / SIXIANG 安装脚本。在项目根执行：
; ISCC.exe /DMyAppVersion=1.3.29 setup\sixiang.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "四象"
#define MyAppNameEn "SIXIANG"
#define MyAppExeName "SIXIANG.exe"

[Setup]
AppId={{B7E91C4A-2F18-4D6B-9A33-E5C8F0A17D24}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppNameEn} {#MyAppVersion}
AppPublisher={#MyAppNameEn}
DefaultDirName={localappdata}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
DisableDirPage=auto
AlwaysShowDirOnReadyPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SIXIANG-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=classic
SetupIconFile=..\src\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
UsePreviousAppDir=yes
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 不碰用户的 data.db / themes（安装器只投放主程序）
[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Win11 开始菜单「所有应用」不展示子文件夹里的快捷方式，必须直接放在 Programs 根下
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  { 覆盖完成后稍等再启动，避免杀软正在扫描刚写入的 onefile }
  if CurStep = ssPostInstall then
    Sleep(2500);
end;
