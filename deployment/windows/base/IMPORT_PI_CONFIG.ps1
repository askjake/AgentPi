param(
    [Parameter(Mandatory=$true)][string]$PiHost,
    [string]$PiUser = "agentpi001",
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
$scp = Get-Command scp.exe -ErrorAction SilentlyContinue
if (-not $scp) { throw "Windows OpenSSH scp.exe is unavailable." }

$Backend = Join-Path $Root "dish-chat\backend"
$AppDir = Join-Path $Backend "app"
$Dish = Join-Path $Root "dish-chat"
New-Item -ItemType Directory -Force -Path $Backend,$AppDir | Out-Null

Write-Host "This copies the existing DishChat runtime .env files from your Pi to this Windows dev tree."
Write-Host "Their contents are NOT printed."

& scp.exe "$PiUser@$PiHost`:/home/agentpi001/dish-chat/backend/.env" (Join-Path $Backend ".env")
if ($LASTEXITCODE -ne 0) { throw "backend/.env copy failed" }
& scp.exe "$PiUser@$PiHost`:/home/agentpi001/dish-chat/backend/app/.env" (Join-Path $AppDir ".env")
if ($LASTEXITCODE -ne 0) { throw "backend/app/.env copy failed" }
& scp.exe "$PiUser@$PiHost`:/home/agentpi001/dish-chat/.env" (Join-Path $Dish ".env")
if ($LASTEXITCODE -ne 0) { throw "dish-chat/.env copy failed" }

foreach ($file in @((Join-Path $Backend ".env"),(Join-Path $AppDir ".env"),(Join-Path $Dish ".env"))) {
    try {
        & icacls.exe $file /inheritance:r /grant:r "$env:USERNAME`:(R,W)" | Out-Null
    } catch {
        Write-Warning "Could not tighten ACL for $file; file was still copied."
    }
}
Write-Host "CONFIG IMPORT PASS"
