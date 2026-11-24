#define AppVersion "0.1.0"
[Setup]
AppId={{F7A03C3B-F3B7-493E-90CF-8990D21B56D6}
AppName=SomePhylloscopus - 某种柳莺
AppVersion={#AppVersion}
AppPublisher=SomePhylloscopus
AppPublisherURL=https://github.com/mmax911110-lgtm/SomePhylloscopus
DefaultDirName={localappdata}\Programs\SomePhylloscopus
DefaultGroupName=SomePhylloscopus
DisableProgramGroupPage=yes
DisableWelcomePage=no
UsePreviousTasks=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
WizardSizePercent=115
OutputBaseFilename=SomePhylloscopus-v0.1.0-Windows-NVIDIA-Setup
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
UninstallDisplayIcon={app}\柳莺识别.exe
CloseApplications=no
RestartApplications=no
ExtraDiskSpaceRequired=18000000000
VersionInfoVersion=0.1.0.2
VersionInfoDescription=SomePhylloscopus Windows NVIDIA guided installer

[Languages]
Name: "zhcn"; MessagesFile: "ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[LangOptions]
zhcn.DialogFontName=Microsoft YaHei UI
zhcn.DialogFontSize=10
en.DialogFontName=Segoe UI
en.DialogFontSize=10

[CustomMessages]
zhcn.Welcome=此向导安装某种柳莺 v0.1.0 Windows NVIDIA 完整版。%n%n需要兼容的 NVIDIA 显卡及驱动。完整下载约 5.67 GiB，安装后约 10.1 GiB；安装过程中建议所选磁盘有 30 GB 可用空间。%n%n已下载的完整 ZIP 或分件可以继续使用。个人档案不会被打包进来。
en.Welcome=This wizard installs the complete SomePhylloscopus v0.1.0 Windows NVIDIA edition.%n%nA compatible NVIDIA GPU and driver are required. Download: 5.67 GiB. Installed size: about 10.1 GiB. Allow 30 GB free on the selected drive during installation.%n%nYou may reuse an existing ZIP or downloaded parts. Personal archives are not included.
zhcn.SourceTitle=安装文件从哪里来？
en.SourceTitle=Where are your installation files?
zhcn.SourceSubtitle=新用户可以直接下载；已下载的文件也能复用。
en.SourceSubtitle=Download automatically or reuse files you already have.
zhcn.SourcePrompt=请选择一种方式。只校验固定版本，软件内容完全相同。
en.SourcePrompt=Choose a source. Every option verifies and installs the same fixed release.
zhcn.Online=在线下载完整包（支持中断后继续）
en.Online=Download the complete package (resumable)
zhcn.Zip=我已经有合成好的完整 ZIP
en.Zip=I already have the complete assembled ZIP
zhcn.Parts=我已经下载了一些 part 分件
en.Parts=I already downloaded some part files
zhcn.ZipTitle=选择完整 ZIP
en.ZipTitle=Select the complete ZIP
zhcn.ZipSubtitle=不能单独选择 part04 等分件。
en.ZipSubtitle=Do not select individual part files such as part04.
zhcn.ZipPrompt=安装器会核对整包 SHA-256。所选 ZIP 原文件会保留。
en.ZipPrompt=Setup will verify the full SHA-256 and preserve your original ZIP.
zhcn.ZipLabel=完整 ZIP：
en.ZipLabel=Complete ZIP:
zhcn.PartsTitle=选择分件所在文件夹
en.PartsTitle=Select your parts folder
zhcn.PartsSubtitle=无需手动合并或解压任何分件。
en.PartsSubtitle=You do not need to merge or extract the parts yourself.
zhcn.PartsPrompt=把已下载的 part01a～part04 放在同一文件夹；缺失或损坏的件会自动补下，原分件会保留。
en.PartsPrompt=Keep part01a through part04 in one folder. Missing or damaged parts will be downloaded; your originals are preserved.
zhcn.PartsLabel=分件文件夹：
en.PartsLabel=Parts folder:
zhcn.PrepareTitle=正在准备安装文件
en.PrepareTitle=Preparing installation files
zhcn.PrepareSub=下载、校验和解包都在所选安装盘完成。
en.PrepareSub=Download, verification and extraction use the selected installation drive.
zhcn.CancelPending=正在停止，下载进度会保留……
en.CancelPending=Stopping; download progress will be preserved...
zhcn.EmptyDir=请选择一个空文件夹，以免覆盖已有软件和个人档案。
en.EmptyDir=Please choose an empty folder to protect existing installations and personal records.
zhcn.Desktop=创建桌面快捷方式
en.Desktop=Create a desktop shortcut
zhcn.Launch=打开某种柳莺
en.Launch=Launch SomePhylloscopus
zhcn.RetryInfo=安装文件准备失败。进度已保留，可重新运行向导继续。
en.RetryInfo=Preparation failed. Progress is preserved; reopen Setup to continue.

[Tasks]
Name: "desktopicon"; Description: "{cm:Desktop}"

[Files]
Source: "prepare_payload.ps1"; Flags: dontcopy
Source: "..\download-manifest.json"; Flags: dontcopy
Source: "{code:GetStageDir}\NVIDIA\*"; DestDir: "{app}\NVIDIA"; ExternalSize: 10825796146; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\app\*"; DestDir: "{app}\app"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\models\*"; DestDir: "{app}\models"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\assets\*"; DestDir: "{app}\assets"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\vendor\*"; DestDir: "{app}\vendor"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\文档\*"; DestDir: "{app}\文档"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs ignoreversion
Source: "{code:GetStageDir}\*.exe"; DestDir: "{app}"; ExternalSize: 0; Flags: external ignoreversion
Source: "{code:GetStageDir}\*.cmd"; DestDir: "{app}"; ExternalSize: 0; Flags: external ignoreversion
Source: "{code:GetStageDir}\*.txt"; DestDir: "{app}"; ExternalSize: 0; Flags: external ignoreversion
Source: "{code:GetStageDir}\config\*"; DestDir: "{app}\config"; ExternalSize: 0; Flags: external recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\某种柳莺"; Filename: "{app}\柳莺识别.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\某种柳莺"; Filename: "{app}\柳莺识别.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; postinstall defaults to checked; keep the user free to uncheck it.
Filename: "{app}\柳莺识别.exe"; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent

[Code]
var
  SourcePage: TInputOptionWizardPage;
  ZipPage: TInputFileWizardPage;
  PartsPage: TInputDirWizardPage;
  ProgressPage: TOutputProgressWizardPage;
  CacheDir, OptionsPath, LastError: String;
  Preparing, CancelRequested: Boolean;

function GetStageDir(Param: String): String;
begin
  Result := RemoveBackslashUnlessRoot(WizardDirValue) + '.somephylloscopus-setup-v0.1.0\stage';
end;

function FolderHasFiles(const Dir: String): Boolean;
var R: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Dir) + '*', R) then begin
    try
      repeat
        if (R.Name <> '.') and (R.Name <> '..') then begin Result := True; Break; end;
      until not FindNext(R);
    finally FindClose(R); end;
  end;
