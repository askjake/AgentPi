param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-Python313 {
    try {
        $out = & py -3.13 --version 2>&1
        if ($LASTEXITCODE -eq 0) { return "py -3.13" }
    } catch {}

    Write-Host "Python 3.13 is not installed. Installing per-user with winget..."
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw "winget is unavailable and Python 3.13 is required." }
    & winget.exe install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python 3.13 user-scope installation failed." }
    $out = & py -3.13 --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Python 3.13 installed but py launcher cannot resolve it yet. Open a new CMD/PowerShell and rerun setup." }
    return "py -3.13"
}

$null = Resolve-Python313
$DishBackend = Join-Path $Root "dish-chat\backend"
$DishVenv = Join-Path $DishBackend ".venv-windows"
$AgentRoot = Join-Path $Root "AgentPi"
$AgentVenv = Join-Path $AgentRoot ".venv-windows"

Write-Host "============================================================"
Write-Host "AGENTPI001 FULL WINDOWS SETUP"
Write-Host "Root: $Root"
Write-Host "============================================================"

if (-not (Test-Path $DishVenv)) {
    & py -3.13 -m venv $DishVenv
    if ($LASTEXITCODE -ne 0) { throw "DishChat venv creation failed" }
}
$DishPy = Join-Path $DishVenv "Scripts\python.exe"
& $DishPy -m pip install --upgrade pip setuptools wheel
& $DishPy -m pip install -r (Join-Path $PSScriptRoot "requirements-dishchat-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "DishChat dependency installation failed" }

if (-not (Test-Path $AgentVenv)) {
    & py -3.13 -m venv $AgentVenv
    if ($LASTEXITCODE -ne 0) { throw "AgentPi venv creation failed" }
}
$AgentPy = Join-Path $AgentVenv "Scripts\python.exe"
& $AgentPy -m pip install --upgrade pip setuptools wheel
& $AgentPy -m pip install -r (Join-Path $AgentRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "AgentPi dependency installation failed" }

Write-Host "== DishChat import gate =="
Push-Location $DishBackend
try {
    $env:PYTHONPATH = $DishBackend
    & $DishPy -c "import fastapi,uvicorn,sqlalchemy,psycopg,langchain,langgraph,boto3,mcp; from app.tools.agentpi_bridge import agentpi_health; print('DISHCHAT IMPORTS OK')"
    if ($LASTEXITCODE -ne 0) { throw "DishChat import gate failed" }
    & $DishPy -m pytest -q tests_windows
    if ($LASTEXITCODE -ne 0) { throw "DishChat Windows bridge tests failed" }
} finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "== AgentPi test gate =="
Push-Location $AgentRoot
try {
    & $AgentPy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "AgentPi test gate failed" }
} finally { Pop-Location }

Write-Host "============================================================"
Write-Host "SETUP PASS"
Write-Host "Next: run IMPORT_PI_CONFIG.ps1, START_DB_TUNNEL.ps1, then START_FULL_STACK.ps1"
Write-Host "============================================================"
