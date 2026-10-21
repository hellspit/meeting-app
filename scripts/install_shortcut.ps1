$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the app dependencies before creating the shortcut.'
}
$desktopPath = [Environment]::GetFolderPath('DesktopDirectory')
$shortcutPath = Join-Path $desktopPath 'Meeting Assistant.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonPath
$shortcut.Arguments = '-m src.main'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Meeting Assistant - live transcription and suggested answers'
$shortcut.IconLocation = "$pythonPath,0"
$shortcut.Save()
Write-Output "Created desktop shortcut: $shortcutPath"
