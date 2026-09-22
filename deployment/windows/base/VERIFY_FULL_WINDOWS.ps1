param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
$DishBackend = Join-Path $Root "dish-chat\backend"
$DishPy = Join-Path $DishBackend ".venv-windows\Scripts\python.exe"
$AgentRoot = Join-Path $Root "AgentPi"
$AgentPy = Join-Path $AgentRoot ".venv-windows\Scripts\python.exe"
if (-not (Test-Path $DishPy)) { throw "DishChat venv missing" }
if (-not (Test-Path $AgentPy)) { throw "AgentPi venv missing" }
Push-Location $DishBackend
try {
    $env:PYTHONPATH=$DishBackend
    & $DishPy -c "from app.agent.agents.tools.registry import get_tools_set; names=[t.name for t in get_tools_set('agent_mode')]; print('Agent tools:', len(names)); assert 'agentpi_discover_devices' in names; assert 'agentpi_list_devices' in names; print('AGENTPI BRIDGE REGISTERED')"
    if ($LASTEXITCODE -ne 0) { throw "DishChat AgentPi bridge verification failed" }
} finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue; Pop-Location }
Push-Location $AgentRoot
try {
    & $AgentPy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "AgentPi regression suite failed" }
} finally { Pop-Location }
Write-Host "VERIFY PASS"
