#define AppName "JL Engine"
#define AppVersion "0.1.0"
#define AppPublisher "JL Engine"

[Setup]
AppId={{B4A1B14A-6E9D-4D0E-AF5B-8E64D90E2101}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\JL Engine
DefaultGroupName=JL Engine
OutputDir=..\..\dist
OutputBaseFilename=JL-Engine-Setup
Compression=none
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
CloseApplications=yes

[Dirs]
Name: "{localappdata}\JL-Engine"; Flags: uninsneveruninstall

[Files]
Source: "..\..\*"; DestDir: "{app}"; Excludes: ".git\*,.github\*,dist\*,node_modules\*,.venv\*,venv\*,__pycache__\*,packaging\windows\runtime\*,packaging\windows\depot\*,packaging\windows\python\*,*.db,*.sqlite,*.sqlite3"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "runtime\*"; DestDir: "{app}\runtime"; Excludes: "include\*,lib\*,libexec\*,share\doc\*,share\julia\compiled\*,share\julia\stdlib\*\*\test\*,share\julia\stdlib\*\*\docs\*,share\julia\stdlib\*\*\.github\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "depot\*"; DestDir: "{app}\depot"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JL Engine"; Filename: "{app}\packaging\windows\Launch-JL-Engine.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\JL Engine"; Filename: "{app}\packaging\windows\Launch-JL-Engine.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\packaging\windows\Launch-JL-Engine.cmd"; Description: "Launch JL Engine"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\depot"
Type: filesandordirs; Name: "{app}\python"





