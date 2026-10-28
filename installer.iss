; Inno Setup 安装脚本 — Anhu 百宝箱
; 用法:
;   1) 在 PyCharm 里先用 PyInstaller 打包 (AnhuToolbox.spec -> dist\Anhu百宝箱\)
;   2) 用 Inno Setup 6 打开本文件编译, 或命令行执行:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;   3) 产物在 installer\ 目录下
;
; 说明:
;   - 默认安装到 D:\Anhu百宝箱, 无需管理员权限,
;     这样 data\ 和 tools\ 两个外置可写目录能正常读写。
;   - 若用户在向导里改到受保护目录(如 Program Files), Inno Setup 会自动请求提权。
;   - data\ 里的配置只在首次安装时写入, 升级时不会覆盖用户已有配置;
;     tools\ 里的工具文件(除 tools.json)只在首次安装时写入, tools.json 每次都会更新。

#define MyAppName "Anhu百宝箱"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Anhu"
#define MyAppExeName "Anhu百宝箱.exe"

[Setup]
AppId={{7F2B1C3D-4E5A-4B6C-9D8E-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVerName={#MyAppName} {#MyAppVersion}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=D:\Anhu百宝箱
DefaultGroupName=Anhu百宝箱
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=Anhu百宝箱_{#MyAppVersion}
SetupIconFile=anhutoolbox.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\Anhu百宝箱\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Anhu百宝箱\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
; tools.json 是工具清单, 每次安装/升级都要用新版本覆盖,
; 否则升级时旧清单不更新, 新增的工具(如 Geek/TCPView)不会出现在工具箱里
Source: "tools\tools.json"; DestDir: "{app}\tools"; Flags: ignoreversion
; 其余工具文件(体积大)保持 onlyifdoesntexist, 升级时不重复覆盖
Source: "tools\*"; DestDir: "{app}\tools"; Excludes: "tools.json"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('是否同时删除用户数据（配置和预设命令）？' + #13#10 +
              '数据保存在 data 目录中。' + #13#10#13#10 +
              '点击「是」删除数据，点击「否」保留数据，方便以后重装继续使用。',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{app}\data'), True, True, True);
  end;
end;
