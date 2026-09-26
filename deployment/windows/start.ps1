param([switch]$OpenBrowser)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")

$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
Ensure-Directory $Run
Ensure-Directory $Logs
Ensure-Directory (Join-Path $Run "workspaces")

# Force child Python processes to use UTF-8 even when stdout/stderr are redirected.
# Without this, Windows CP1252 can crash startup on Unicode log output.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Expose the DishChat web surface to the LAN. Keep AgentPi and PostgreSQL
# loopback-only because they are internal control/data-plane services.
$env:DISHCHAT_FRONTEND_HOST = "0.0.0.0"
$env:DISHCHAT_FRONTEND_PORT = "3000"
$env:AGENTPI_HOST = "127.0.0.1"
$env:AGENTPI_DB = Join-Path $Run "agentpi-devices.db"

function Test-LoopbackPortBindable([int]$Port) {
    $listener = $null
    try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            try { $listener.Stop() } catch {}
        }
    }
}

$AgentPiPortFile = Join-Path $Run "agentpi-port.txt"
$AgentPiPort = $null

# Prefer a previously selected port when it is already serving a healthy AgentPi.
if (Test-Path $AgentPiPortFile) {
    $saved = (Get-Content -LiteralPath $AgentPiPortFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $savedPort = 0
    if ([int]::TryParse("$saved", [ref]$savedPort) -and $savedPort -gt 0 -and $savedPort -lt 65536) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/rest/api/v1/health" -f $savedPort) -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $AgentPiPort = $savedPort }
        } catch {}
    }
}

# Windows may reserve 8765 (WinError 10013). Probe it first, then deterministic fallbacks.
if (-not $AgentPiPort) {
    foreach ($candidate in @(8765, 18765, 28765, 38765, 48765)) {
        if (Test-LoopbackPortBindable $candidate) {
            $AgentPiPort = $candidate
            break
        }
    }
}

if (-not $AgentPiPort) {
    throw "No usable loopback port found for AgentPi (tried 8765,18765,28765,38765,48765)."
}

$env:AGENTPI_PORT = "$AgentPiPort"
$env:AGENTPI_URL = "http://127.0.0.1:$AgentPiPort"
Set-Content -LiteralPath $AgentPiPortFile -Value $AgentPiPort -Encoding ASCII
Write-Host "AgentPi endpoint: $($env:AGENTPI_URL)"

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

$AgentPiHealthUrl = "$($env:AGENTPI_URL)/rest/api/v1/health"
if (-not (Is-Healthy $AgentPiHealthUrl)) {
    Start-ManagedProcess "agentpi" $AgentPy @("-m","backend") $Root
} else { Write-Host "Reusing healthy AgentPi on :$AgentPiPort" }

if (-not (Is-Healthy "http://127.0.0.1:8000/rest/api/v1/health")) {
    Start-ManagedProcess "dishchat-backend" $DishPy @($Runner) $Root
} else { Write-Host "Reusing healthy DishChat backend on :8000" }

if (-not (Is-Healthy "http://127.0.0.1:3000/health")) {
    Start-ManagedProcess "dishchat-frontend" $DishPy @($Frontend) (Join-Path $Root "dish-chat\frontend")
} else { Write-Host "Reusing healthy DishChat frontend on :3000" }

$ok = $true
$ok = (Wait-Http "AgentPi" $AgentPiHealthUrl 15) -and $ok
$ok = (Wait-Http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 40) -and $ok
$ok = (Wait-Http "DishChat frontend" "http://127.0.0.1:3000/health" 20) -and $ok
if (-not $ok) {
    $agentErr = Join-Path $Logs "agentpi.err.log"
    $backendErr = Join-Path $Logs "dishchat-backend.err.log"
    if (Test-Path $agentErr) {
        Write-Host "----- AgentPi stderr (tail) -----"
        Get-Content $agentErr -Tail 120
    }
    if (Test-Path $backendErr) {
        Write-Host "----- DishChat backend stderr (tail) -----"
        Get-Content $backendErr -Tail 120
    }
    throw "One or more services failed health checks."
}

try {
    $lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and
            $_.IPAddress -notlike "169.254.*"
        } |
        Select-Object -ExpandProperty IPAddress -Unique)
    foreach ($ip in $lanIps) {
        Write-Host ("LAN access: http://{0}:3000/  (backend http://{0}:8000/)" -f $ip)
    }
} catch {}

if ($OpenBrowser) { Start-Process "http://127.0.0.1:3000/" }