end;

procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption := CustomMessage('Welcome');
  SourcePage := CreateInputOptionPage(wpSelectDir, CustomMessage('SourceTitle'),
    CustomMessage('SourceSubtitle'), CustomMessage('SourcePrompt'), True, False);
  SourcePage.Add(CustomMessage('Online'));
  SourcePage.Add(CustomMessage('Zip'));
  SourcePage.Add(CustomMessage('Parts'));
  SourcePage.SelectedValueIndex := 0;
  ZipPage := CreateInputFilePage(SourcePage.ID, CustomMessage('ZipTitle'),
    CustomMessage('ZipSubtitle'), CustomMessage('ZipPrompt'));
  ZipPage.Add(CustomMessage('ZipLabel'), 'ZIP (*.zip)|*.zip', '.zip');
  PartsPage := CreateInputDirPage(ZipPage.ID, CustomMessage('PartsTitle'),
    CustomMessage('PartsSubtitle'), CustomMessage('PartsPrompt'), False, '');
  PartsPage.Add(CustomMessage('PartsLabel'));
  ZipPage.Values[0] := ExpandConstant('{param:ZIP|}');
  PartsPage.Values[0] := ExpandConstant('{param:PARTS|}');
  if ZipPage.Values[0] <> '' then SourcePage.SelectedValueIndex := 1
  else if PartsPage.Values[0] <> '' then SourcePage.SelectedValueIndex := 2;
  ProgressPage := CreateOutputProgressPage(CustomMessage('PrepareTitle'), CustomMessage('PrepareSub'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = ZipPage.ID) and (SourcePage.SelectedValueIndex <> 1)) or
            ((PageID = PartsPage.ID) and (SourcePage.SelectedValueIndex <> 2));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and FolderHasFiles(WizardDirValue) then begin
    SuppressibleMsgBox(CustomMessage('EmptyDir'), mbError, MB_OK, IDOK); Result := False;
  end;
  if (CurPageID = ZipPage.ID) and not FileExists(ZipPage.Values[0]) then Result := False;
  if (CurPageID = PartsPage.ID) and not DirExists(PartsPage.Values[0]) then Result := False;
