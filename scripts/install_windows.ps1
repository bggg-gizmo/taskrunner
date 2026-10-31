# Task Runner per-user installer. No administrator privileges or virtualenv.
[CmdletBinding()]
param([string]$Source = '', [switch]$KeepExistingData)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Source) { $Source = Join-Path $root 'dist\TaskRunner' }
$src = [IO.Path]::GetFullPath($Source)
$executable = Join-Path $src 'TaskRunner.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Built TaskRunner.exe not found at $executable. Run BUILD_WINDOWS.cmd first."
}
$install = Join-Path $env:LOCALAPPDATA 'Programs\TaskRunner'
$parent = Split-Path $install -Parent
$staging = Join-Path $parent ('TaskRunner.install.'+[guid]::NewGuid().ToString('N'))
$old = Join-Path $parent ('TaskRunner.previous.'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
$committed = $false
try {
    Get-ChildItem -LiteralPath $src -Force | Copy-Item -Destination $staging -Recurse -Force -ErrorAction Stop
    if (-not (Test-Path (Join-Path $staging 'TaskRunner.exe'))) { throw 'Staging missing executable' }
    Copy-Item (Join-Path $root 'scripts\uninstall_windows.ps1') (Join-Path $staging 'uninstall_windows.ps1') -Force
    Copy-Item (Join-Path $root 'UNINSTALL_WINDOWS.cmd') (Join-Path $staging 'UNINSTALL_WINDOWS.cmd') -Force
    if (Test-Path $install) { Move-Item -LiteralPath $install -Destination $old }
    Move-Item -LiteralPath $staging -Destination $install
    $committed = $true
    $menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Task Runner'
    New-Item -ItemType Directory -Path $menu -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $menu 'Task Runner.lnk'))
    $shortcut.TargetPath = Join-Path $install 'TaskRunner.exe'
    $shortcut.WorkingDirectory = $install
    $shortcut.IconLocation = (Join-Path $install 'TaskRunner.exe') + ',0'
    $shortcut.Save()
    $uninstallShortcut = $shell.CreateShortcut((Join-Path $menu 'Uninstall Task Runner.lnk'))
    $uninstallShortcut.TargetPath = Join-Path $install 'UNINSTALL_WINDOWS.cmd'
    $uninstallShortcut.WorkingDirectory = $install
    $uninstallShortcut.Save()
    $key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BackgroundGremlinGroup.TaskRunner'
    New-Item -Path $key -Force | Out-Null
    New-ItemProperty -Path $key -Name DisplayName -Value 'Task Runner' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name DisplayVersion -Value '1.3.0' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name Publisher -Value 'Background Gremlin Group' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name InstallLocation -Value $install -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name DisplayIcon -Value (Join-Path $install 'TaskRunner.exe') -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name UninstallString -Value ('"'+(Join-Path $install 'UNINSTALL_WINDOWS.cmd')+'"') -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $key -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $key -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
    Write-Host "SUCCESS: Task Runner installed at $install"
    Write-Host 'Start Menu shortcut and Windows Apps uninstall entry registered.'
    Write-Host 'Local workflows, shared Python packages, and Playwright cache were not modified.'
} catch {
    if (-not $committed -and (Test-Path $old) -and -not (Test-Path $install)) {
        Move-Item -LiteralPath $old -Destination $install
    }
    throw
} finally {
    if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    if ($committed -and (Test-Path $old)) { Remove-Item -LiteralPath $old -Recurse -Force }
}
