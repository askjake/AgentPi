param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Continue"
$Run = Join-Path $Root "runtime"
foreach ($name in @("dishchat-enhanced","dishchat-frontend","dishchat-backend","agentpi","db-tunnel")) {
    $pidFile = Join-Path $Run "$name.pid"
    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue) {
            Write-Host "Stopping $name PID $pidValue"
            taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "STOP COMPLETE"
