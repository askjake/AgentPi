param(
    [string]$Root = "",
    [Parameter(Mandatory=$true)][string]$PiHost,
    [string]$PiUser = "agentpi001"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$AppDir = Join-Path $Root "dish-chat\backend\app"
$LogsDir = Join-Path $AppDir "logs"
if (-not (Test-Path $AppDir)) { throw "DishChat app directory missing: $AppDir" }
if (-not (Get-Command scp.exe -ErrorAction SilentlyContinue)) { throw "scp.exe is unavailable" }

Write-Host "Recovering the real DishChat app.logs source package from the Pi."
Write-Host "No .env or credential files are copied by this step."
if (Test-Path $LogsDir) {
    $backup = "$LogsDir.pre-local-db-$(Get-Date -Format yyyyMMddTHHmmss)"
    Move-Item -LiteralPath $LogsDir -Destination $backup
    Write-Host "Existing logs package backed up to: $backup"
}

$remote = "${PiUser}@${PiHost}:/home/agentpi001/dish-chat/backend/app/logs"
& scp.exe -r $remote $AppDir
if ($LASTEXITCODE -ne 0) { throw "Failed to copy app/logs from the Pi" }

Get-ChildItem -Path $LogsDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$required = @("__init__.py","models.py","router.py","schemas.py","service.py")
foreach ($name in $required) {
    $p = Join-Path $LogsDir $name
    if (-not (Test-Path $p)) { throw "Recovered app.logs package is incomplete: missing $name" }
}
Write-Host "PASS: app.logs source package recovered."
