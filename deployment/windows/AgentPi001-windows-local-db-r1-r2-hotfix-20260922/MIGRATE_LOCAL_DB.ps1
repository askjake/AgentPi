param([string]$Root = "")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$EnvFile = Join-Path $Run "local-db.env"
$Backend = Join-Path $Root "dish-chat\backend"
$DishPy = Join-Path $Backend ".venv-windows\Scripts\python.exe"
if (-not (Test-Path $EnvFile)) { throw "Missing $EnvFile" }
if (-not (Test-Path $DishPy)) { throw "DishChat Windows venv missing: $DishPy" }

function Import-LocalEnv([string]$Path) {
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = $line.Split('=',2)
        if ($parts.Count -eq 2) { [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process") }
    }
}
Import-LocalEnv $EnvFile

# Required by journal_001: server_default uuid_generate_v4().
& (Join-Path $PSScriptRoot "ENABLE_UUID_OSSP.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "uuid-ossp prerequisite failed" }

$env:PYTHONPATH = $Backend
$AppDir = Join-Path $Backend "app"
Push-Location $AppDir
try {
    Write-Host "Running DishChat Alembic migrations against LOCAL PostgreSQL..."
    & $DishPy -m alembic -c alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
    & $DishPy -m alembic -c alembic.ini current
    if ($LASTEXITCODE -ne 0) { throw "Alembic current failed" }
} finally {
    Pop-Location
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}

$probePath = Join-Path $Run "probe-local-db.py"
$probe = @'
import os
import psycopg

conn = psycopg.connect(
    host=os.environ["POSTGRES_HOST"],
    port=int(os.environ["POSTGRES_PORT"]),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PWD"],
)
with conn, conn.cursor() as cur:
    cur.execute("show server_version")
    version = cur.fetchone()[0]
    cur.execute("select version_num from alembic_version order by version_num")
    revisions = [row[0] for row in cur.fetchall()]
    cur.execute("select count(*) from information_schema.tables where table_schema='public'")
    tables = cur.fetchone()[0]
    cur.execute("select extname from pg_extension where extname='uuid-ossp'")
    uuid_ossp = cur.fetchone()
print(f"LOCAL_DB_SERVER={version}")
print("ALEMBIC_REVISIONS=" + ",".join(revisions))
print(f"PUBLIC_TABLES={tables}")
print("UUID_OSSP=" + (uuid_ossp[0] if uuid_ossp else "MISSING"))
assert "20260918_fix_message_role_enum" in revisions, revisions
assert tables > 0
assert uuid_ossp and uuid_ossp[0] == "uuid-ossp"
'@
Set-Content -LiteralPath $probePath -Value $probe -Encoding UTF8
try {
    & $DishPy $probePath
    if ($LASTEXITCODE -ne 0) { throw "Local DB post-migration probe failed" }
} finally {
    Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
}
Write-Host "LOCAL DB MIGRATION PASS"
