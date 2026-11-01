# Per-user uninstaller. Data deletion requires the user's explicit confirmation.
[CmdletBinding()]
param([switch]$RemoveUserData)
$ErrorActionPreference = 'Stop'
$install = Join-Path $env:LOCALAPPDATA 'Programs\TaskRunner'
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BackgroundGremlinGroup.TaskRunner'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Task Runner'
$data = Join-Path $env:LOCALAPPDATA 'TaskRunner'
$exe = Join-Path $install 'TaskRunner.exe'
if (Get-Process -Name TaskRunner -ErrorAction SilentlyContinue) {
    throw 'Close all Task Runner windows and running jobs before uninstalling.'
}
# Remove only Task Runner's exact own scheduler task.
$task = Get-ScheduledTask -TaskName 'TaskRunnerScheduler' -ErrorAction SilentlyContinue
if ($task) { Unregister-ScheduledTask -TaskName 'TaskRunnerScheduler' -Confirm:$false }
if (Test-Path $menu) { Remove-Item -LiteralPath $menu -Recurse -Force }
if (Test-Path $registry) { Remove-Item -LiteralPath $registry -Recurse -Force }
if ($RemoveUserData) {
    $answer = Read-Host 'Delete all saved workflows, SQLite data, capture images, and logs? Type DELETE to confirm'
    if ($answer -ceq 'DELETE' -and (Test-Path $data)) {
        Remove-Item -LiteralPath $data -Recurse -Force
        Write-Host 'Local Task Runner data removed.'
    } else { Write-Host 'Local Task Runner data preserved.' }
}
# Do not delete the shared Python packages or shared Playwright browser cache.
if (Test-Path $install) { Remove-Item -LiteralPath $install -Recurse -Force }
Write-Host 'Task Runner uninstalled. Shared development tools and Python packages retained.'
if (Test-Path $data) { Write-Host "Saved user data retained at $data" }
