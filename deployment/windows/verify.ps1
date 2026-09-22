$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"

$ok = $true
$ok = (Wait-Http "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health" 3) -and $ok
$ok = (Wait-Http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 3) -and $ok
$ok = (Wait-Http "DishChat frontend" "http://127.0.0.1:3000/health" 3) -and $ok

Start-AgentPiPostgres $Root
$pg = Get-PgPaths $Root
$db = Read-DotEnv $pg.Env
$env:PGPASSWORD = $db["POSTGRES_PWD"]
try {
    $psql = Join-Path $pg.Bin "psql.exe"
    $query = "SELECT (SELECT version_num FROM alembic_version LIMIT 1), (SELECT extname FROM pg_extension WHERE extname='uuid-ossp');"
    $result = (& $psql -h 127.0.0.1 -p 55432 -U $db["POSTGRES_USER"] -d $db["POSTGRES_DB"] -v ON_ERROR_STOP=1 -Atc $query | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0) { throw "Database verification failed." }
    $value = "$result".Trim()
    if ($value -ne "20260918_fix_message_role_enum|uuid-ossp") {
        throw "Unexpected database state: $value"
    }
    Write-Host "DB_STATE=$value"
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Push-Location $Root
try {
    $sha = (& git rev-parse HEAD).Trim()
    Write-Host "GIT_SHA=$sha"
} finally { Pop-Location }

if (-not $ok) { throw "HTTP health verification failed." }
Write-Host "AGENTPI001 WINDOWS VERIFY PASS"