end;

procedure WorkerLog(const S: String; const Error, FirstLine: Boolean);
var Tail, Caption: String; P, Value: Integer;
begin
  Log(S);
  if Pos('SP_ERROR|', S) = 1 then LastError := Copy(S, 10, MaxInt);
  if Pos('SP_PROGRESS|', S) = 1 then begin
    Tail := Copy(S, 13, MaxInt); P := Pos('|', Tail);
    if P > 0 then begin
      Value := StrToIntDef(Copy(Tail, 1, P-1), 0);
      Caption := Copy(Tail, P+1, MaxInt);
      if CancelRequested then Caption := CustomMessage('CancelPending');
      ProgressPage.SetText(Caption, CustomMessage('PrepareSub'));
      ProgressPage.SetProgress(Value, 100);
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer; SourceZip, SourceParts, Params: String; Options: TArrayOfString;
begin
  Result := '';
  if FolderHasFiles(WizardDirValue) then begin Result := CustomMessage('EmptyDir'); Exit; end;
  CacheDir := RemoveBackslashUnlessRoot(WizardDirValue) + '.somephylloscopus-setup-v0.1.0';
  ExtractTemporaryFile('prepare_payload.ps1');
  ExtractTemporaryFile('download-manifest.json');
  OptionsPath := ExpandConstant('{tmp}\installer-options.txt');
  SourceZip := ''; SourceParts := '';
  if SourcePage.SelectedValueIndex = 1 then SourceZip := ZipPage.Values[0];
  if SourcePage.SelectedValueIndex = 2 then SourceParts := PartsPage.Values[0];
  SetArrayLength(Options, 3);
  Options[0] := 'WorkDir=' + CacheDir;
  Options[1] := 'SourceZip=' + SourceZip;
  Options[2] := 'SourceParts=' + SourceParts;
  if not SaveStringsToUTF8File(OptionsPath, Options, False) then begin Result := 'Could not write installer options.'; Exit; end;
  Params := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + AddQuotes(ExpandConstant('{tmp}\prepare_payload.ps1')) +
    ' -Options ' + AddQuotes(OptionsPath);
  Preparing := True; CancelRequested := False; LastError := '';
  ProgressPage.SetText(CustomMessage('PrepareTitle'), CustomMessage('PrepareSub'));
  ProgressPage.SetProgress(0, 100);
  ProgressPage.Show;
  try
    WizardForm.CancelButton.Enabled := True;
    if not ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
      SW_HIDE, ewWaitUntilTerminated, Code, @WorkerLog) then Code := -1;
    if Code <> 0 then Result := CustomMessage('RetryInfo') + #13#10 + LastError;
  finally
    Preparing := False;
    ProgressPage.Hide;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Preparing then begin
    Cancel := False; Confirm := False; CancelRequested := True;
    SaveStringToFile(CacheDir + '\cancel.request', 'cancel', False);
    ProgressPage.SetText(CustomMessage('CancelPending'), CustomMessage('PrepareSub'));
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Params: String;
begin
  if (CurStep = ssPostInstall) and (OptionsPath <> '') then begin
    Params := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + AddQuotes(ExpandConstant('{tmp}\prepare_payload.ps1')) +
      ' -Options ' + AddQuotes(OptionsPath) + ' -Cleanup';
    if not ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
      SW_HIDE, ewWaitUntilTerminated, Code, nil) then Log('Cache cleanup could not start.');
  end;
end;
