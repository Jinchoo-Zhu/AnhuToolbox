; Inno Setup 安装脚本 — Anhu 百宝箱
; 用法:
;   1) 在 PyCharm 里先用 PyInstaller 打包 (AnhuToolbox.spec -> dist\Anhu百宝箱\)
;   2) 用 Inno Setup 6 打开本文件编译, 或命令行执行:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;   3) 产物在 installer\ 目录下
;
; 说明:
;   - 默认安装到 D:\Anhu百宝箱, 无需管理员权限；若安装目录不可写，
;     程序会自动把 data 和自定义库清单放到 %LOCALAPPDATA%\AnhuToolbox。
;   - 若用户在向导里改到受保护目录(如 Program Files), Inno Setup 会自动请求提权。
;   - data\ 里的配置只在首次安装时写入, 升级时不会覆盖用户已有配置;
;     官方 tools 是可选的“安护工具箱”组件, 由安装任务决定是否复制;
;     用户自定义库清单 tools.user.json 始终保留。

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
UsePreviousTasks=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "installtoolbox"; Description: "安装安护工具箱（可选第三方工具）"; GroupDescription: "可选组件"

[Files]
Source: "dist\Anhu百宝箱\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Anhu百宝箱\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
; tools.json 是工具清单, 每次安装/升级都要用新版本覆盖,
; 否则升级时旧清单不更新, 新增的工具(如 Geek/TCPView)不会出现在工具箱里
Source: "tools\tools.json"; DestDir: "{app}\tools"; Tasks: installtoolbox; Flags: ignoreversion
; 官方便携工具及资源在升级时同步更新，避免 tools.json 已指向新文件但磁盘上
; 仍是旧版本。用户自己维护的 tools.user.json 单独排除。
Source: "tools\*"; DestDir: "{app}\tools"; Excludes: "tools.json,tools.user.json,toolbox.install-state"; Tasks: installtoolbox; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure RemoveOfficialToolboxFiles();
var
  ToolsDir: String;
begin
  ToolsDir := ExpandConstant('{app}\tools');
  DeleteFile(AddBackslash(ToolsDir) + 'tools.json');
  DeleteFile(AddBackslash(ToolsDir) + 'tools.gresource');
  DeleteFile(AddBackslash(ToolsDir) + 'README.md');
  DelTree(AddBackslash(ToolsDir) + '综合工具', True, True, True);
  DelTree(AddBackslash(ToolsDir) + '硬盘工具', True, True, True);
  DelTree(AddBackslash(ToolsDir) + '读写器工具', True, True, True);
  DelTree(AddBackslash(ToolsDir) + '海康工具', True, True, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  StateFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    ; 旧版曾把 tools 同时打入 lib\tools，这份副本不会被程序使用。
    DelTree(ExpandConstant('{app}\lib\tools'), True, True, True);
    ForceDirectories(ExpandConstant('{app}\tools'));
    StateFile := ExpandConstant('{app}\tools\toolbox.install-state');
    if WizardIsTaskSelected('installtoolbox') then
      SaveStringToFile(StateFile, '1', False)
    else
    begin
      RemoveOfficialToolboxFiles();
      SaveStringToFile(StateFile, '0', False);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('是否同时删除用户数据（配置和预设命令）？' + #13#10 +
              '数据保存在应用 data 目录或 %LOCALAPPDATA%\AnhuToolbox 中。' + #13#10#13#10 +
              '点击「是」删除数据，点击「否」保留数据，方便以后重装继续使用。',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{app}\data'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\AnhuToolbox'), True, True, True);
    end;
  end;
end;
