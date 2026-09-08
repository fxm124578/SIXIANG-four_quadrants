; 四象 / SIXIANG 安装脚本。在项目根执行：
; ISCC.exe /DMyAppVersion=X.Y.Z setup\sixiang.iss
; 载荷：dist\SIXIANG\ onedir 整目录（先按 RELEASE.md 步骤 4 用 PyInstaller --onedir 打包）
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
; 不碰用户的 data.db / themes（安装器只投放主程序与页面资源）
; {app}\web 为外置页面层（用户可改文件重启生效）；_internal\web 保留作兜底。
; 注：下列两段 Source 均针对 PyInstaller 6+（依赖位于 _internal\）；
; 若打包机为 PyInstaller 5.x，第二段 Source 应改为 ..\dist\SIXIANG\web\*。
[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; onedir 目录即安装内容：exe + _internal（模块/内置 web/themes/ico 兜底）
Source: "..\dist\SIXIANG\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 外置页面层：把 _internal\web 再复制一份到 {app}\web（改文件即刷新）；
; 用户误删/覆盖时由程序回退 _internal\web，不会白屏
Source: "..\dist\SIXIANG\_internal\web\*"; DestDir: "{app}\web"; Flags: recursesubdirs createallsubdirs ignoreversion
; 用户可见卸载入口。Inno 仍生成 unins000.exe（系统卸载用）；本文件只转调它。
Source: "uninstall.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Win11 开始菜单「所有应用」不展示子文件夹里的快捷方式，必须直接放在 Programs 根下
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall

[UninstallDelete]
Type: files; Name: "{app}\uninstall.exe"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  { 覆盖完成后稍等再启动，避免杀软正在扫描刚写入的 onedir 文件 }
  if CurStep = ssPostInstall then
    Sleep(2500);
end;
