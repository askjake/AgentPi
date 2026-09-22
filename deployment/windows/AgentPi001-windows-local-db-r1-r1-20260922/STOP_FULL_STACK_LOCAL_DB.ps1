param([string]$Root = "")
$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
foreach ($name in @("dishchat-enhanced","dishchat-frontend","dishchat-backend","agentpi")) {
    $pidFile = Join-Path $Run "$name.pid"
    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping $name PID $pidValue"
            taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}
& (Join-Path $PSScriptRoot "STOP_LOCAL_POSTGRES.ps1") -Root $Root
Write-Host "FULL LOCAL-DB STACK STOP COMPLETE"
