; Установщик DocRenamer Offline для Windows.
;
; Ставится в профиль пользователя, поэтому не требует прав администратора и
; не показывает запрос UAC. Каталог установки доступен на запись — это важно:
; программа ведёт журналы и файлы отмены рядом с собой.
;
; Сборка: ISCC.exe installer\DocRenamer.iss

#define AppName "Переименователь документов"
#define AppVersion "1.1.1"
#define AppPublisher "DocRenamer"
#define AppExeName "DocRenamer.exe"

[Setup]
AppId={{7D3F2A61-4C9E-4B2A-9A1D-DC7E6B5A0F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\DocRenamer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=DocRenamer-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
AppComments=Локальное переименование документов по содержимому. Работает без Интернета.
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName}

; Обновление поверх прежней версии.
; CloseApplications: Windows сама закрывает запущенные файлы программы через
; Restart Manager — иначе установка спотыкается о занятый DocRenamer.exe.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
SetupMutex=DocRenamerOfflineSetup
DirExistsWarning=no
UsePreviousAppDir=yes
AllowCancelDuringInstall=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Значок на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "contextmenu"; Description: "Пункт «Переименовать файлы (DocRenamer)» в меню папки"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\DocRenamer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Программа обновления сама запускает этот установщик, поэтому её файл может
; быть занят. Флаг replacesameversion отключён, а сама программа обновления
; запускается из временной копии — см. docrenamer_updater/cli.py.
Source: "..\dist\updater\DocRenamerUpdate.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist uninsrestartdelete
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\runtime\README.md"; DestDir: "{app}\runtime"; Flags: ignoreversion

[Dirs]
; Программа пишет журналы и файлы отмены рядом с собой — каталоги создаются заранее.
Name: "{app}\logs"
Name: "{app}\manifests"
Name: "{app}\runtime_temp"
Name: "{app}\models"
Name: "{app}\runtime"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Журналы работы"; Filename: "{app}\logs"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Пункт контекстного меню для папки и для пустого места внутри папки.
Root: HKCU; Subkey: "Software\Classes\Directory\shell\DocRenamer"; ValueType: string; ValueName: ""; ValueData: "Переименовать файлы (DocRenamer)"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\DocRenamer"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\DocRenamer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\DocRenamer"; ValueType: string; ValueName: ""; ValueData: "Переименовать файлы (DocRenamer)"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\DocRenamer"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\DocRenamer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%V"""; Flags: uninsdeletekey; Tasks: contextmenu

[Code]
{ Перед установкой снимаем прежнюю версию: остатки старой раскладки мешают
  копированию, а обновление должно проходить без вопросов к пользователю. }
function PreviousUninstaller(): String;
var
  Key: String;
  Value: String;
begin
  Result := '';
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1';
  if RegQueryStringValue(HKCU, Key, 'QuietUninstallString', Value) then
    Result := Value
  else if RegQueryStringValue(HKLM, Key, 'QuietUninstallString', Value) then
    Result := Value
  else if RegQueryStringValue(HKCU, Key, 'UninstallString', Value) then
    Result := Value + ' /VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
  else if RegQueryStringValue(HKLM, Key, 'UninstallString', Value) then
    Result := Value + ' /VERYSILENT /SUPPRESSMSGBOXES /NORESTART';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Command: String;
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;
  Command := PreviousUninstaller();
  if Command <> '' then
  begin
    { Ошибку снятия прежней версии не считаем поводом отменить установку:
      файлы всё равно будут перезаписаны. }
    Exec('>', Command, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1200);
  end;
end;

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Служебные данные самой программы. Пользовательские документы не трогаются
; никогда: программа их не копирует и не перемещает.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\manifests"
Type: filesandordirs; Name: "{app}\runtime_temp"
