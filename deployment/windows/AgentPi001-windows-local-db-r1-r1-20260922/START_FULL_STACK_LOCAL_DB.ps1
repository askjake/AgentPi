param(
    [string]$Root = "",
    [switch]$OpenBrowser = $true
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
New-Item -ItemType Directory -Force -Path $Run,$Logs | Out-Null
$DishBackend = Join-Path $Root "dish-chat\backend"
$DishPy = Join-Path $DishBackend ".venv-windows\Scripts\python.exe"
$AgentRoot = Join-Path $Root "AgentPi"
$AgentPy = Join-Path $AgentRoot ".venv-windows\Scripts\python.exe"
if (-not (Test-Path $DishPy)) { throw "DishChat venv missing; run SETUP_FULL_WINDOWS.ps1" }
if (-not (Test-Path $AgentPy)) { throw "AgentPi venv missing; run SETUP_FULL_WINDOWS.ps1" }
if (-not (Test-Path (Join-Path $DishBackend "app\logs\router.py"))) { throw "DishChat app.logs source missing; run RECOVER_MISSING_APP_LOGS.ps1" }

& (Join-Path $PSScriptRoot "START_LOCAL_POSTGRES.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "Local PostgreSQL failed to start" }

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

$agentPiAlreadyRunning = $false
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/rest/api/v1/health" -TimeoutSec 2
    if ($health.status -eq "ok") { $agentPiAlreadyRunning = $true; Write-Host "Reusing existing AgentPi service on 127.0.0.1:8765" }
} catch {}
if (-not $agentPiAlreadyRunning) {
    Start-LoggedProcess "agentpi" $AgentPy @("-m","backend") $AgentRoot
}

$runner = Join-Path $PSScriptRoot "run_dishchat_backend_local.py"
Start-LoggedProcess "dishchat-backend" $DishPy @($runner) $Root
Start-LoggedProcess "dishchat-frontend" $DishPy @((Join-Path $Root "dish-chat\frontend\server.py")) (Join-Path $Root "dish-chat\frontend")

function Wait-Http([string]$Name,[string]$Url,[int]$Attempts=25) {
    for ($i=0; $i -lt $Attempts; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                Write-Host ("PASS {0,-18} {1} -> {2}" -f $Name,$Url,$r.StatusCode)
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    Write-Warning "FAIL $Name $Url"
    return $false
}

$ok = $true
$ok = (Wait-Http "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health" 10) -and $ok
$ok = (Wait-Http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 30) -and $ok
$ok = (Wait-Http "DishChat classic" "http://127.0.0.1:3000/health" 15) -and $ok
if (-not $ok) {
    Write-Host "One or more health checks failed. Backend stderr:"
    $err = Join-Path $Logs "dishchat-backend.err.log"
    if (Test-Path $err) { Get-Content $err -Tail 120 }
    throw "Full local-DB stack did not become healthy"
}
Write-Host "============================================================"
Write-Host "AGENTPI001 FULL WINDOWS + LOCAL DB RUNNING"
Write-Host "DishChat:  http://127.0.0.1:3000/"
Write-Host "Backend:   http://127.0.0.1:8000/api/docs"
Write-Host "AgentPi:   http://127.0.0.1:8765/"
Write-Host "Postgres:  127.0.0.1:55432 (private local cluster)"
Write-Host "============================================================"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:3000/" }
