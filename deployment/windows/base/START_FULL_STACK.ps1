param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$OpenBrowser = $true,
    [switch]$StartEnhanced = $false
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
New-Item -ItemType Directory -Force -Path $Run,$Logs | Out-Null

$DishBackend = Join-Path $Root "dish-chat\backend"
$DishPy = Join-Path $DishBackend ".venv-windows\Scripts\python.exe"
$AgentRoot = Join-Path $Root "AgentPi"
$AgentPy = Join-Path $AgentRoot ".venv-windows\Scripts\python.exe"
if (-not (Test-Path $DishPy)) { throw "DishChat venv missing; run SETUP_FULL_WINDOWS.ps1" }
if (-not (Test-Path $AgentPy)) { throw "AgentPi venv missing; run SETUP_FULL_WINDOWS.ps1" }
if (-not (Test-Path (Join-Path $DishBackend ".env"))) { throw "DishChat backend .env missing; run IMPORT_PI_CONFIG.ps1" }

function Start-LoggedProcess([string]$Name,[string]$Exe,[string[]]$ProcessArgs,[string]$Cwd) {
    $pidFile = Join-Path $Run "$Name.pid"
    if (Test-Path $pidFile) {
        $old = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
            Write-Host "$Name already running as PID $old"
            return
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    $stdout = Join-Path $Logs "$Name.out.log"
    $stderr = Join-Path $Logs "$Name.err.log"
    $p = Start-Process -FilePath $Exe -ArgumentList $ProcessArgs -WorkingDirectory $Cwd -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath $pidFile -Value $p.Id
    Write-Host "$Name PID: $($p.Id)"
}

# Require the PostgreSQL tunnel before DishChat startup.
$client = New-Object System.Net.Sockets.TcpClient
try {
    $iar = $client.BeginConnect("127.0.0.1", 55432, $null, $null)
    if (-not ($iar.AsyncWaitHandle.WaitOne(500) -and $client.Connected)) {
        throw "PostgreSQL tunnel is not listening on 127.0.0.1:55432. Run START_DB_TUNNEL.ps1 first."
    }
} finally { $client.Close() }

# Reuse an already-running qualified AgentPi service when present.
$agentPiAlreadyRunning = $false
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/rest/api/v1/health" -TimeoutSec 2
    if ($health.status -eq "ok") {
        $agentPiAlreadyRunning = $true
        Write-Host "Reusing existing AgentPi service on 127.0.0.1:8765"
    }
} catch {}
if (-not $agentPiAlreadyRunning) {
    Start-LoggedProcess "agentpi" $AgentPy @("-m","backend") $AgentRoot
    Start-Sleep -Seconds 2
}
Start-LoggedProcess "dishchat-backend" $DishPy @((Join-Path $PSScriptRoot "run_dishchat_backend.py")) $Root
Start-Sleep -Seconds 4
Start-LoggedProcess "dishchat-frontend" $DishPy @((Join-Path $Root "dish-chat\frontend\server.py")) (Join-Path $Root "dish-chat\frontend")
if ($StartEnhanced) {
    Start-LoggedProcess "dishchat-enhanced" $DishPy @((Join-Path $Root "dish-chat\frontend\enhanced\server.py")) (Join-Path $Root "dish-chat\frontend\enhanced")
}
Start-Sleep -Seconds 2

function Check([string]$Name,[string]$Url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        Write-Host ("PASS {0,-18} {1} -> {2}" -f $Name,$Url,$r.StatusCode)
        return $true
    } catch {
        Write-Warning "FAIL $Name $Url :: $($_.Exception.Message)"
        return $false
    }
}

$ok = $true
$ok = (Check "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health") -and $ok
$ok = (Check "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health") -and $ok
$ok = (Check "DishChat classic" "http://127.0.0.1:3000/health") -and $ok
if ($StartEnhanced) {
    $ok = (Check "DishChat enhanced" "http://127.0.0.1:3001/api/health") -and $ok
}
if (-not $ok) {
    Write-Host "One or more health checks failed. Logs: $Logs"
    throw "Full stack did not become healthy"
}

Write-Host "============================================================"
Write-Host "AGENTPI001 FULL WINDOWS STACK RUNNING"
Write-Host "Classic chat:       http://127.0.0.1:3000/"
if ($StartEnhanced) { Write-Host "Enhanced dashboard: http://127.0.0.1:3001/ (legacy API contract)" }
Write-Host "DishChat API docs:   http://127.0.0.1:8000/api/docs"
Write-Host "AgentPi devices:     http://127.0.0.1:8765/"
Write-Host "============================================================"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:3000/" }
