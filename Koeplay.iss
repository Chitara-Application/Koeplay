; ============================================================
;  Koeplay インストーラー
;  ビルド手順:
;    1) python -m PyInstaller --noconfirm --clean Koeplay.spec
;    2) このファイルを Inno Setup Compiler で開いて Compile
;  必要なファイル(このiss と同じフォルダー):
;    dist\Koeplay\...                (手順1の出力)
;    VBCABLE_Driver_Pack45.zip       (VB-CABLEのドライバパック)
; ============================================================
#define MyAppName "Koeplay"
#define MyAppVersion "1.0"
#define MyAppPublisher "Chitara-Applications"
#define MyAppURL "https://github.com/Chitara-Application/Koeplay"
#define MyAppExeName "Koeplay.exe"
#define VBZip "VBCABLE_Driver_Pack45.zip"
#define VBSetup "VBCABLE_Setup_x64.exe"

[Setup]
AppId={{9B5C83CC-FDC8-4263-ABEC-1EAD5AD0766C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=Koeplay_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
; インストーラー自身(Koeplay_Setup_1.0.exe)のアイコン
SetupIconFile=assets\icon.ico
; インストーラーのファイルのプロパティに表示される情報
VersionInfoVersion=1.0.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} セットアップ
VersionInfoProductName={#MyAppName}
; VB-CABLE(ドライバ)の導入に管理者権限が必要
PrivilegesRequired=admin
; 常駐中(トレイ)のKoeplayを、更新時に自動で閉じる
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成する"; GroupDescription: "追加タスク:"; Flags: unchecked
; VB-CABLEが未導入の時だけ表示される
Name: "installvb"; Description: "VB-CABLE(Discordへ音を送る仮想オーディオケーブル)を導入する"; GroupDescription: "必要なコンポーネント:"; Check: VBCableMissing

[Files]
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#VBZip}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: installvb

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName}を起動する"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
const
  RunOnceKey = 'Software\Microsoft\Windows\CurrentVersion\RunOnce';

var
  VBCheckDone: Boolean;
  VBIsMissing: Boolean;
  VBNeedsRestart: Boolean;

function PowerShellExe: String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

{ PowerShellで条件を調べる。条件が真なら True。実行できなかった時は Failed を True にする }
function PsCheck(const Condition: String; var Failed: Boolean): Boolean;
var
  ResultCode: Integer;
  Params: String;
begin
  Params := '-NoProfile -ExecutionPolicy Bypass -Command "if (' + Condition + ') { exit 0 } else { exit 1 }"';
  Failed := not Exec(PowerShellExe, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (not Failed) and (ResultCode = 0);
end;

{ VB-CABLEのドライバが入っているか。調べられない時は「入っている」とみなす(再導入の事故を避けるため) }
function VBCableInstalled: Boolean;
var
  Failed: Boolean;
begin
  Result := PsCheck('Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like ''*VB-Audio Virtual Cable*'' }', Failed);
  if Failed then
    Result := True;
end;

{ アプリから見える録音デバイス(CABLE Output)が使える状態か }
function VBEndpointReady: Boolean;
var
  Failed: Boolean;
begin
  Result := PsCheck('Get-PnpDevice -Class AudioEndpoint -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like ''*CABLE Output*'' -and $_.Status -eq ''OK'' }', Failed);
end;

function VBCableMissing: Boolean;
begin
  if not VBCheckDone then
  begin
    VBIsMissing := not VBCableInstalled;
    VBCheckDone := True;
  end;
  Result := VBIsMissing;
end;

{ 展開先から VBCABLE_Setup_x64.exe を探す(ZIP内のフォルダー構成が変わっても動くように) }
function FindSetup(const Dir: String): String;
var
  FindRec: TFindRec;
  Sub: String;
begin
  Result := '';
  if FileExists(Dir + '\{#VBSetup}') then
  begin
    Result := Dir + '\{#VBSetup}';
    Exit;
  end;
  if FindFirst(Dir + '\*', FindRec) then
  begin
    try
      repeat
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Sub := FindSetup(Dir + '\' + FindRec.Name);
          if Sub <> '' then
          begin
            Result := Sub;
            Exit;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure InstallVBCable;
var
  ZipPath, ExtractDir, SetupPath: String;
  ResultCode: Integer;
begin
  ZipPath := ExpandConstant('{tmp}\{#VBZip}');
  ExtractDir := ExpandConstant('{tmp}\vbcable');

  { 1) 解凍 }
  WizardForm.StatusLabel.Caption := 'VB-CABLEを展開しています...';
  if (not Exec(PowerShellExe,
      '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' + ZipPath + ''' -DestinationPath ''' + ExtractDir + ''' -Force"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
  begin
    MsgBox('VB-CABLEの展開に失敗しました。' + #13#10 +
           'Koeplay本体は導入済みです。VB-CABLEは公式サイト(https://vb-audio.com/Cable/)から手動で導入してください。',
           mbError, MB_OK);
    Exit;
  end;

  SetupPath := FindSetup(ExtractDir);
  if SetupPath = '' then
  begin
    MsgBox('VB-CABLEのセットアップが見つかりませんでした。' + #13#10 +
           'VB-CABLEは公式サイト(https://vb-audio.com/Cable/)から手動で導入してください。',
           mbError, MB_OK);
    Exit;
  end;

  { 2) セットアップを起動(利用者が「Install Driver」を押す) }
  MsgBox('これからVB-CABLEのセットアップ画面が開きます。' + #13#10 + #13#10 +
         '  1. 「Install Driver」(ドライバのインストール)を押す' + #13#10 +
         '  2. 完了の表示が出たら閉じる' + #13#10 + #13#10 +
         '再起動の確認は、このインストーラーの最後に出ます。' + #13#10 +
         'セットアップ画面からは再起動しないでください。' + #13#10 + #13#10 +
         'VB-CABLEは VB-Audio Software のドネーションウェアです(www.vb-cable.com)。',
         mbInformation, MB_OK);
  WizardForm.StatusLabel.Caption := 'VB-CABLEのセットアップが終わるのを待っています...';
  Exec(SetupPath, '', ExtractDir, SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode);

  { 3) 結果の判定 }
  if VBEndpointReady then
  begin
    { すぐ使える状態: 再起動は不要。そのままKoeplayを起動できる }
    VBNeedsRestart := False;
  end
  else if VBCableInstalled then
  begin
    { ドライバは入ったが、まだ使えない状態: 再起動が必要。再起動後にKoeplayを1回だけ自動起動する }
    VBNeedsRestart := True;
    RegWriteStringValue(HKLM, RunOnceKey, '{#MyAppName}',
      '"' + ExpandConstant('{app}\{#MyAppExeName}') + '"');
  end
  else
  begin
    MsgBox('VB-CABLEが導入されませんでした。' + #13#10 +
           'Koeplay本体は導入済みです。VB-CABLEは後から導入できます(Koeplayの設定 > VB-CABLE に案内があります)。',
           mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('installvb') and (not WizardSilent) then
    InstallVBCable;
end;

{ 再起動が必要な時だけ、最後のページに再起動の確認が出る }
function NeedRestart(): Boolean;
begin
  Result := VBNeedsRestart;
end;
