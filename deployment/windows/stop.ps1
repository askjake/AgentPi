$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"

foreach ($name in @("dishchat-frontend","dishchat-backend","agentpi")) {
    $pidFile = Join-Path $Run "$name.pid"
    if (Test-Path $pidFile) {
        $pidValue = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping $name PID $pidValue"
            taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}
Stop-AgentPiPostgres $Root
Write-Host "AGENTPI001 WINDOWS STACK STOPPED"
