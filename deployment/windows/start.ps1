param([switch]$OpenBrowser)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")

$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
Ensure-Directory $Run
Ensure-Directory $Logs
Ensure-Directory (Join-Path $Run "workspaces")

$AgentPy = Join-Path $Root ".venv-windows\Scripts\python.exe"
$DishPy = Join-Path $Root "dish-chat\backend\.venv-windows\Scripts\python.exe"
$Frontend = Join-Path $Root "dish-chat\frontend\server.py"
$Runner = Join-Path $PSScriptRoot "run_dishchat_backend.py"

foreach ($required in @($AgentPy,$DishPy,$Frontend,$Runner,(Join-Path $Run "local-db.env"))) {
    if (-not (Test-Path $required)) { throw "Missing required runtime file: $required. Run install.ps1 first." }
}

Start-AgentPiPostgres $Root

function Is-Healthy([string]$Url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Start-ManagedProcess(
    [string]$Name,
    [string]$Exe,
    [string[]]$ProcessArgs,
    [string]$Cwd
) {
    $pidFile = Join-Path $Run "$Name.pid"
    if (Test-Path $pidFile) {
        $pidValue = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            Write-Host "$Name already running as PID $pidValue"
            return
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    # Do not name this parameter $Args: $args is a PowerShell automatic
    # variable and the collision can produce an empty/null ArgumentList.
    $cleanArgs = @(
        $ProcessArgs |
            Where-Object { $null -ne $_ -and -not [string]::IsNullOrWhiteSpace([string]$_) } |
            ForEach-Object { [string]$_ }
    )

    $start = @{
        FilePath = $Exe
        WorkingDirectory = $Cwd
        RedirectStandardOutput = (Join-Path $Logs "$Name.out.log")
        RedirectStandardError = (Join-Path $Logs "$Name.err.log")
        PassThru = $true
    }
    if ($cleanArgs.Count -gt 0) {
        $start["ArgumentList"] = $cleanArgs
    }

    Write-Host ("Starting {0}: {1} {2}" -f $Name, $Exe, ($cleanArgs -join " "))
    $p = Start-Process @start
    Set-Content -LiteralPath $pidFile -Value $p.Id -Encoding ASCII
    Write-Host "$Name PID: $($p.Id)"
}

if (-not (Is-Healthy "http://127.0.0.1:8765/rest/api/v1/health")) {
    Start-ManagedProcess "agentpi" $AgentPy @("-m","backend") $Root
} else { Write-Host "Reusing healthy AgentPi on :8765" }

if (-not (Is-Healthy "http://127.0.0.1:8000/rest/api/v1/health")) {
    Start-ManagedProcess "dishchat-backend" $DishPy @($Runner) $Root
} else { Write-Host "Reusing healthy DishChat backend on :8000" }

if (-not (Is-Healthy "http://127.0.0.1:3000/health")) {
    Start-ManagedProcess "dishchat-frontend" $DishPy @($Frontend) (Join-Path $Root "dish-chat\frontend")
} else { Write-Host "Reusing healthy DishChat frontend on :3000" }

$ok = $true
$ok = (Wait-Http "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health" 15) -and $ok
$ok = (Wait-Http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 40) -and $ok
$ok = (Wait-Http "DishChat frontend" "http://127.0.0.1:3000/health" 20) -and $ok
if (-not $ok) {
    $err = Join-Path $Logs "dishchat-backend.err.log"
    if (Test-Path $err) { Get-Content $err -Tail 120 }
    throw "One or more services failed health checks."
}

if ($OpenBrowser) { Start-Process "http://127.0.0.1:3000/" }
